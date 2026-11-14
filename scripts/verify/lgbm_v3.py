#!/usr/bin/env python3
"""[P5-V3] 添加真正不同源特征(Barra 四因子):能否改善 OOS IC?

基线: 9 因子 (IC +0.051)
V3:   9 因子 + Beta + RSTR(lag21) + DASTD + Amihud = 13 因子
关键: 这四个是**股票级横截面特征**(不是市场级/窗口变体)——每只股票不同。
"""
import json, math, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import lightgbm as lgb
from astock_monitor import alpha_lite as AL
from astock_monitor import limits as LIM
from astock_monitor.audit import newey_west_t
from astock_monitor.config import load_config, resolve_path
from astock_monitor.riskfactors import compute_risk_factors

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
FOLDS = [("2024-01-01","2024-12-31"),("2025-01-01","2025-12-31"),("2026-01-01","2026-11-12")]
PARAMS = {"objective":"regression","metric":"l2","learning_rate":0.05,"num_leaves":31,
          "max_depth":5,"min_data_in_leaf":500,"feature_fraction":0.8,
          "bagging_fraction":0.8,"bagging_freq":1,"lambda_l2":1.0,"max_bin":128,"verbose":-1}

# ---- 数据 ----
bars_full = AL.load_bars_complete(lake, min_symbols=500)
bars_full["trade_date"] = pd.to_datetime(bars_full["trade_date"])
bars_full = bars_full.sort_values(["symbol","trade_date"]).reset_index(drop=True)
g = bars_full.groupby("symbol", sort=False)

# ---- 9 因子 ----
f = pd.DataFrame({"symbol": bars_full["symbol"], "date": bars_full["trade_date"]})
f["KMID"] = (bars_full["close"] - bars_full["open"]) / bars_full["open"]
f["KSFT"] = (2*bars_full["close"] - bars_full["high"] - bars_full["low"]) / bars_full["open"]
ret = g["close"].pct_change()
for w in (5, 20):
    f[f"ROC{w}"] = g["close"].shift(w) / bars_full["close"] - 1
f["STD20"] = ret.groupby(df_sym := bars_full["symbol"]).transform(lambda s: s.rolling(20).std())
mn20 = g["close"].transform(lambda s: s.rolling(20).min())
mx20 = g["close"].transform(lambda s: s.rolling(20).max())
f["RSV20"] = (bars_full["close"] - mn20) / (mx20 - mn20).where((mx20-mn20)>0)
f["CNTP20"] = ret.gt(0).groupby(bars_full["symbol"]).transform(lambda s: s.rolling(20).mean())
vm20 = g["volume"].transform(lambda s: s.rolling(20).mean())
f["VMA20"] = bars_full["volume"] / vm20.where(vm20>0)
f["CORR20"] = g["close"].transform(lambda s: s.rolling(20).corr(
    bars_full.loc[s.index, "volume"]))
FEAT9 = ["KMID","KSFT","ROC5","ROC20","STD20","RSV20","CORR20","CNTP20","VMA20"]

# ---- Barra 四因子(riskfactors.py) ----
idx_ret = {}
for d in sorted(bars_full["trade_date"].dt.date.unique()):
    sub = bars_full[bars_full["trade_date"].dt.date == d]
    idx_ret[d] = sub["close"].pct_change().mean() if len(sub) > 1 else 0.0
rf = compute_risk_factors(bars_full[["symbol","trade_date","close","amount"]], idx_ret,
                           window=60, mom_lag=21)
f = f.merge(rf[["symbol","date","beta","rstr","dastd","amihud"]],
            on=["symbol","date"], how="left")
FEAT13 = FEAT9 + ["beta","rstr","dastd","amihud"]

# ---- 标签 ----
cl = bars_full[["symbol","trade_date","close"]].rename(columns={"trade_date":"date"})
cl["date"] = pd.to_datetime(cl["date"])
gc = cl.groupby("symbol", sort=False)
cl["label_raw"] = gc["close"].shift(-21) / gc["close"].shift(-1) - 1
f = f.merge(cl[["symbol","date","label_raw"]], on=["symbol","date"], how="left")

