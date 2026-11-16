#!/usr/bin/env python3
"""指数 bar 缺口回补(EM 指数日线,历史日期可达)。

背景(2026-11-17):
  · 11-13 计划任务静默失败(旧 bat 无日志)+ 11-16 EM push2 断连 rc=1 →
    湖 index_bars 缺 11-13/11-16 两个交易日,信号引擎断粮。
  · cne(TDX) 本机当前不可用 → 指数走 akshare EM 日线历史接口(push2his,
    与被限流的 push2 spot 不同端点,1 请求/指数)。
  · 个股 bar 对历史日期无免费批量源,缺口按缺口纪律降级(banner),不硬补。

纪律:
  · 只补 < 今天的已完成交易日(盘中 bar 不完整,不碰)。
  · 已存在 (symbol, trade_date) 的行绝不重写(幂等,PIT)。
  · 新行写独立 part 文件,不动 part-merged(湖既定模式:part-<hash> 并存)。
  · pre_close 与湖内 tdx 行一致保持 NaN;source=akshare_em 可溯源。

用法:
  python scripts/backfill_index_gap.py            # 检测缺口并回补
  python scripts/backfill_index_gap.py --dry-run  # 只列出缺口,不联网
"""
from __future__ import annotations

import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

LAKE = REPO_ROOT / "data" / "cnequity-lake"
INDEX_SYMBOLS = [
    "000300.SH", "000001.SH", "000016.SH", "000688.SH",
    "000852.SH", "000905.SH", "399001.SZ", "399006.SZ",
]
LOOKBACK_DAYS = 30          # 只看近 30 个自然日内的缺口(历史大洞走 TDX,不归本脚本)
SOURCE = "akshare_sina"


def load_index_frame() -> pd.DataFrame:
    files = sorted(LAKE.glob("curated/index_bars/**/*.parquet"))
    if not files:
        raise FileNotFoundError(f"湖内无 index_bars: {LAKE}")
    cols = ["symbol", "trade_date", "close"]
    return pd.concat((pd.read_parquet(f, columns=cols) for f in files), ignore_index=True)


def find_gaps(existing: pd.DataFrame) -> list[tuple[str, date]]:
    """返回 [(symbol, 缺失交易日)]。

    基准必须是独立交易日历(湖 curated/trading_calendar),不能用湖内已出现日期:
    全体指数同时缺的日子(如采集中断)不在后者里,会漏检。
    """
    from astock_monitor.calendar import read_cnequity_calendar
    today = date.today()
    cutoff = (pd.Timestamp(today) - pd.Timedelta(days=LOOKBACK_DAYS)).date()
    calendar = read_cnequity_calendar(LAKE)          # 升序 list[date]
    recent_days = [d for d in calendar if cutoff <= d < today]
    ex = existing[pd.to_datetime(existing["trade_date"]).dt.date >= cutoff]
    have = {(r["symbol"], r["trade_date"].date() if hasattr(r["trade_date"], "date")
             else r["trade_date"]) for _, r in ex.iterrows()}
    gaps = []
    for sym in INDEX_SYMBOLS:
        for d in recent_days:
            if (sym, d) not in have:
                gaps.append((sym, d))
    return gaps


def symbol_em(symbol: str) -> str:
    """000300.SH -> sh000300; 399001.SZ -> sz399001"""
    code, _, exch = symbol.partition(".")
    return ("sh" if exch == "SH" else "sz") + code


def fetch_index_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """新浪指数日线(stock_zh_index_daily,全史一次)。

    主源本应是 EM push2his(index_zh_a_hist),但 2026-11-16 起本机 IP 对 EM
    数据端点被 WAF 拒(主站 200、带参数即断连)→ 备源新浪。[S1] 已对拍验证。
    注意: 新浪 volume 为股数,湖内 tdx 行为手 → /100 换算;无成交额列 → NaN。
    """
    import akshare as ak  # noqa: PLC0415
    df = ak.stock_zh_index_daily(symbol=symbol_em(symbol))
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"date": "trade_date"})
    keep = [c for c in ("trade_date", "open", "high", "low", "close", "volume")
            if c in df.columns]
    df = df[keep].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = (df["volume"] / 100.0).round().astype("Int64")  # 股→手
    s, e = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    return df[(df["trade_date"] >= s) & (df["trade_date"] <= e)]


def write_part(rows: pd.DataFrame) -> Path:
    out_dir = LAKE / "curated" / "index_bars" / "trade_date=2026"
    out_dir.mkdir(parents=True, exist_ok=True)
    part = out_dir / f"part-{uuid.uuid4().hex[:12]}.parquet"
    rows.to_parquet(part, index=False)
    return part


def main() -> int:
    dry = "--dry-run" in sys.argv
    existing = load_index_frame()
    gaps = find_gaps(existing)
    if not gaps:
        print("index_bars 无近 30 日缺口,无需回补")
        return 0
    syms = sorted({s for s, _ in gaps})
    days = sorted({d for _, d in gaps})
    print(f"缺口: {len(gaps)} 格 ({len(syms)} 指数 x {len(days)} 日)")
    for sym in syms:
        sym_gaps = [d for s, d in gaps if s == sym]
        print(f"  {sym}: {[str(d) for d in sym_gaps]}")
    if dry:
        print("[dry-run] 未联网")
        return 0

    start_s = (pd.Timestamp(days[0]) - pd.Timedelta(days=5)).strftime("%Y%m%d")
    end_s = pd.Timestamp(days[-1]).strftime("%Y%m%d")
    have = {(r["symbol"], r["trade_date"].date() if hasattr(r["trade_date"], "date")
             else r["trade_date"]) for _, r in existing.iterrows()}
    out_frames = []
    for i, sym in enumerate(syms):
        df = fetch_index_daily(sym, start_s, end_s)
        if df.empty:
            print(f"  {sym}: EM 无返回,跳过")
            continue
        new = df[~df.apply(lambda r: (sym, r["trade_date"]) in have, axis=1)]
        new = new[new["trade_date"] < date.today()]  # 盘中不完整,不碰今天
        if new.empty:
            print(f"  {sym}: 无新增(均已存在)")
        else:
            new.insert(0, "symbol", sym)
            new["pre_close"] = float("nan")
            new["source"] = SOURCE
            new["data_version"] = "v1"
            new["fetched_at"] = pd.Timestamp(datetime.now(timezone.utc))
            new["frequency"] = "1d"
            out_frames.append(new)
            print(f"  {sym}: +{len(new)} 行 {[str(d) for d in new['trade_date']]}")
        if i < len(syms) - 1:
            time.sleep(1.0)  # EM 指数端点礼貌间隔
    if not out_frames:
        print("无任何新增行,不写盘")
        return 1
    all_rows = pd.concat(out_frames, ignore_index=True)
    part = write_part(all_rows)
    print(f"落盘: {part} ({len(all_rows)} 行)")

    # 复验
    chk = load_index_frame()
    chk_gaps = [g for g in find_gaps(chk)]
    print(f"复验: 剩余缺口 {len(chk_gaps)} 格")
    return 0 if not chk_gaps else 1


if __name__ == "__main__":
    raise SystemExit(main())
