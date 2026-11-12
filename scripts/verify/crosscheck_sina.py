#!/usr/bin/env python3
"""湖数据第二源交叉验证(CNEquity TDX vs 新浪)——L5 双源纪律的第一次实弹。

抽 3 只股,逐日比对 OHLC(容差 0.01,复权口径:双方都用不复权价)。
新浪 stock_zh_a_daily 为不复权日_price;湖 daily_bars 默认含复权因子,
此处只取 close 与新浪 close 比对;若湖为后复权口径则改比比率(见输出标注)。

用法: WorkBuddy venv python(需 cnequity 包读湖)或系统 python+pyarrow 直接读 parquet。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SAMPLE = ["000001.SZ", "600519.SH", "300123.SZ"]

import pandas as pd  # noqa: E402
import akshare as ak  # noqa: E402

lake = REPO_ROOT / "data" / "cnequity-lake"


def lake_all_bars() -> pd.DataFrame:
    files = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
    if not files:
        raise FileNotFoundError("湖内无 daily_bars 分区")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    return df.rename(columns={"trade_date": "date"})


def lake_symbols(df: pd.DataFrame) -> list[str]:
    col = "symbol" if "symbol" in df.columns else df.columns[0]
    return sorted(df[col].unique().tolist())


def lake_daily_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    col = "symbol" if "symbol" in df.columns else df.columns[0]
    return df[df[col] == symbol]


def sina_daily(code6: str) -> pd.DataFrame:
    sym = ("sh" if code6.startswith("6") else "sz") + code6
    df = ak.stock_zh_a_daily(symbol=sym)
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["date", "close"]]


def main() -> int:
    overall = True
    all_bars = lake_all_bars()
    in_lake = lake_symbols(all_bars)
    symbols = [s for s in SAMPLE if s in in_lake] or in_lake[:3]
    print(f"湖内可用 {len(in_lake)} 只,抽验: {symbols}")
    for symbol in symbols:
        code6 = symbol.split(".")[0]
        try:
            ldf = lake_daily_bars(all_bars, symbol)[["date", "close", "source"]]
            sdf = sina_daily(code6)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {symbol}: {type(e).__name__}: {e}")
            overall = False
            continue
        m = ldf.merge(sdf, on="date", suffixes=("_lake", "_sina"))
        if m.empty:
            print(f"[FAIL] {symbol}: 湖 {len(ldf)} 行 vs 新浪 {len(sdf)} 行,日期交集为空")
            overall = False
            continue
        diff = (m["close_lake"].astype(float) - m["close_sina"].astype(float)).abs()
        ratio_diff = ((m["close_lake"].astype(float) / m["close_sina"].astype(float)) - 1).abs()
        exact = int((diff <= 0.011).sum())
        # 若湖是复权口径,close 会有恒定比率差——比率标准差极小而均值大 → 口径差异而非数据错误
        caliber = "复权口径差异(比率恒定)" if ratio_diff.mean() > 0.02 and ratio_diff.std() < 0.005 else "逐日一致"
        ok = exact >= len(m) * 0.95 or "复权" in caliber
        print(f"[{'PASS' if ok else 'FAIL'}] {symbol}: 交集 {len(m)} 天, "
              f"close 逐日一致 {exact}/{len(m)}, 平均比差 {ratio_diff.mean():.4f}, 判读: {caliber}")
        overall = overall and ok
    print("OVERALL:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
