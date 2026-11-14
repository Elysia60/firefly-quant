"""Alpha158-lite 因子面板与单因子 IC 检验(P5 ML 层地基;roadmap P5)。

因子定案(Alpha158 五类收敛的 MVP 9 因子,公式对照 qlib contrib/data/loader.py):
  K线: KMID=(c-o)/o · KSFT=(2c-h-l)/o                     (无窗,当日形态)
  动量: ROC5 / ROC20 = close.shift(k)/close − 1            (过去 k 日收益)
  波动: STD20 = rolling(20).std(日收益)
  极值: RSV20 = (c−min20)/(max20−min20)                    (类 KDJ 位置)
  量价: CORR20 = rolling corr(close, volume, 20) · CNTP20 = 20 日上涨天数占比 ·
        VMA20 = volume / rolling(volume,20).mean()         (量比)

标签口径(8 条清单 #1,一票否决的唯一函数):
  label_raw(t) = close[t+1+N]/close[t+1] − 1   (T 收盘出信号,T+1 成交,T+1+N 出)
  评估用 Spearman IC——对截面单调变换不变,故 excess/rank 在 IC 环节可省;
  进模型训练时再按清单做 excess+rank(同一函数加参数)。

防泄漏:全部因子只用 ≤T 数据(shift 方向已钉死并有测试);label 用未来属本职。
"""

from __future__ import annotations

from pathlib import Path


def compute_factor_panel(bars: "object") -> "object":
    """bars: DataFrame(symbol, trade_date, open, high, low, close, volume)。

    返回长表 DataFrame(symbol, date, <因子列>…)。惰性 pandas;全部 shift 方向只向过去。
    """
    import pandas as pd  # noqa: PLC0415

    df = bars.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = df.groupby("symbol", sort=False)

    df["KMID"] = (df["close"] - df["open"]) / df["open"]
    df["KSFT"] = (2 * df["close"] - df["high"] - df["low"]) / df["open"]
    df["ROC5"] = df.groupby("symbol")["close"].shift(5) / df["close"] - 1
    df["ROC20"] = df.groupby("symbol")["close"].shift(20) / df["close"] - 1
    df["STD20"] = g["close"].pct_change().transform(lambda s: s.rolling(20).std())
    min20 = g["close"].transform(lambda s: s.rolling(20).min())
    max20 = g["close"].transform(lambda s: s.rolling(20).max())
    df["RSV20"] = (df["close"] - min20) / (max20 - min20).where((max20 - min20) > 0)
    df["CORR20"] = g["close"].transform(lambda s: s.rolling(20).corr(df.loc[s.index, "volume"]))
    df["CNTP20"] = g["close"].pct_change().gt(0).transform(lambda s: s.rolling(20).mean())
    df["VMA20"] = df["volume"] / g["volume"].transform(lambda s: s.rolling(20).mean())

    cols = ["symbol", "trade_date", "KMID", "KSFT", "ROC5", "ROC20", "STD20",
            "RSV20", "CORR20", "CNTP20", "VMA20"]
    out = df[cols].rename(columns={"trade_date": "date"})
    return out


def forward_label(panel: "object", closes: "object", horizon: int = 20) -> "object":
    """label_raw(t) = close[t+1+N]/close[t+1] − 1,逐股计算后并回长表。

    closes: DataFrame(symbol, trade_date, close)。label 的未来性是本职(标签),
    末尾 horizon+1 天为 NaN(样本未到期,不造数)。
    """
    import pandas as pd  # noqa: PLC0415

    cl = closes.copy()
    cl["trade_date"] = pd.to_datetime(cl["trade_date"])
    cl = cl.sort_values(["symbol", "trade_date"])
    g = cl.groupby("symbol", sort=False)
    cl["label_raw"] = g["close"].shift(-(1 + horizon)) / g["close"].shift(-1) - 1
    lab = cl[["symbol", "trade_date", "label_raw"]].rename(
        columns={"trade_date": "date"})
    # 日期键归一(调用方的 panel.date 可能是 str 或 Timestamp,统一转 datetime 再并)
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    lab["date"] = pd.to_datetime(lab["date"])
    return panel.merge(lab, on=["symbol", "date"], how="left")


def daily_spearman_ic(panel: "object", factor: str, min_n: int = 300) -> "object":
    """逐日截面 Spearman IC(Spearman 对截面单调变换不变——excess/rank 可省)。

    min_n:当日有效样本不足则跳过(防小截面伪 IC)。
    """
    import pandas as pd  # noqa: PLC0415

    df = panel.dropna(subset=[factor, "label_raw"])
    out = {}
    for d, g in df.groupby("date"):
        if len(g) < min_n:
            continue
        ic = g[factor].corr(g["label_raw"], method="spearman")
        if ic == ic:  # 非 NaN
            out[d] = float(ic)
    return pd.Series(out, name=f"IC_{factor}")


def ic_summary(ic_series: "object", nw_window: int = 20) -> dict:
    """IC 汇总:均值/ICIR/NW t(重叠窗=horizon,audit.newey_west_t)/正比例。

    调用方传入 nw_window=label horizon(重叠修正,呼应 METHODS §3c)。
    """
    from .audit import newey_west_t

    s = ic_series.dropna()
    if len(s) < 10:
        return {"n": len(s), "small_sample": True}
    mean = float(s.mean())
    std = float(s.std())
    icir = mean / std if std > 0 else 0.0
    t = newey_west_t(list(s.values), window=nw_window)
    by_year = {}
    for d, v in s.items():
        y = d.year if hasattr(d, "year") else d
        by_year.setdefault(y, []).append(v)
    years = {str(y): {"mean_ic": round(sum(v) / len(v), 5), "n": len(v),
                      "ic_gt_0": round(sum(1 for x in v if x > 0) / len(v), 3)}
             for y, v in sorted(by_year.items())}
    return {"n": int(len(s)), "mean_ic": round(mean, 5),
            "std": round(std, 5), "icir": round(icir, 3),
            "nw_t": round(t, 3) if t == t and abs(t) != math_inf_guard() else None,
            "ic_gt_0_ratio": round(float((s > 0).mean()), 3),
            "by_year": years, "small_sample": len(s) < 30}


def math_inf_guard() -> float:
    return float("inf")


def load_bars_complete(lake: Path, min_symbols: int = 700) -> "object":
    """读湖内 daily_bars,只保留成分数 ≥ min_symbols 的完整天(部分回填月份防伪 IC)。"""
    import pandas as pd  # noqa: PLC0415

    files = sorted(Path(lake).glob("curated/daily_bars/trade_date=*/*.parquet"))
    if not files:
        raise FileNotFoundError(f"湖内无 daily_bars: {lake}")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    counts = df.groupby("trade_date")["symbol"].nunique()
    keep = set(counts[counts >= min_symbols].index)
    df = df[df["trade_date"].isin(keep)]
    return df.reset_index(drop=True)
