#!/usr/bin/env python3
"""[P5-V2] 因子扩充 9→27 + LightGBM 重训——能否突破 IC 0.058?

新增:
  · 窗口变体: STD5/10/60, RSV5/60, CORR5/60, CNTP5/60, VMA5/60, ROC10/60
  · 市场级: vol_pct(波动分位), margin_greed(两融分位), breadth(宽度), regime(门控状态)
  · 合计 ~27 个特征(vs 旧 9 个)
对比: 同折同种子, 9 因子 vs 27 因子 OOS IC。
"""
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import lightgbm as lgb

from astock_monitor import alpha_lite as AL
from astock_monitor import regime as R
from astock_monitor.audit import newey_west_t
from astock_monitor.config import load_config, resolve_path
from astock_monitor.sentiment import load_margin_greed
from astock_monitor.signals import load_index_closes

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
FOLDS = [("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"),
         ("2026-01-01", "2026-11-12")]
PARAMS = {"objective": "regression", "metric": "l2", "learning_rate": 0.05,
          "num_leaves": 31, "max_depth": 5, "min_data_in_leaf": 500,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 1.0, "max_bin": 128, "verbose": -1}

# ---- 数据 ----
bars_full = AL.load_bars_complete(lake, min_symbols=500)
bars_full["trade_date"] = pd.to_datetime(bars_full["trade_date"])
bars_full = bars_full.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
g = bars_full.groupby("symbol", sort=False)

# ---- 27 因子 ----
f = pd.DataFrame({"symbol": bars_full["symbol"], "date": bars_full["trade_date"]})
f["close"] = bars_full["close"]
f["volume"] = bars_full["volume"]

# K线
f["KMID"] = (bars_full["close"] - bars_full["open"]) / bars_full["open"] if "open" in bars_full.columns else 0.0
f["KSFT"] = ((2 * bars_full["close"] - bars_full["high"] - bars_full["low"]) / bars_full["open"]) if "open" in bars_full.columns else 0.0

ret = g["close"].pct_change()

# 动量
for w in (5, 10, 20, 60):
    f[f"ROC{w}"] = g["close"].shift(w) / bars_full["close"] - 1

# 波动
for w in (5, 10, 20, 60):
    f[f"STD{w}"] = ret.groupby(bars_full["symbol"]).transform(lambda s: s.rolling(w).std())

# 极值
for w in (5, 20, 60):
    mn = g["close"].transform(lambda s: s.rolling(w).min())
    mx = g["close"].transform(lambda s: s.rolling(w).max())
    rng = (mx - mn).where((mx - mn) > 0)
    f[f"RSV{w}"] = (bars_full["close"] - mn) / rng

# 量价
for w in (5, 10, 20):
    f[f"CNTP{w}"] = ret.gt(0).groupby(bars_full["symbol"]).transform(lambda s: s.rolling(w).mean())
    vm = g["volume"].transform(lambda s: s.rolling(w).mean())
    f[f"VMA{w}"] = bars_full["volume"] / vm.where(vm > 0)

for w in (10, 20):
    mc = g["close"].transform(lambda s: s.rolling(w).corr(
        bars_full.loc[s.index, "volume"]) if "volume" in bars_full.columns else np.nan)
    f[f"CORR{w}"] = mc

# 市场级特征(从 index)
from astock_monitor.signals import load_index_closes
idx_rows = load_index_closes(lake, "000300.SH")
idx_closes = dict(idx_rows)
idx_dates = [d for d, _ in idx_rows]
volp = R.realized_vol_percentile([c for _, c in idx_rows])
volp_map = {d: p for d, p in zip(idx_dates, volp) if p is not None}
regime_map = R.daily_regime(idx_rows)
f["vol_pct"] = f["date"].map(volp_map)
f["regime"] = f["date"].map(lambda d: (regime_map.get(d) or {}).get("regime"))
f["regime"] = f["regime"].fillna(1)

# 两融 + 宽度
from astock_monitor.sentiment import load_margin_greed
greed = load_margin_greed(resolve_path(cfg, "paths.lake_raw"))
f["greed"] = f["date"].map(greed)

bh_file = resolve_path(cfg, "paths.lake_norm") / "breadth_history" / "part.parquet"
if bh_file.exists():
    bdf = pd.read_parquet(bh_file)
    bmap = {d: float(v) for d, v in zip(pd.to_datetime(bdf["date"]).dt.date, bdf["up_ratio"])}
    f["breadth"] = f["date"].dt.date.map(bmap)

FEAT9 = ["KMID", "KSFT", "ROC5", "ROC20", "STD20", "RSV20", "CORR20", "CNTP20", "VMA20"]
FEAT27 = [c for c in f.columns if c not in ("symbol", "date", "close", "volume") and c in f.columns]
# 去掉 close/volume 原始列
FEAT27 = [c for c in f.columns if c not in ("symbol", "date", "close", "volume")]

# ---- 标签 ----
cl = bars_full[["symbol", "trade_date", "close"]].rename(columns={"trade_date": "date"})
cl["date"] = pd.to_datetime(cl["date"])
gc = cl.groupby("symbol", sort=False)
cl["label_raw"] = gc["close"].shift(-21) / gc["close"].shift(-1) - 1
f = f.merge(cl[["symbol", "date", "label_raw"]], on=["symbol", "date"], how="left")

