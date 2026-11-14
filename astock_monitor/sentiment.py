"""情绪/宽度数据采集层(2026-11-13 调研定案,详见 docs/optimization-roadmap.md)。

两个时限性结论(侦察实证):
1. **涨停池全家桶(push2ex)东财仅保留约 3 周历史,不可回补**——每日收盘后各 1 次
   落库,晚一天永远缺一天。连板高度/炸板率/昨涨停溢价是 A 股情绪分信息量最高的成分。
2. **两融余额(stock_margin_account_info)单次调用回补 2012-09 至今全量**——
   成本最低的慢变量杠杆情绪,日频平滑,此后每日增量。

宽度历史不加外部接口:湖内 daily_bars 带 pre_close,直接回算(breadth_history,见 roadmap)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .collect import guarded_call
from .config import resolve_path
from .store import has_task, log_event, record_task, task_key, write_parquet_atomic


def collect_zt_pool(cfg: dict, conn, day: date | None = None,
                    fetchers: dict | None = None, limiter=None) -> dict:
    """涨停池 + 昨涨停表现,各 1 次请求(不可回补,幂等:当日已有即跳过)。"""
    day = day or date.today()
    d8 = f"{day:%Y%m%d}"
    params = {"day": day.isoformat()}
    tkey = task_key("akshare", "zt_pool", params)
    if has_task(conn, tkey) is not None:
        return {"status": "skipped", "task_key": tkey}

    if fetchers is None:
        import akshare as ak  # noqa: PLC0415

        fetchers = {"zt": ak.stock_zt_pool_em, "prev": ak.stock_zt_pool_previous_em}
    limiter = limiter or _limiter(cfg)
    out = {}
    for name, fn in fetchers.items():
        raw = guarded_call(limiter, fn, date=d8)
        raw_dir = resolve_path(cfg, "paths.lake_raw") / "akshare" / name / f"dt={d8}"
        path = write_parquet_atomic(raw, raw_dir / "part.parquet")
        out[name] = {"rows": 0 if raw is None else len(raw), "path": str(path)}
    record_task(conn, tkey, "akshare", "zt_pool", params,
                sum(v["rows"] for v in out.values()), day.isoformat(), day.isoformat(),
                out.get("zt", {}).get("path"))
    log_event(conn, "INFO", "collect_zt_pool", f"{day} {out}")
    return {"status": "ok", "task_key": tkey, **{k: v["rows"] for k, v in out.items()}}


def backfill_margin(cfg: dict, conn, fetcher=None, limiter=None) -> dict:
    """两融余额单次全量回补(2012-09 起);幂等:已回补即跳过。"""
    params = {"dataset": "margin_account"}
    tkey = task_key("akshare", "margin", params)
    if has_task(conn, tkey) is not None:
        return {"status": "skipped", "task_key": tkey}

    if fetcher is None:
        import akshare as ak  # noqa: PLC0415

        fetcher = ak.stock_margin_account_info
    limiter = limiter or _limiter(cfg)
    raw = guarded_call(limiter, fetcher)
    if raw is None or len(raw) == 0:
        raise ValueError("两融接口返回空")
    raw_dir = resolve_path(cfg, "paths.lake_raw") / "akshare" / "margin"
    path = write_parquet_atomic(raw, raw_dir / "part.parquet")
    record_task(conn, tkey, "akshare", "margin", params, len(raw), None, None, str(path))
    log_event(conn, "INFO", "backfill_margin", f"rows={len(raw)}")
    return {"status": "ok", "rows": len(raw), "path": str(path)}


def compute_breadth_history(bars_df, ma_windows: tuple[int, ...] = (20, 60)) -> "object":
    """从湖内 daily_bars 回算宽度历史(T2107/T2108 式 + 涨跌家数占比)。

    输入:湖 daily_bars(symbol, trade_date, close, pre_close)。
    口径声明:分母 = 当日有行情的样本(800 只成分口径,幸存者偏差同湖, METHODS L6);
    每股 MA 用自身历史(不足窗口剔除),天然只用 ≤T 数据(防泄漏)。
    返回 DataFrame(date, up_ratio, above_ma20, above_ma60, ...)。惰性 pandas。
    """
    import pandas as pd  # noqa: PLC0415

    df = bars_df.sort_values(["symbol", "trade_date"])
    df = df.assign(_chg=df.groupby("symbol")["close"].pct_change())
    for w in ma_windows:
        df[f"_above_ma{w}"] = df["close"] > df.groupby("symbol")["close"].transform(
            lambda s: s.rolling(w).mean())
    daily = df.groupby("trade_date").agg(
        up_ratio=("_chg", lambda s: float((s > 0).sum() / (s.abs() > 1e-12).sum()) if (s.abs() > 1e-12).sum() else None),
        n=("symbol", "nunique"),
        **{f"above_ma{w}": (f"_above_ma{w}", "mean") for w in ma_windows},
    )
    daily = daily.reset_index().rename(columns={"trade_date": "date"})
    return daily


def load_margin_greed(lake_raw: Path, rank_window: int = 500) -> dict:
    """两融余额 → 贪婪度 0-100(滚动分位;杠杆升高=贪婪=危险,csqaq 反向锚点口径)。

    输入:raw/akshare/margin/part.parquet(stock_margin_account_info 全量回补)。
    惰性 pandas;分位池不含当日(防泄漏,同 regime.vol_pct 口径)。
    """
    import pandas as pd  # noqa: PLC0415

    path = Path(lake_raw) / "akshare" / "margin" / "part.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    date_col = next(c for c in df.columns if "日期" in c or c.lower() == "date")
    bal_col = next(c for c in df.columns if "融资余额" in str(c))
    df = df[[date_col, bal_col]].copy()
    df.columns = ["date", "balance"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df["greed"] = (df["balance"].rolling(rank_window).rank(pct=True) * 100).shift(1)
    # shift(1):分位池不含当日——T 日贪婪度只反映 ≤T-1(与 regime.vol_pct 同纪律)
    return {d: float(v) for d, v in zip(df["date"], df["greed"]) if pd.notna(v)}


def _limiter(cfg: dict):
    from .collect import RateLimiter
    c = cfg["collect"]
    return RateLimiter(min_interval=c["min_interval_seconds"],
                       state_path=resolve_path(cfg, "collect.cooldown_file"),
                       backoff_initial=c["backoff_initial_seconds"],
                       backoff_max=c["backoff_max_seconds"])
