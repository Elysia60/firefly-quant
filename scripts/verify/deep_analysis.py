#!/usr/bin/env python3
"""通宵深度分析:因子相关性 / 分年 IC 热力图 / LightGBM 特征重要性 / 成本敏感性曲线。"""
import json, math, sys, sqlite3
from datetime import date
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
from astock_monitor.signals import load_index_closes

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
FEAT = ["KMID","KSFT","ROC5","ROC20","STD20","RSV20","CORR20","CNTP20","VMA20"]
H = 20

# ---- 数据 ----
bars = AL.load_bars_complete(lake, min_symbols=500)
bars["trade_date"] = pd.to_datetime(bars["trade_date"])
bars = bars.sort_values(["symbol","trade_date"]).reset_index(drop=True)
print(f"数据: {len(bars)} 行, {bars['symbol'].nunique()} 只")

panel = AL.compute_factor_panel(bars)
closes = bars[["symbol","trade_date","close"]]
panel = AL.forward_label(panel, closes, horizon=H)
df = panel.dropna(subset=FEAT + ["label_raw"]).reset_index(drop=True)
print(f"有效样本: {len(df)} 行")

# ---- 1. 因子相关性矩阵 ----
print("\n== 1. 因子相关性矩阵 ==")
corr = df[FEAT].corr(method="spearman")
print(corr.round(3).to_string())
max_offdiag = 0.0
for i in range(len(FEAT)):
    for j in range(i+1, len(FEAT)):
        v = abs(corr.iloc[i, j])
        if v > max_offdiag:
            max_offdiag = v
print(f"最大非对角相关: {max_offdiag:.3f}")
avg_corr = (corr.sum().sum() - len(FEAT)) / (len(FEAT)**2 - len(FEAT))
print(f"平均非对角相关: {avg_corr:.3f}")

# ---- 2. 分年 IC 热力图 ----
print("\n== 2. 分年因子 IC ==")
df["year"] = df["date"].dt.year
years = [int(y) for y in sorted(df["year"].unique())]
ic_heat = {}
for feat in FEAT:
    ic_heat[feat] = {}
    for y in years:
        sub = df[(df["year"] == y) & df[feat].notna() & df["label_raw"].notna()]
        if len(sub) < 300:
            ic_heat[feat][y] = None
            continue
        ics = []
        for d, g in sub.groupby("date"):
            if len(g) < 100:
                continue
            ic = g[feat].corr(g["label_raw"], method="spearman")
            if ic == ic:
                ics.append(ic)
        if ics:
            ic_heat[feat][y] = round(float(np.mean(ics)), 4)
        else:
            ic_heat[feat][y] = None

# 打印热力图
hdr = f"{'因子':<8}" + "".join(f"{y:>8}" for y in years)
print(hdr)
for feat in FEAT:
    row = f"{feat:<8}"
    for y in years:
        v = ic_heat[feat].get(y)
        if v is None:
            row += f"{'—':>8}"
        else:
            mark = " ↑" if abs(v) > 0.05 else ""
            row += f"{v:+.3f} {mark:>2}" if mark else f"{v:+.3f}  "
    print(row)

