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


FACTORS = ("beta", "rstr", "dastd", "amihud")


def _daily_decomposition(day_cs: "object", idx_ret: float,
                         quantiles: int = 5) -> dict | None:
    """单日截面分解(P6 记分牌 %var 两列的核心,纯函数便于测试)。

    day_cs: DataFrame(symbol, ret, beta, rstr, dastd, amihud)(当日截面,NaN 已滤);
    idx_ret: 当日指数收益。
    - %var: r_i = beta_i·r_m + ε_i → var_common/(var_common+var_idio),按 stocks 方差(总体口径);
      beta 全缺失/指数缺 → None(诚实缺列,不造数)。
    - 逐因子收益贡献 V0 = 每因子分位数多空组合日收益(高组均值−低组均值);
      诚实声明: 单变量口径、未正交化、未估纯因子收益——只堵"风格暴露冒充 alpha"的第一层。
    """
    import numpy as np  # noqa: PLC0415

    n = len(day_cs)
    if n < 10:
        return None
    out: dict = {"n_stocks": n}
    beta = day_cs["beta"].to_numpy(dtype=float)
    ret = day_cs["ret"].to_numpy(dtype=float)
    if np.isfinite(beta).sum() >= 10 and idx_ret is not None and np.isfinite(idx_ret):
        common = np.nan_to_num(beta, nan=0.0) * idx_ret
        idio = ret - common
        var_c = float(np.var(common))
        var_i = float(np.var(idio))
        denom = var_c + var_i
        out["pct_var_common"] = round(var_c / denom, 4) if denom > 0 else None
    else:
        out["pct_var_common"] = None
    ls = {}
    for f in FACTORS:
        v = day_cs[f].to_numpy(dtype=float)
        mask = np.isfinite(v)
        if mask.sum() < quantiles * 2:
            ls[f] = None
            continue
        vv, rr = v[mask], ret[mask]
        q = np.quantile(vv, np.linspace(0, 1, quantiles + 1))
        # 最低组与最高组的成员(边界值并入低组,与常见分组一致)
        hi_mask = vv >= q[-2]
        lo_mask = vv <= q[1]
        if hi_mask.sum() and lo_mask.sum():
            ls[f] = round(float(rr[hi_mask].mean() - rr[lo_mask].mean()), 6)
        else:
            ls[f] = None
    out["factor_ls"] = ls
    return out


def factor_attribution(bars: "object", idx_ret_by_date: dict,
                       days: list, quantiles: int = 5,
                       window: int = WINDOW, mom_lag: int = MOMENTUM_LAG) -> dict:
    """对给定信号日集合做因子归因聚合(P6 记分牌两列的湖侧计算)。

    bars: DataFrame(symbol, trade_date, close, amount);days: 想归因的 date 列表
    (通常=forecast_log 里某 verdict 的 judged signal_date);window/mom_lag 透传
    compute_risk_factors(合成短数据测试可调小)。
    返回 {"n_days": 实际归因日数, "pct_var_common": 逐日均值,
          "factor_ls": {factor: 逐日均值}}——日级结果取均值,缺失日不计入并如实报告。
    """
    import pandas as pd  # noqa: PLC0415

    rf = compute_risk_factors(bars, idx_ret_by_date, window=window, mom_lag=mom_lag)
    rf["date"] = pd.to_datetime(rf["date"]).dt.date
    bars2 = bars.copy()
    bars2["trade_date"] = pd.to_datetime(bars2["trade_date"]).dt.date
    bars2 = bars2.sort_values(["symbol", "trade_date"])
    bars2["ret"] = bars2.groupby("symbol")["close"].pct_change()
    merged = bars2[["symbol", "trade_date", "ret"]].merge(
        rf, left_on=["symbol", "trade_date"], right_on=["symbol", "date"], how="inner")

    per_day = {}
    for d in days:
        cs = merged[merged["trade_date"] == d]
        if cs.empty:
            continue
        dec = _daily_decomposition(cs, idx_ret_by_date.get(d), quantiles=quantiles)
        if dec is not None:
            per_day[d] = dec
    if not per_day:
        return {"n_days": 0, "pct_var_common": None, "factor_ls": {f: None for f in FACTORS}}

    pvs = [v["pct_var_common"] for v in per_day.values() if v["pct_var_common"] is not None]
    agg: dict = {"n_days": len(per_day),
                 "pct_var_common": round(sum(pvs) / len(pvs), 4) if pvs else None}
    agg["factor_ls"] = {}
    for f in FACTORS:
        vals = [v["factor_ls"][f] for v in per_day.values() if v["factor_ls"][f] is not None]
        agg["factor_ls"][f] = round(sum(vals) / len(vals), 6) if vals else None
    return agg
