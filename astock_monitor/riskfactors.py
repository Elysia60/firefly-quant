"""Barra 风格因子(纯价量可算子集,P6 MVP;公式定案 = roadmap P6/侦察报告 2026-11-13)。

四因子(全部逐股滚动、只用 ≤T 数据、O(n) 向量化):
- **Beta**:252 日个股收益对指数收益的滚动协方差/指数方差
- **Momentum RSTR**:252 日对数收益和,**滞后 21 日**(剔最近一月防 A 股反转污染,CNE5 口径)
- **Residual Vol DASTD**:252 日超额收益标准差(简化:未做 Beta/Size 正交化,记分牌标注)
- **Liquidity Amihud**:21 日 mean(|ret|/成交额)×1e9(近似 STOM,截面相关 0.9+)

诚实声明:Liquidity 为近似口径;DASTD 未正交化;历史深度受湖覆盖限制(缺口=NaN,不填充)。
"""

from __future__ import annotations

from pathlib import Path

WINDOW = 252
MOMENTUM_LAG = 21
LIQ_WINDOW = 21


def compute_risk_factors(bars: "object", idx_ret_by_date: dict,
                         window: int = WINDOW, mom_lag: int = MOMENTUM_LAG) -> "object":
    """bars: DataFrame(symbol, trade_date, close, amount);idx_ret_by_date: {date: 指数日收益}。

    返回 DataFrame(symbol, date, beta, rstr, dastd, amihud)。惰性 pandas。
    指数均值/方差**按日期全局计算**(扁平 rolling 会跨股票边界——测试钉死过这个坑)。
    """
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    df = bars.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["_dkey"] = df["trade_date"].dt.date
    df = df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = df.groupby("symbol", sort=False)

    # 指数序列(按日期全局)
    idx_ser = pd.Series(idx_ret_by_date).sort_index()
    mean_m_by_date = idx_ser.rolling(window).mean()
    var_m_by_date = (idx_ser ** 2).rolling(window).mean() - mean_m_by_date ** 2  # 总体口径,与 Cov 一致
    df["ret"] = g["close"].pct_change()
    df["idx_ret"] = df["_dkey"].map(idx_ret_by_date)
    df["mean_m"] = df["_dkey"].map(mean_m_by_date)
    df["var_m"] = df["_dkey"].map(var_m_by_date)
    df["xret"] = df["ret"] - df["idx_ret"]
    df["logr"] = np.log1p(df["ret"])

    # Beta = Cov(ret, idx)/Var(idx),滚动 window
    df["prod"] = df["ret"] * df["idx_ret"]
    mean_prod = g["prod"].transform(lambda s: s.rolling(window).mean())
    mean_i = g["ret"].transform(lambda s: s.rolling(window).mean())
    cov = mean_prod - mean_i * df["mean_m"]
    df["beta"] = cov / df["var_m"].where(df["var_m"] > 0)

    # RSTR:window 日对数收益和,滞后 mom_lag 日
    df["rstr"] = g["logr"].transform(lambda s: s.rolling(window).sum()).groupby(
        df["symbol"]).shift(mom_lag)

    # DASTD:window 日超额收益标准差
    df["dastd"] = g["xret"].transform(lambda s: s.rolling(window).std())

    # Amihud:LIQ_WINDOW 日 mean(|ret|/amount)×1e9
    df["illiq"] = df["ret"].abs() / df["amount"].where(df["amount"] > 0)
    df["amihud"] = g["illiq"].transform(lambda s: s.rolling(LIQ_WINDOW).mean()) * 1e9

    out = df[["symbol", "trade_date", "beta", "rstr", "dastd", "amihud"]].copy()
    out = out.rename(columns={"trade_date": "date"})
    return out
