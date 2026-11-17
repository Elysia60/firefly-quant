#!/usr/bin/env python3
"""[S15] 反方① 实验:低换手变体能否救活 TopK alpha(2026-11-18)。

[S15] 已证明: TopK 毛价差真实(+0.576%/20d)但 20 日全调仓制下成本拖累 8.48%/年
吃光一切(C−A t=−0.12)。注册表开放推翻观测: 低换手设计(宽调仓窗/持有带)。

四种变体(全部复用 data/state/oos_cache/ 的 OOS 预测,零重训):
  C40      TopK 40日全调仓      —— 调仓频率减半 → 成本减半
  C-band   持有带(20日检查点)   —— 买入=top20%, 持有期=跌出 top40% 才卖,
           空槽用买入区最优补足  —— 换手=排名自然流动,远低于全重建
  C-band40 持有带+40日检查点    —— 两者叠加
  对照:    A 等权宇宙 / B regime 门控 / C20 TopK 20日全调仓(上轮输家)
全部带 regime 门控(bear→空仓),与 C20 同口径。

会计口径与 final_combination.py 完全一致:
  · 非重叠 T+20 期间收益 = 所持股票 label_raw(T+20 前向收益)均值
  · 换手成本 = Σ|Δw| × 单边(0.05%)
  · 期末链式 NAV,无期内 MTM(mdd 同口径低估,只作横向比较——[S15]-口径注记)

判定标准(预注册,写死在这里,跑完不改):
  · 变体年化 > A 且配对差 t > 2.0 → [S15] 翻案(TopK 可收割)
  · 变体年化 > A 但 t ≤ 2.0 → [S15] 维持,记录"方向存在但不显著"
  · 变体年化 ≤ A → [S15] 加固
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from astock_monitor import regime as R
from astock_monitor.config import load_config, resolve_path
from astock_monitor.signals import load_index_closes

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
COST_SIDE = float(cfg["backtest"]["cost_round_trip"]) / 2.0
H = 20
TOPK_FRAC = 0.20          # 买入区: 预测前 20%
HOLD_FRAC = 0.40          # 持有带: 跌出前 40% 才卖
OUT_JSON = REPO_ROOT / "results" / "turnover_variants.json"

# ---- 数据 ----
panel = pd.read_parquet(REPO_ROOT / "data" / "state" / "factor_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
oos = pd.concat([pd.read_parquet(f) for f in
                 sorted((REPO_ROOT / "data" / "state" / "oos_cache").glob("replay_*.parquet"))],
                ignore_index=True)
oos["date"] = pd.to_datetime(oos["date"])
print(f"OOS 缓存: {len(oos)} 行, {oos['date'].min().date()} -> {oos['date'].max().date()}")

idx_rows = load_index_closes(lake, "000300.SH")
regime_map = R.daily_regime(idx_rows)
regime_by_date = {d: (regime_map.get(d) or {}).get("regime", R.NEUTRAL) for d, _ in idx_rows}

dates_all = sorted(oos["date"].unique())
n_dates = len(dates_all)
rebal_idx = list(range(0, n_dates - H, H))
rebal_step = {"C20": 1, "C40": 2}          # 以 H 为单位: 1=每 20 日, 2=每 40 日


def topk_hold(dd, k):
    return set(dd.nlargest(k, "pred")["symbol"])


def band_hold(dd, prev, k):
    """持有带: 旧仓仍在 top HOLD_FRAC 内的保留;空槽用买入区(TOPK_FRAC)最优补足。"""
    rank = dd["pred"].rank(pct=True, ascending=False)   # 1=最好
    dd = dd.assign(_rank=rank)
    hold_zone = set(dd[dd["_rank"] <= int(len(dd) * HOLD_FRAC)]["symbol"])
    buy_zone = dd[dd["_rank"] <= max(1, int(len(dd) * TOPK_FRAC))]
    keep = prev & hold_zone
    need = k - len(keep)
    fill = set()
    if need > 0:
        cand = buy_zone[~buy_zone["symbol"].isin(keep)]
        fill = set(cand.nlargest(need, "pred")["symbol"])
    return keep | fill


STRATEGIES = {
    "A":  {"name": "等权宇宙持有", "gate": False, "mode": "universe", "step": 1},
    "B":  {"name": "regime 门控宇宙", "gate": True, "mode": "universe", "step": 1},
    "C20": {"name": "TopK 20日全调仓", "gate": True, "mode": "topk", "step": 1},
    "C40": {"name": "TopK 40日全调仓", "gate": True, "mode": "topk", "step": 2},
    "C-band": {"name": "持有带20日", "gate": True, "mode": "band", "step": 1},
    "C-band40": {"name": "持有带40日", "gate": True, "mode": "band", "step": 2},
}

results = {}
oos_by_date = {d: g for d, g in oos.groupby("date")}
for mode, spec in STRATEGIES.items():
    nav, peak, mdd = 1.0, 1.0, 0.0
    prev_hold = set()
    period_rets, turnovers = [], []
    n_riskoff = 0
    for j, i in enumerate(rebal_idx):
        if j % spec["step"] != 0:
            continue                       # 40日模式: 非检查点期间维持旧仓
        t = pd.Timestamp(dates_all[i])
        dd = oos_by_date[dates_all[i]].dropna(subset=["label_raw"])
        bear = regime_by_date.get(t.date(), regime_by_date.get(t, R.NEUTRAL)) == R.BEAR
        if spec["gate"] and bear:
            n_riskoff += 1
            hold = set()
        elif spec["mode"] == "universe":
            hold = set(dd["symbol"])
        elif spec["mode"] == "topk":
            hold = topk_hold(dd, max(1, int(len(dd) * TOPK_FRAC)))
        else:
            hold = band_hold(dd, prev_hold, max(1, int(len(dd) * TOPK_FRAC)))

        if hold:
            sub = dd[dd["symbol"].isin(hold)]
            gross = float(sub["label_raw"].mean())
        else:
            gross = 0.0

        if prev_hold and hold:
            turnover = (len(prev_hold - hold) / len(prev_hold) +
                        len(hold - prev_hold) / len(hold))
        elif prev_hold and not hold:
            turnover = 1.0
        elif hold and not prev_hold:
            turnover = 1.0
        else:
            turnover = 0.0
        cost = COST_SIDE * turnover
        net = gross - cost
        nav *= (1.0 + net)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
        period_rets.append(net)
        turnovers.append(turnover)
        prev_hold = hold

    pr = np.array(period_rets)
    n = len(pr)
    ann = nav ** (252.0 / (H * spec["step"] * n)) - 1.0 if n and nav > 0 else float("nan")
    results[mode] = {
        "name": spec["name"], "rebalance_days": H * spec["step"],
        "nav": round(nav, 4), "ann_ret": round(ann, 4) if n else None,
        "mdd": round(mdd, 4), "n_periods": n, "n_riskoff": n_riskoff,
        "avg_turnover": round(float(np.mean(turnovers)), 3),
        "total_cost_drag": round(sum(t * COST_SIDE for t in turnovers), 4),
        "period_rets": [round(float(x), 6) for x in pr],
    }

# ---- 汇总 ----
print(f"\n== [S15] 反方① 低换手变体 (单边 {COST_SIDE:.2%}, T+20 非重叠) ==")
print(f"{'策略':<22} {'再平衡':>6} {'NAV':>8} {'年化':>8} {'mdd':>8} {'均换手':>7} {'成本拖累':>8}")
for mode, spec in STRATEGIES.items():
    r = results[mode]
    ann_s = f"{r['ann_ret']:+.1%}" if r["ann_ret"] is not None else "N/A"
    print(f"{mode} {spec['name']:<17} {r['rebalance_days']:>4}d {r['nav']:>8.4f} {ann_s:>8} "
          f"{r['mdd']:>8.1%} {r['avg_turnover']:>7.2f} {r['total_cost_drag']:>8.2%}")


def pair(m1, m2):
    a = np.array(results[m1]["period_rets"])
    b = np.array(results[m2]["period_rets"])
    # 40日模式的期收益区间是 40 天——对齐到 20 日口径: 每 40d 期拆两半不可行,
    # 用"每期收益/期长"归一后再比 (日均收益口径)
    a = a / results[m1]["rebalance_days"]
    b = b / results[m2]["rebalance_days"]
    n = min(len(a), len(b))
    d = a[:n] - b[:n]
    t = float(d.mean() / d.std(ddof=1) * np.sqrt(n)) if n > 2 and d.std(ddof=1) > 0 else None
    return {"mean_daily_diff": round(float(d.mean()), 7),
            "ann_diff": round(float(d.mean() * 252), 4),
            "t": round(t, 3) if t else None, "n": n}


pair_tests = {
    "C40_minus_A": pair("C40", "A"),
    "C-band_minus_A": pair("C-band", "A"),
    "C-band40_minus_A": pair("C-band40", "A"),
    "C-band_minus_C20": pair("C-band", "C20"),
}
print("\n配对差检验(日均收益口径):")
for k, v in pair_tests.items():
    print(f"  {k}: ann_diff={v['ann_diff']:+.2%}  t={v['t']}  n={v['n']}")

payload = {
    "meta": {
        "cost_side": COST_SIDE, "horizon": H, "topk_frac": TOPK_FRAC,
        "hold_frac": HOLD_FRAC,
        "purpose": "[S15] 反方①: 低换手变体(宽窗/持有带)能否救活 TopK alpha",
        "decision_rule": "变体年化>A 且 t>2.0 → [S15]翻案; >A 但 t≤2.0 → 维持+方向记录; ≤A → 加固",
        "accounting": "与 final_combination.py 同口径(期末链式,无期内 MTM)",
    },
    "strategies": results,
    "pair_tests": pair_tests,
}
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", OUT_JSON)
