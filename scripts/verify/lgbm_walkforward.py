#!/usr/bin/env python3
"""[P5] LightGBM walk-forward 训练:逐年重训,产出 OOS 预测分 + TopK 分析。

输入:data/state/factor_panel.parquet(已含 15 特征 + y 截面 rank)
输出:results/lgbm_walkforward.json(OOS IC + TopK 分析)
"""
import json, math, sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
import numpy as np
import pandas as pd
import lightgbm as lgb
from astock_monitor.config import load_config

cfg = load_config()
panel = pd.read_parquet(REPO_ROOT / "data" / "state" / "factor_panel.parquet")
FEAT = [c for c in panel.columns if c not in ("symbol", "date", "label_raw", "y")]
print(f"面板: {len(panel)} 行, {len(FEAT)} 特征, {panel['symbol'].nunique()} 只, {panel['date'].min()}~{panel['date'].max()}")

HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
PARAMS = {"objective": "regression", "metric": "l2", "learning_rate": 0.05,
          "num_leaves": 31, "max_depth": 5, "min_data_in_leaf": 500,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 1.0, "max_bin": 128, "verbose": -1}

def daily_rank_ic(preds, labels, dates):
    d = pd.DataFrame({"p": preds, "y": labels, "d": dates}).dropna()
    if len(d) < 100: return pd.Series(dtype=float)
    d["rp"] = d.groupby("d")["p"].rank()
    d["ry"] = d.groupby("d")["y"].rank()
    d["xy"] = d["rp"] * d["ry"]
    g2 = d.groupby("d")
    return ((g2["xy"].mean() - g2["rp"].mean() * g2["ry"].mean()) /
            (g2["rp"].std() * g2["ry"].std())).dropna()

def ic_feval(valid):
    vd = valid["date"].values
    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(valid["y"].values), pd.Series(vd))
        return "rank_ic", float(ic.mean()) if len(ic) else 0.0, True
    return feval

# ---- Walk-forward ----
years = [int(y) for y in sorted(panel["date"].dt.year.unique())]
oos_all = []
print("\n== Walk-forward 训练 ==")
for test_year in [int(y) for y in years[3:]]:
    train = panel[panel["date"].dt.year < int(test_year)]
    test = panel[panel["date"].dt.year == int(test_year)]
    if len(train) < 100000 or len(test) < 5000:
        continue
    split = int(len(train) * 0.92)
    vtr, va = train.iloc[:split], train.iloc[split:]
    preds_seeds = []
    for seed in SEEDS:
        params = dict(PARAMS)
        params.update({"seed": seed, "bagging_seed": seed, "feature_fraction_seed": seed})
        dtr = lgb.Dataset(vtr[FEAT], vtr["y"])
        dva = lgb.Dataset(va[FEAT], va["y"], reference=dtr)
        b = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dva],
                      feval=ic_feval(va),
                      callbacks=[lgb.early_stopping(30, verbose=False)])
        preds_seeds.append(b.predict(test[FEAT], num_iteration=b.best_iteration or 400))
    pred = np.mean(preds_seeds, axis=0)
    ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values),
                       pd.Series(test["date"].values))
    mean_ic = ic.mean() if len(ic) else 0
    print(f"  {test_year}: n={len(test)}, OOS IC={mean_ic:+.4f}")
    for i, (_, row) in enumerate(test.iterrows()):
        oos_all.append({"date": row["date"], "symbol": row["symbol"],
                        "pred": pred[i], "label_raw": row["label_raw"]})

oos = pd.DataFrame(oos_all)
print(f"\nOOS 总: {len(oos)} 行")

# ---- TopK 分析 ----
oos["decile"] = oos.groupby("date")["pred"].transform(
    lambda s: pd.qcut(s.rank(method="first"), 10, labels=False) + 1)
decile = oos.groupby(["date", "decile"])["label_raw"].mean().reset_index()
tb = decile.pivot(index="date", columns="decile", values="label_raw")

print("\n== TopK 分析 ==")
for k in (10, 5, 1):
    top_col = 11 - k  # decile 10=最高分, 9=次高...
    if top_col in tb.columns:
        top_ret = tb[top_col].dropna()
        print(f"  Top {k*10}%: mean={top_ret.mean():+.4f} "
              f"年化={top_ret.mean()*12.15:+.2%} n={len(top_ret)}")

# 多空价差
if 10 in tb.columns and 1 in tb.columns:
    spread = (tb[10] - tb[1]).dropna()
    print(f"  Top-Bottom 价差: mean={spread.mean():+.4f} "
          f"t={spread.mean()/spread.std()*np.sqrt(len(spread)):.2f}")

# 分年 Top Decile
print("\n分年 Top Decile 收益:")
oos["year"] = pd.to_datetime(oos["date"]).dt.year
for y in sorted(oos["year"].unique()):
    sub = oos[(oos["year"] == y) & (oos["decile"] == 10)]["label_raw"]
    bot = oos[(oos["year"] == y) & (oos["decile"] == 1)]["label_raw"]
    if len(sub) > 0:
        print(f"  {y}: Top10% mean={sub.mean():+.4f} n={len(sub)}"
              + (f" | Bottom10% mean={bot.mean():+.4f}" if len(bot) else ""))

# ---- 保存 ----
result = {
    "n_oos": len(oos),
    "features": FEAT,
    "years": [int(y) for y in years[3:]],
    "topk": {},
    "overall": {},
}
for k in (10, 5, 1):
    col = 11 - k
    if col in tb.columns:
        vals = tb[col].dropna()
        result["topk"][f"top{k*10}"] = {
            "mean_fwd20": round(vals.mean(), 5),
            "ann": round(vals.mean() * 12.15, 4),
            "n": len(vals),
        }
if 10 in tb.columns and 1 in tb.columns:
    sp = (tb[10] - tb[1]).dropna()
    result["topk"]["spread_10_1"] = {
        "mean": round(sp.mean(), 5), "t": round(sp.mean() / sp.std() * np.sqrt(len(sp)), 2),
    }
out_path = REPO_ROOT / "results" / "lgbm_walkforward.json"
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", out_path)