# ---- 可交易性过滤 ----
bs = bars_full.sort_values(["symbol","trade_date"]).reset_index(drop=True)
gs = bs.groupby("symbol", sort=False)
bs["next_ret"] = gs["close"].shift(-1) / bs["close"] - 1
lim = bs["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
bs["ut"] = bs["next_ret"].abs() >= lim
ut = bs[["symbol","trade_date","ut"]].rename(columns={"trade_date":"date"})
f = f.merge(ut, on=["symbol","date"], how="left")
f = f[~f["ut"].fillna(False)]

# ---- 截面 rank ----
for c in FEAT13:
    if f[c].isna().all(): continue
    f[c] = f.groupby("date")[c].rank(pct=True)
f["y"] = f.groupby("date")["label_raw"].rank(pct=True)

def daily_rank_ic(preds, labels, dates):
    d = pd.DataFrame({"p":preds, "y":labels, "d":dates}).dropna()
    if len(d) < 100: return pd.Series(dtype=float)
    d["rp"] = d.groupby("d")["p"].rank()
    d["ry"] = d.groupby("d")["y"].rank()
    d["xy"] = d["rp"] * d["ry"]
    g2 = d.groupby("d")
    ic = (g2["xy"].mean() - g2["rp"].mean() * g2["ry"].mean()) / (g2["rp"].std() * g2["ry"].std())
    return ic.dropna()

def ic_feval_factory(valid):
    vd = valid["date"].values
    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(valid["y"].values), pd.Series(vd))
        return "rank_ic", float(ic.mean()) if len(ic) else 0.0, True
    return feval

# ---- 训练对比 ----
def run(feat_cols, tag):
    pooled_ic, folds = [], []
    for ts_s, te_s in FOLDS:
        ts, te = pd.Timestamp(ts_s), pd.Timestamp(te_s)
        test_days = sorted(d for d in f["date"].unique() if ts <= d <= te)
        if len(test_days) < 60: continue
        day_list = sorted(f["date"].unique())
        pos = {d: i for i, d in enumerate(day_list)}
        first_test = test_days[0]
        train_max = day_list[max(0, pos[first_test] - 25)]
        train = f[f["date"] <= train_max].dropna(subset=feat_cols + ["y"])
        test = f[f["date"].isin(set(test_days))].dropna(subset=feat_cols + ["y"])
        if len(train) < 50000 or len(test) < 5000: continue
        split = int(len(train) * 0.92)
        vtr, va = train.iloc[:split], train.iloc[split:]
        preds_seeds = []
        for seed in SEEDS:
            params = dict(PARAMS); params.update({"seed": seed, "bagging_seed": seed, "feature_fraction_seed": seed})
            dtr = lgb.Dataset(vtr[feat_cols], vtr["y"])
            dva = lgb.Dataset(va[feat_cols], va["y"], reference=dtr)
            fe = ic_feval_factory(va)
            b = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dva],
                          feval=fe, callbacks=[lgb.early_stopping(30, verbose=False)])
            preds_seeds.append(b.predict(test[feat_cols], num_iteration=b.best_iteration or 400))
        pred = np.mean(preds_seeds, axis=0)
        ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values), pd.Series(test["date"].values))
        t_stat = newey_west_t(list(ic.values), window=HORIZON)
        fold_res = {"fold": ts_s, "ic": round(float(ic.mean()), 5), "nw_t": round(t_stat, 3), "n": len(ic)}
        folds.append(fold_res)
        pooled_ic += list(ic.values)
        print(f"  {tag} {ts_s}: IC {ic.mean():+.4f} t={t_stat:+.2f}")
    pt = newey_west_t(pooled_ic, window=HORIZON)
    return {"tag": tag, "pooled_ic": round(float(np.mean(pooled_ic)), 5),
            "nw_t": round(pt, 3), "n_days": len(pooled_ic), "folds": folds}

print("== 9 因子基线 ==")
r9 = run(FEAT9, "9f")
print("\n== 13 因子(+Barra 四因子) ==")
r13 = run(FEAT13, "13f")

out = {"r9": r9, "r13": r13, "improvement": round(r13["pooled_ic"] - r9["pooled_ic"], 5)}
out_p = REPO_ROOT / "results" / "lgbm_v3.json"
out_p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n9因子: {r9['pooled_ic']:+.5f} (t={r9['nw_t']:+.3f})")
print(f"13因子: {r13['pooled_ic']:+.5f} (t={r13['nw_t']:+.3f})")
print(f"Barra 增量: {r13['pooled_ic'] - r9['pooled_ic']:+.5f}")
print("saved", out_p)
