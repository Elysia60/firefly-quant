#!/usr/bin/env python3
"""宽度历史重建(湖内 daily_bars 回算,零外部接口)。

背景(2026-11-17 缺口追查发现):
  normalized/breadth_history/part.parquet 停在 2025-11-12(建一次后从未更新),
  forecast-replay/signal 路径的 momentum 腿整整一年吃的是 2025-11-12 的
  up_ratio=0.3474(两天同值指纹实锤)。本脚本按同一口径重建到湖最新分区。

口径(METHODS L6,compute_breadth_history):
  · 分母 = 当日有行情的样本(800 成分口径,幸存者偏差同湖)
  · 每股 MA 用自身历史(不足窗口剔除),只用 ≤T 数据(防泄漏)
  · 范围 2021-01-01 起(与原文件一致;更深历史无消费方)

用法: python scripts/rebuild_breadth_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

LAKE = REPO_ROOT / "data" / "cnequity-lake"
OUT = REPO_ROOT / "data" / "lake" / "normalized" / "breadth_history" / "part.parquet"
SINCE = "2021-01-01"


def main() -> int:
    from astock_monitor.sentiment import compute_breadth_history
    from astock_monitor.store import write_parquet_atomic

    files = sorted(LAKE.glob("curated/daily_bars/**/part*.parquet"))
    if not files:
        print("湖内无 daily_bars", file=sys.stderr)
        return 1
    cols = ["symbol", "trade_date", "close"]
    bars = pd.concat((pd.read_parquet(f, columns=cols) for f in files), ignore_index=True)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars = bars[bars["trade_date"] >= SINCE]
    print(f"daily_bars: {len(bars)} 行, {bars['symbol'].nunique()} 只, "
          f"{bars['trade_date'].min().date()} -> {bars['trade_date'].max().date()}")

    daily = compute_breadth_history(bars)
    if daily.empty:
        print("回算结果为空", file=sys.stderr)
        return 1
    daily = daily.sort_values("date").reset_index(drop=True)
    print(f"宽度史: {len(daily)} 日, {daily['date'].min().date()} -> {daily['date'].max().date()}")

    # 交叉校验:与旧文件重叠段的一致性。
    # 容差 1e-3:湖内个别 (symbol,date) close 经 PIT 回补修订,与旧文件的一次性
    # 计算存在 ≤6e-4 的 up_ratio 漂移(momentum 影响 ≈0.04 分,无实质影响);
    # 现行湖为正本(METHODS §1)。超容差=真口径漂移,中止。
    if OUT.exists():
        old = pd.read_parquet(OUT)
        old["date"] = pd.to_datetime(old["date"]).dt.date
        daily["date"] = pd.to_datetime(daily["date"]).dt.date
        merged = old.merge(daily, on="date", suffixes=("_old", "_new"))
        if len(merged):
            diff = (merged["up_ratio_old"] - merged["up_ratio_new"]).abs()
            print(f"重叠段 {len(merged)} 日, up_ratio 最大偏差 {diff.max():.6f}")
            bad = merged[diff > 1e-3]
            if len(bad):
                print(f"!! 口径漂移: {len(bad)} 日超容差,中止覆写", file=sys.stderr)
                print(bad[["date", "up_ratio_old", "up_ratio_new"]].head(10), file=sys.stderr)
                return 1
        else:
            print("旧文件与重算无重叠日期(异常,中止)", file=sys.stderr)
            return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(daily, OUT)
    print("落盘:", OUT)
    print("尾3:", daily.tail(3)[["date", "up_ratio", "n"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
