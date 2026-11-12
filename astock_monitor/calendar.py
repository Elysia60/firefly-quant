"""交易日历层(PoC-4 定案:CNEquity 湖为主源,新浪对拍兜底,缓存 JSON 供离线)。

两条接口约定(第 3 周固化,METHODS.md §3 为语义正本):
1. 回测:run_backtest(..., trading_calendar=trading_days(...)) — AKQuant 不传日历会在
   假日真实成交(PoC-4 撮合级证据),必传。
2. 对账:add_trading_days(d, n) 判卷窗口按交易日数计算,长假不漂移。

纯函数(add_trading_days 等)零依赖;Parquet 读取惰性导入 pandas。
"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date
from pathlib import Path


def read_cnequity_calendar(lake_dir: str | Path) -> list[date]:
    """读 CNEquity 湖 curated/trading_calendar 分区,返回升序交易日列表。

    湖结构(见 PoC-4):curated/trading_calendar/trade_date=*/part-merged.parquet,
    列 trade_date(date)+ is_trading(0/1)。惰性导入 pandas。
    """
    import pandas as pd  # noqa: PLC0415 — 数据路径才需要

    lake = Path(lake_dir)
    files = sorted(lake.glob("curated/trading_calendar/trade_date=*/part-merged.parquet"))
    if not files:
        raise FileNotFoundError(f"CNEquity 湖无 trading_calendar 分区: {lake}")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    mask = df["is_trading"].astype(bool)
    days = pd.to_datetime(df.loc[mask, "trade_date"]).dt.date.tolist()
    if not days:
        raise ValueError(f"CNEquity 湖 trading_calendar 无交易日: {lake}")
    return sorted(set(days))


def fetch_sina_calendar() -> list[date]:
    """新浪源交易日历(akshare tool_trade_date_hist_sina,PoC-2/4 实测可用)。

    联网调用;东财限流不影响该接口(新浪源)。惰性导入 akshare。
    """
    import akshare as ak  # noqa: PLC0415

    df = ak.tool_trade_date_hist_sina()
    days = pd_to_dates(df["trade_date"])
    if not days:
        raise ValueError("新浪交易日历返回空")
    return days


def pd_to_dates(series) -> list[date]:
    import pandas as pd  # noqa: PLC0415

    return sorted(set(pd.to_datetime(series).dt.date.tolist()))


def crosscheck(a: list[date], b: list[date]) -> dict:
    """两源日历对拍(PoC-4 A2 口径):交集窗口内零分歧才 identical=True。"""
    set_a, set_b = set(a), set(b)
    lo, hi = max(min(set_a), min(set_b)), min(max(set_a), max(set_b))
    if lo > hi:
        return {"status": "no_overlap", "identical": False}
    only_a = sorted(d for d in set_a if lo <= d <= hi and d not in set_b)
    only_b = sorted(d for d in set_b if lo <= d <= hi and d not in set_a)
    return {
        "status": "compared",
        "window": [lo.isoformat(), hi.isoformat()],
        "count_a": sum(1 for d in set_a if lo <= d <= hi),
        "count_b": sum(1 for d in set_b if lo <= d <= hi),
        "only_in_a": [d.isoformat() for d in only_a[:20]],
        "only_in_b": [d.isoformat() for d in only_b[:20]],
        "identical": not only_a and not only_b,
    }


def trading_days(days: list[date], start: date | None = None, end: date | None = None) -> list[date]:
    """升序交易日列表切片(含端点)。"""
    out = sorted(days)
    if start is not None:
        out = [d for d in out if d >= start]
    if end is not None:
        out = [d for d in out if d <= end]
    return out


def next_trading_day(d: date, days: list[date]) -> date:
    """严格晚于 d 的第一个交易日;越界抛 ValueError(fail loud,不静默回绕)。"""
    idx = bisect_right(days, d)
    if idx >= len(days):
        raise ValueError(f"日历覆盖到 {days[-1]},无法给出晚于 {d} 的交易日")
    return days[idx]


def add_trading_days(d: date, n: int, days: list[date]) -> date:
    """窗口加法(METHODS.md §3 语义正本)。

    n >= 1: 严格晚于 d 的第 n 个交易日(判卷 T+n 用);
    n == 0: d 当天若为交易日返回 d,否则返回下一交易日。
    """
    if n < 0:
        raise ValueError("n 不支持负数(窗口只向前)")
    if n == 0:
        return d if d in set(days) else next_trading_day(d, days)
    idx = bisect_right(days, d) + n - 1
    if idx >= len(days):
        raise ValueError(f"日历覆盖到 {days[-1]},不足以给出 {d}+{n} 交易日")
    return days[idx]


def cache_to_json(days: list[date], path: str | Path) -> Path:
    """日历缓存落盘(离线兜底;collect/doctor 优先读湖,湖不可达读此缓存)。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"days": [d.isoformat() for d in sorted(set(days))]}, ensure_ascii=False), encoding="utf-8")
    return p


def load_calendar_cache(path: str | Path) -> list[date] | None:
    """读日历缓存;缺失/损坏返回 None(调用方降级,不静默造数据)。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return [date.fromisoformat(s) for s in raw["days"]]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