# ---- 3. LightGBM 特征重要性 ----
print("\n== 3. LightGBM 特征重要性 ==")
# 构建训练集
from astock_monitor import limits as LIM
bars_sorted = bars.sort_values(["symbol","trade_date"]).reset_index(drop=True)
gs = bars_sorted.groupby("symbol", sort=False)
bars_sorted["next_ret"] = gs["close"].shift(-1) / bars_sorted["close"] - 1
lim = bars_sorted["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
bars_sorted["ut"] = bars_sorted["next_ret"].abs() >= lim
ut = bars_sorted[["symbol","trade_date","ut"]].rename(columns={"trade_date":"date"})
df = df.merge(ut, on=["symbol","date"], how="left")
df = df[~df["ut"].fillna(False)]
df["y"] = df.groupby("date")["label_raw"].rank(pct=True)
df_clean = df.dropna(subset=FEAT + ["y"]).reset_index(drop=True)

day_list = sorted(df_clean["date"].unique())
day_pos = {d: i for i, d in enumerate(day_list)}
FOLDS = [("2024-01-01","2024-12-31"),("2025-01-01","2025-12-31"),("2026-01-01","2026-11-12")]
PARAMS = {"objective":"regression","metric":"l2","learning_rate":0.05,"num_leaves":31,
          "max_depth":5,"min_data_in_leaf":500,"feature_fraction":0.8,"bagging_fraction":0.8,
          "bagging_freq":1,"lambda_l2":1.0,"max_bin":128,"verbose":-1,"seed":42}

importance_accum = {f: 0.0 for f in FEAT}
for t_start, t_end in FOLDS:
    ts, te = pd.Timestamp(t_start), pd.Timestamp(t_end)
    test_days = [d for d in day_list if ts <= d <= te]
    if len(test_days) < 60: continue
    first_test = test_days[0]
    train_max = day_list[max(0, day_pos[first_test] - 25)]
    train = df_clean[df_clean["date"] <= train_max]
    if len(train) < 50000: continue
    dtr = lgb.Dataset(train[FEAT], train["y"])
    b = lgb.train(PARAMS, dtr, num_boost_round=200)
    imp = b.feature_importance(importance_type="gain")
    for f, v in zip(FEAT, imp):
        importance_accum[f] += v

total_imp = sum(importance_accum.values())
if total_imp > 0:
    print(f"{'因子':<10}{'增益占比':>10}")
    for f in sorted(FEAT, key=lambda x: -importance_accum[x]):
        pct = importance_accum[f] / total_imp * 100
        print(f"{f:<10}{pct:>9.1f}%")
else:
    print("  无重要性数据")

# ---- 4. 成本敏感性曲线 ----
print("\n== 4. 成本敏感性曲线(B 门控策略) ==")
from astock_monitor import regime as R
from astock_monitor.signals import load_index_closes as _lic
idx_rows = _lic(lake, "000300.SH")
regime_daily = R.daily_regime(idx_rows, breadth250=None)
days = [d for d, _ in idx_rows]
closes = dict(idx_rows)
start = date(2015, 1, 5)
verdict_conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
verdicts = {date.fromisoformat(ds): v for ds, v in verdict_conn.execute(
    "SELECT signal_date, verdict FROM forecast_log WHERE window_days=5").fetchall()}
verdict_conn.close()
verdict_conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
sig_rows = verdict_conn.execute(
    "SELECT signal_date, verdict FROM forecast_log WHERE window_days=5").fetchall()
verdict_conn.close()
verdicts = {date.fromisoformat(ds): v for ds, v in sig_rows}

def sim(mode, cost_side):
    nav, peak, mdd = 1.0, 1.0, 0.0
    rets, switches = [], 0
    pos_prev = 1.0
    for i, d in enumerate(days):
        if d < start or i == 0: continue
        prev = days[i-1]
        if prev not in closes: continue
        if mode == "A":
            pos = 1.0
        else:
            r = regime_daily.get(d, {}).get("regime", 1)
            pos = 0.0 if r == R.BEAR else 1.0
        if pos != pos_prev:
            switches += 1
            nav *= 1 - cost_side * abs(pos - pos_prev) * 2
        ret = closes[d] / closes[prev] - 1.0
        nav *= 1 + pos * ret
        rets.append(pos * ret)
        pos_prev = pos
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    yrs = len(rets) / 243.0
    ann = nav ** (1/yrs) - 1 if yrs else 0
    return {"ann": round(ann, 4), "mdd": round(mdd, 4), "switches": switches}

start = date(2015, 1, 5)
cost_curve = []
for rt_pct in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00]:
    cost = rt_pct / 100 / 2  # 单边
    a = sim("A", cost)
    b = sim("B", cost)
    edge = a["ann"] - b["ann"]
    cost_curve.append({"rt_pct": rt_pct, "buyhold_ann": a["ann"],
                       "gate_ann": b["ann"], "excess": round(edge, 4),
                       "gate_wins": b["ann"] > a["ann"]})
    print(f"  rt={rt_pct:.2f}%  买入持有 {a['ann']:+.1%}  门控 {b['ann']:+.1%}  超额 {edge:+.2%}  {'门控赢' if b['ann']>a['ann'] else '持有赢'}")

# ---- 保存 ----
out = {
    "corr_matrix": corr.round(4).to_dict(),
    "max_offdiag_corr": round(max_offdiag, 4),
    "avg_offdiag_corr": round(avg_corr, 4),
    "ic_heatmap": ic_heat,
    "feature_importance": {f: round(v/total_imp*100, 2) for f, v in importance_accum.items()} if total_imp > 0 else {},
    "cost_sensitivity": cost_curve,
}
out_p = REPO_ROOT / "results" / "deep_analysis.json"
out_p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nsaved {out_p}")