# ---- 可交易性过滤 ----
bars_sorted = bars_full.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
gs = bars_sorted.groupby("symbol", sort=False)
bars_sorted["next_ret"] = gs["close"].shift(-1) / bars_sorted["close"] - 1
from astock_monitor import limits as LIM
lim = bars_sorted["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
bars_sorted["untradeable"] = bars_sorted["next_ret"].abs() >= lim
ut = bars_sorted[["symbol", "trade_date", "untradeable"]].rename(columns={"trade_date": "date"})
f = f.merge(ut, on=["symbol", "date"], how="left")
f = f[~f["untradeable"].fillna(False)]
f = f.dropna(subset=["label_raw"])

# ---- 每日截面 rank ----
for c in FEAT27:
    if f[c].isna().all():
        continue
    f[c] = f.groupby("date")[c].rank(pct=True)
f["y"] = f.groupby("date")["label_raw"].rank(pct=True)
df_clean = f.dropna(subset=FEAT27 + ["y"]).reset_index(drop=True)
print(f"建模样本: {len(df_clean)} 行, {len(FEAT27)} 特征")

# ---- 工具 ----
def ic_feval_valid_factory(valid: pd.DataFrame):
    """早停 feval:验证集逐日 Rank IC 均值。"""
    vd = valid["date"].values

    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(valid["y"].values),
                           pd.Series(vd))
        return "rank_ic", float(ic.mean()) if len(ic) else 0.0, True
    return feval
def daily_rank_ic(preds, labels, dates):
    d = pd.DataFrame({"p": preds, "y": labels, "d": dates}).dropna()
    d["rp"] = d.groupby("d")["p"].rank()
    d["ry"] = d.groupby("d")["y"].rank()
    d["xy"] = d["rp"] * d["ry"]
    g2 = d.groupby("d")
    ic = (g2["xy"].mean() - g2["rp"].mean() * g2["ry"].mean()) / (g2["rp"].std() * g2["ry"].std())
    return ic.dropna()

def ic_feval(valid_df):
    vd = valid_df["date"].values
    vy = valid_df["y"].values
    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(vy), pd.Series(vd))
        return "rank_ic", float(ic.mean()) if len(ic) else 0.0, True
    return feval

# ---- 训练 ----
def run_train(feature_cols, tag):
    pooled_ic, pooled_pred, pooled_true, pooled_date = [], [], [], []
    fold_results = []
    for t_start, t_end in FOLDS:
        ts, te = pd.Timestamp(t_start), pd.Timestamp(t_end)
        test_days = sorted(d for d in days if ts <= d <= te)
        if len(test_days) < 60:
            continue
        first_test_idx = {d: i for i, d in enumerate(days)}[test_days[0]]
        train_max = days[max(0, first_test_idx - 25)]
        train = df_clean[df_clean["date"] <= train_max]
        if len(train) < 50000:
            continue
        split = int(len(train) * 0.92)
        vtr, va = train.iloc[:split], train.iloc[split:]
        test = df_clean[df_clean["date"].isin(set(test_days))]
        preds_seeds = []
        for seed in SEEDS:
            params = dict(PARAMS)
            params.update({"seed": seed, "bagging_seed": seed, "feature_fraction_seed": seed})
            dtr = lgb.Dataset(vtr[feature_cols], vtr["y"])
            dva = lgb.Dataset(va[feature_cols], va["y"], reference=dtr)
            fe = ic_feval_valid_factory(va)
            b = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dva],
                          feval=fe, callbacks=[lgb.early_stopping(30, verbose=False)])
            preds_seeds.append(b.predict(test[feature_cols], num_iteration=b.best_iteration or 400))
        pred = np.mean(preds_seeds, axis=0)
        ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values),
                           pd.Series(test["date"].values))
        t_stat = newey_west_t(list(ic.values), window=HORIZON)
        fold_results.append({"fold": t_start, "ic_mean": round(float(ic.mean()), 5),
                             "nw_t": round(t_stat, 3)})
        pooled_ic += list(ic.values)
        pooled_pred += list(pred)
        pooled_true += list(test["y"].values)
        pooled_date += list(test["date"].values)
        print(f"  {tag} 折 {t_start}: IC {ic.mean():+.4f} t={t_stat:+.2f}")
    pt = newey_west_t(pooled_ic, window=HORIZON)
    return {"tag": tag, "n_days": len(pooled_ic),
            "mean_ic": round(float(np.mean(pooled_ic)), 5),
            "nw_t": round(pt, 3), "folds": fold_results}

# ---- 两版对比 ----
days = sorted(df_clean["date"].unique())
print("\n== 9 因子(基线) ==")
r9 = run_train(FEAT9, "9f")
print("\n== 27 因子(扩充) ==")
r27 = run_train(FEAT27, "27f")

out = {"r9": r9, "r27": r27,
       "improvement": round(r27["mean_ic"] - r9["mean_ic"], 5) if r9.get("mean_ic") and r27.get("mean_ic") else None}
out_path = REPO_ROOT / "results" / "lgbm_v2_comparison.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n9因子 IC: {r9['mean_ic']:+.5f} (t={r9['nw_t']:+.3f})")
print(f"27因子 IC: {r27['mean_ic']:+.5f} (t={r27['nw_t']:+.3f})")
print(f"改善: {r27['mean_ic'] - r9['mean_ic']:+.5f}")
print("saved", out_path)
