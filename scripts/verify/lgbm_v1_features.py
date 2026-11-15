#!/usr/bin/env python3
"""[P5-V1] 特征体系逐步扩展实验:9→13→18,每种信息来源单独测增量。

四层:
  L0 基线:   9 个价量因子(alpha_lite)
  L1 +Barra: + Beta/RSTR/DASTD/Amihud(股票级风险因子,riskfactors)
  L2 +市场:  + vol_pct/regime/breadth/greed(市场级状态)
  L3 +ERP:   + erp_pct(股债性价比,全市场)
每层做 3 折 expanding walk-forward + 5 种子集成。
"""
import json, math, sys, sqlite3
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
import numpy as np
import pandas as pd
import lightgbm as lgb
from astock_monitor import alpha_lite as AL
from astock_monitor import limits as LIM
from astock_monitor import regime as R
from astock_monitor.audit import newey_west_t
from astock_monitor.config import load_config, resolve_path
from astock_monitor.signals import load_index_closes
from astock_monitor.sentiment import load_margin_greed

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
FOLDS = [("2024-01-01","2024-12-31"),("2025-01-01","2025-12-31"),("2026-01-01","2026-11-12")]
PARAMS = {"objective":"regression","metric":"l2","learning_rate":0.05,"num_leaves":31,
          "max_depth":5,"min_data_in_leaf":500,"feature_fraction":0.8,
          "bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"max_bin":128,"verbose":-1}

# ---- 数据加载 ----
bars = AL.load_bars_complete(lake, min_symbols=500)
bars["trade_date"] = pd.to_datetime(bars["trade_date"])
bars = bars.sort_values(["symbol","trade_date"]).reset_index(drop=True)
g = bars.groupby("symbol", sort=False)
idx_rows = load_index_closes(lake, "000300.SH")
idx_dates = [d for d, _ in idx_rows]
idx_closes = dict(idx_rows)

# ---- 9 基础因子 ----
f = pd.DataFrame({"symbol": bars["symbol"], "date": bars["trade_date"]})
f["KMID"] = (bars["close"] - bars["open"]) / bars["open"]
f["KSFT"] = (2*bars["close"] - bars["high"] - bars["low"]) / bars["open"]
ret = g["close"].pct_change()
for w in (5, 20):
    f[f"ROC{w}"] = g["close"].shift(w) / bars["close"] - 1
f["STD20"] = ret.groupby(bars["symbol"]).transform(lambda s: s.rolling(20).std())
mn20 = g["close"].transform(lambda s: s.rolling(20).min())
mx20 = g["close"].transform(lambda s: s.rolling(20).max())
f["RSV20"] = (bars["close"] - mn20) / (mx20 - mn20).where((mx20-mn20)>0)
f["CNTP20"] = ret.gt(0).groupby(bars["symbol"]).transform(lambda s: s.rolling(20).mean())
vm20 = g["volume"].transform(lambda s: s.rolling(20).mean())
f["VMA20"] = bars["volume"] / vm20.where(vm20>0)
f["CORR20"] = g["close"].transform(lambda s: s.rolling(20).corr(
    bars.loc[s.index, "volume"]))

# ---- Barra 四因子(股票级) ----
idx_ret_map = {}
for i in range(1, len(idx_rows)):
    d, c = idx_rows[i]
    p = idx_rows[i-1][1]
    if p > 0: idx_ret_map[d] = c / p - 1
bars["idx_ret"] = bars["trade_date"].dt.date.map(idx_ret_map)
bars["xret"] = bars["close"].pct_change() - bars["idx_ret"]
gb = bars.groupby("symbol", sort=False)
bars["beta_60"] = gb.apply(lambda s: s.assign(
    _p=s["close"].pct_change() * s["idx_ret"],
    _m=s["idx_ret"].pow(2)).assign(
    **{"_cov": lambda x: x["_p"].rolling(60).mean(),
       "_vm": lambda x: x["idx_ret"].rolling(60).mean()}
).assign(_beta=lambda x: (x["_cov"] - x["_cov"].mean() + x["_m"].rolling(60).mean()) /
         x["_m"].rolling(60).var().where(lambda v: v > 0))["_beta"]) if False else np.nan
# 简化 Beta:滚动 60 日相关系数 × 标准差比
bars["ret60_std"] = gb["close"].pct_change().transform(lambda s: s.rolling(60).std())
bars["rstr"] = gb["close"].pct_change().apply(np.log1p).transform(lambda s: s.rolling(126).sum()).groupby(
    bars["symbol"]).shift(21)
bars["dastd"] = gb["xret"].transform(lambda s: s.rolling(60).std())
bars["amihud"] = (bars["close"].pct_change().abs() / bars["amount"].where(bars["amount"]>0)).groupby(
    bars["symbol"]).transform(lambda s: s.rolling(21).mean()) * 1e9
for c in ("rstr","dastd","amihud"):
    f[c] = bars[c].values if len(bars) == len(f) else np.nan
# Beta 用简化的滚动 corr
bars_sorted = bars.sort_values(["symbol","trade_date"])
bars_sorted["beta_60"] = bars_sorted.groupby("symbol")["close"].pct_change().transform(
    lambda s: s.rolling(60).corr(bars.loc[s.index, "idx_ret"]) if len(s) >= 60 else np.nan)
f["beta"] = bars_sorted.sort_index()["beta_60"].values if len(bars_sorted) == len(f) else np.nan
f["beta"] = f["beta"].fillna(1.0)

# ---- 市场级特征 ----
volp_list = R.realized_vol_percentile([c for _, c in idx_rows])
volp_map = {d: p for d, p in zip(idx_dates, volp_list) if p is not None}
f["vol_pct"] = f["date"].dt.date.map(volp_map)
regime_map = R.daily_regime(idx_rows)
f["regime"] = f["date"].dt.date.map(lambda d: (regime_map.get(d) or {}).get("regime"))
greed = load_margin_greed(resolve_path(cfg, "paths.lake_raw"))
f["greed"] = f["date"].dt.date.map(greed)
erp = pd.read_parquet(resolve_path(cfg, "paths.lake_raw") / "akshare" / "erp" / "part.parquet")
erp["date"] = pd.to_datetime(erp["日期"]).dt.date
erp_pct = erp.set_index("date")["股债利差"].rolling(2500).rank(pct=True).shift(1) * 100
f["erp_pct"] = f["date"].dt.date.map(erp_pct)
bhf = resolve_path(cfg, "paths.lake_norm") / "breadth_history" / "part.parquet"
if bhf.exists():
    bdf = pd.read_parquet(bhf)
    bmap2 = {d: float(v) for d, v in zip(pd.to_datetime(bdf["date"]).dt.date, bdf["up_ratio"])}
    f["breadth"] = f["date"].dt.date.map(bmap2)

# ---- 标签 ----
cl = bars[["symbol","trade_date","close"]].rename(columns={"trade_date":"date"})
cl["date"] = pd.to_datetime(cl["date"])
gc = cl.groupby("symbol", sort=False)
cl["label_raw"] = gc["close"].shift(-21) / gc["close"].shift(-1) - 1
f = f.merge(cl[["symbol","date","label_raw"]], on=["symbol","date"], how="left")

# ---- 可交易性 ----
bs = bars.sort_values(["symbol","trade_date"]).reset_index(drop=True)
gs = bs.groupby("symbol", sort=False)
bs["next_ret"] = gs["close"].shift(-1) / bs["close"] - 1
lim = bs["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
bs["ut"] = bs["next_ret"].abs() >= lim
ut = bs[["symbol","trade_date","ut"]].rename(columns={"trade_date":"date"})
f = f.merge(ut, on=["symbol","date"], how="left")
f = f[~f["ut"].fillna(False)]

# ---- 截面 rank ----
BASE9 = ["KMID","KSFT","ROC5","ROC20","STD20","RSV20","CORR20","CNTP20","VMA20"]
BARRA4 = ["rstr","dastd","amihud","beta"]
MKT4 = ["vol_pct","regime","greed","erp_pct"]
BREADTH = ["breadth"]
ALL27 = BASE9 + BARRA4 + MKT4 + BREADTH

for c in ALL27:
    if c in f.columns and f[c].notna().any():
        f[c] = f.groupby("date")[c].rank(pct=True)
f["y"] = f.groupby("date")["label_raw"].rank(pct=True)

# ---- 工具 ----
def daily_rank_ic(preds, labels, dates):
    d = pd.DataFrame({"p":preds, "y":labels, "d":dates}).dropna()
    if len(d) < 100: return pd.Series(dtype=float)
    d["rp"] = d.groupby("d")["p"].rank()
    d["ry"] = d.groupby("d")["y"].rank()
    d["xy"] = d["rp"] * d["ry"]
    g2 = d.groupby("d")
    return ((g2["xy"].mean() - g2["rp"].mean() * g2["ry"].mean()) /
            (g2["rp"].std() * g2["ry"].std())).dropna()

def ic_feval_factory(valid):
    vd = valid["date"].values
    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(valid["y"].values), pd.Series(vd))
        return "rank_ic", float(ic.mean()) if len(ic) else 0.0, True
    return feval

# ---- 分层训练 ----
def run(feat_cols, tag):
    pooled_ic, folds = [], []
    for ts_s, te_s in FOLDS:
        ts, te = pd.Timestamp(ts_s), pd.Timestamp(te_s)
        test_days = sorted(d for d in days if ts <= d <= te)
        if len(test_days) < 60: continue
        first_test = test_days[0]
        pos_map = {d: i for i, d in enumerate(days)}
        train_max = days[max(0, pos_map[first_test] - 25)]
        train = f[f["date"] <= train_max].dropna(subset=feat_cols + ["y"])
        test = f[f["date"].isin(set(test_days))].dropna(subset=feat_cols + ["y"])
        if len(train) < 50000 or len(test) < 5000: continue
        split = int(len(train) * 0.92)
        vtr, va = train.iloc[:split], train.iloc[split:]
        preds_seeds = []
        for seed in SEEDS:
            params = dict(PARAMS); params.update({"seed": seed, "bagging_seed": seed,
                                                   "feature_fraction_seed": seed})
            dtr = lgb.Dataset(vtr[feat_cols], vtr["y"])
            dva = lgb.Dataset(va[feat_cols], va["y"], reference=dtr)
            b = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dva],
                          feval=ic_feval_factory(va),
                          callbacks=[lgb.early_stopping(30, verbose=False)])
            preds_seeds.append(b.predict(test[feat_cols], num_iteration=b.best_iteration or 400))
        pred = np.mean(preds_seeds, axis=0)
        ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values),
                           pd.Series(test["date"].values))
        t_stat = newey_west_t(list(ic.values), window=HORIZON)
        folds.append({"fold": ts_s, "ic": round(float(ic.mean()), 5), "nw_t": round(t_stat, 3)})
        pooled_ic += list(ic.values)
        print(f"  {tag} {ts_s}: IC {ic.mean():+.4f} t={t_stat:+.2f}")
    pt = newey_west_t(pooled_ic, window=HORIZON)
    return {"tag": tag, "n_features": len(feat_cols), "n_days": len(pooled_ic),
            "mean_ic": round(float(np.mean(pooled_ic)), 5), "nw_t": round(pt, 3),
            "folds": folds}

days = sorted(f["date"].unique())
print(f"建模样本: {f.dropna(subset=BASE9+['y']).shape[0]} 行")

# ---- 四层对比 ----
layers = [
    ("L0_基线9因子", BASE9),
    ("L1_加Barra4", BASE9 + BARRA4),
    ("L2_加市场4", BASE9 + BARRA4 + MKT4),
    ("L3_加宽度", BASE9 + BARRA4 + MKT4 + BREADTH),
]
all_results = []
for tag, fc in layers:
    fc_avail = [c for c in fc if c in f.columns]
    print(f"\n== {tag} ({len(fc_avail)} 特征) ==")
    r = run(fc_avail, tag)
    all_results.append(r)

out = {"layers": all_results}
out_p = REPO_ROOT / "results" / "feature_ablation.json"
out_p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n== 特征消融汇总 ==")
for r in all_results:
    print(f"  {r['tag']:<18} IC={r['mean_ic']:+.5f} t={r['nw_t']:+.3f}")
print("saved", out_p)
