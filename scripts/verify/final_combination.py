#!/usr/bin/env python3
"""[终版] LightGBM walk-forward + regime 门控 + 组合回测——五天工作的终极实验。

三个已验证组件合体:
  ① LightGBM 13+3 因子模型 (IC +0.056, t=2.12) → 横截面选股
  ② regime 三票二门控 (12 年 5 次 bear 全真实) → 总仓位控制
  ③ 成本模型 (单边 0.05% = 往返 0.1%/2) → 鞭打成本计算

四种策略 (非重叠 T+20 调仓制,每 20 交易日再平衡):
  A 等权宇宙买入持有(基准)
  B regime 门控: bear→空仓, 其余持有宇宙
  C B + LightGBM TopK: regime 允许时持有预测最高前 20%
  D C + 崩溃叠加: bear 或 vol_pct>0.9 或 ROC20 宽度<自身 250 日 20 分位(不含当日)→空仓
    (avoid 信号代理口径: 面板无历史 avoid 序列, 用触发面板 T-波动/T-宽度同构规则替代;
     vol_pct 口径 = R.realized_vol_percentile, 分位池不含当日, 防泄漏已验证)

设计纪律:
  · 训练结果按年落盘缓存 (data/state/oos_cache/), 中断后免重训
  · 调仓期收益 = 所持股票 label_raw 均值 (T+20 前向收益, 非重叠, 无 MA 结构 → 普通 t)
  · 换手成本: Σ|Δw| × 单边成本; 进出空仓各计一次全仓单边
  · 全部阶段防泄漏: 特征/门控/叠加层只用 ≤T 日数据
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import lightgbm as lgb

from astock_monitor import regime as R
from astock_monitor.audit import newey_west_t
from astock_monitor.config import load_config, resolve_path
from astock_monitor.signals import load_index_closes

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
COST_SIDE = float(cfg["backtest"]["cost_round_trip"]) / 2.0   # 单边成本
H = 20                                                        # 调仓期(交易日)
TOPK_FRAC = 0.20
SEEDS = [7, 42, 2024, 2025, 2026]
PARAMS = {"objective": "regression", "metric": "l2", "learning_rate": 0.05,
          "num_leaves": 31, "max_depth": 5, "min_data_in_leaf": 500,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 1.0, "max_bin": 128, "verbose": -1}

CACHE_DIR = REPO_ROOT / "data" / "state" / "oos_cache"
OUT_JSON = REPO_ROOT / "results" / "final_combination.json"

# ================= 数据 =================
panel = pd.read_parquet(REPO_ROOT / "data" / "state" / "factor_panel.parquet")
FEAT = [c for c in panel.columns if c not in ("symbol", "date", "label_raw", "y")]
panel["date"] = pd.to_datetime(panel["date"])
panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
print(f"面板: {len(panel)} 行, {panel['symbol'].nunique()} 只, "
      f"{panel['date'].min().date()} -> {panel['date'].max().date()}, {len(FEAT)} 特征")

idx_rows = load_index_closes(lake, "000300.SH")
regime_map = R.daily_regime(idx_rows)
regime_by_date = {d: (regime_map.get(d) or {}).get("regime", R.NEUTRAL) for d, _ in idx_rows}

# ================= 阶段 1: walk-forward 训练(按年缓存) =================
def daily_rank_ic(preds, labels, dates):
    d = pd.DataFrame({"p": preds, "y": labels, "d": dates}).dropna()
    if len(d) < 100:
        return pd.Series(dtype=float)
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


def train_year(test_year: int) -> pd.DataFrame:
    """单年 walk-forward 训练 + OOS 预测, 带缓存。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_f = CACHE_DIR / f"replay_{test_year}.parquet"
    if cache_f.exists():
        out = pd.read_parquet(cache_f)
        print(f"  {test_year}: [缓存] n={len(out)}")
        return out

    train = panel[panel["date"].dt.year < test_year].dropna(subset=FEAT + ["label_raw"])
    test = panel[panel["date"].dt.year == test_year].dropna(subset=FEAT + ["y"])
    if len(train) < 50000 or len(test) < 5000:
        print(f"  {test_year}: 跳过 (train={len(train)}, test={len(test)})")
        return pd.DataFrame(columns=["symbol", "date", "label_raw", "pred"])

    split = int(len(train) * 0.92)
    vtr, va = train.iloc[:split], train.iloc[split:]
    preds_seeds = []
    for seed in SEEDS:
        params = dict(PARAMS)
        params.update({"seed": seed, "bagging_seed": seed,
                       "feature_fraction_seed": seed})
        dtr = lgb.Dataset(vtr[FEAT], vtr["y"])
        dva = lgb.Dataset(va[FEAT], va["y"], reference=dtr)
        b = lgb.train(params, dtr, num_boost_round=400, valid_sets=[dva],
                      feval=ic_feval(va),
                      callbacks=[lgb.early_stopping(30, verbose=False)])
        preds_seeds.append(b.predict(test[FEAT], num_iteration=b.best_iteration or 400))
    pred = np.mean(preds_seeds, axis=0)

    ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values),
                       pd.Series(test["date"].values))
    print(f"  {test_year}: n={len(test)}, OOS IC={ic.mean():+.4f}")

    out = test[["symbol", "date", "label_raw"]].copy()
    out["pred"] = pred
    out.to_parquet(cache_f)
    return out


years = sorted(int(y) for y in panel["date"].dt.year.unique())
print(f"\n== Walk-forward 训练 (测试年: {years[3:]}{', 训练暖机: ' + str(years[:3])}) ==")
oos_frames = []
for test_year in years[3:]:
    oos_frames.append(train_year(test_year))
oos = pd.concat(oos_frames, ignore_index=True)
print(f"OOS 总: {len(oos)} 行, {oos['date'].nunique()} 个交易日, "
      f"{oos['date'].min().date()} -> {oos['date'].max().date()}")

# ================= OOS IC + 十分位 =================
ic = daily_rank_ic(pd.Series(oos["pred"]), pd.Series(oos["label_raw"]),
                   pd.Series(oos["date"]))
nw = newey_west_t(list(ic.values), window=H)
print(f"\nOOS 合并: IC={ic.mean():+.5f}  NW-t={nw:+.3f}  n_days={len(ic)}")

oos["decile"] = oos.groupby("date")["pred"].transform(
    lambda s: pd.qcut(s.rank(method="first"), 10, labels=False) + 1)
decile_mean = oos.groupby("decile")["label_raw"].mean()
print("\n十分位分析 (T+20 前向收益):")
for d in sorted(decile_mean.index):
    print(f"  D{int(d)}: mean={decile_mean[d]:+.5f}")
top_bot = float(decile_mean[10] - decile_mean[1])
print(f"Top-Bottom 价差: {top_bot:+.5f}")

# ================= 阶段 2: 策略回测 =================
print("\n== 策略回测 (非重叠 T+20 调仓) ==")

# --- 崩溃叠加层输入 (防泄漏 + 真数据源) ---
# 2026-11-17 修正: 面板内 vol_pct/regime/greed 是截面 rank 归一化的市场级列
# (每日对全体股票同值 → rank 恒 0.501, 零信息死列), ROC20 是 (0,1] rank —
# 均不能做市场状态叠加。改用真数据源:
# ① 波动: R.realized_vol_percentile(指数收盘, 分位池不含当日——regime.py 保证)
# ② 宽度: 湖 normalized/breadth_history(真实上涨家数占比, 800 成分口径,
#    由 scripts/rebuild_breadth_history.py 从湖 daily_bars 回算, 只用 ≤T 数据)
volp = R.realized_vol_percentile([c for _, c in idx_rows])
vol_by_date = {d: p for d, p in zip((d for d, _ in idx_rows), volp) if p is not None}
bh = pd.read_parquet(REPO_ROOT / "data" / "lake" / "normalized" / "breadth_history" / "part.parquet")
breadth = pd.Series(bh["up_ratio"].values,
                    index=pd.to_datetime(bh["date"])).sort_index()
b_vals = breadth.values
b_pct = np.full(len(b_vals), np.nan)
for i in range(len(b_vals)):
    pool = b_vals[max(0, i - 250):i]
    if len(pool) >= 60:
        b_pct[i] = (pool < b_vals[i]).mean()
breadth_pct = pd.Series(b_pct, index=breadth.index)

dates_all = sorted(oos["date"].unique())
n_dates = len(dates_all)
rebal_idx = list(range(0, n_dates - H, H))
print(f"调仓点: {len(rebal_idx)} 个 (每 {H} 交易日)")

STRATEGIES = {
    "A": ("等权宇宙持有", False, False),
    "B": ("regime 门控宇宙", True, False),
    "C": ("门控+LightGBM Top20%", True, False),
    "D": ("C+崩溃叠加(波动/宽度)", True, True),
}

results = {}
for mode, (name, use_gate, use_overlay) in STRATEGIES.items():
    nav, peak, mdd = 1.0, 1.0, 0.0
    prev_hold = set()
    period_rets, period_costs = [], []
    n_riskoff, n_bear, n_overlay_only = 0, 0, 0
    yearly_nav = {}
    cur_year = None

    for i in rebal_idx:
        t = pd.Timestamp(dates_all[i])
        if cur_year is None:
            cur_year = t.year
        day = oos[oos["date"] == dates_all[i]]
        bear = regime_by_date.get(t.date(), regime_by_date.get(t, R.NEUTRAL)) == R.BEAR

        overlay_fire = False
        if use_overlay and not bear:
            v = vol_by_date.get(t.date())
            bp = breadth_pct.get(t)
            overlay_fire = bool(
                (v is not None and v > 0.9) or
                (bp is not None and not np.isnan(bp) and bp < 0.2))

        riskoff = (use_gate and bear) or (use_overlay and overlay_fire)
        if bear:
            n_bear += 1
        if use_overlay and overlay_fire and not bear:
            n_overlay_only += 1
        if riskoff:
            n_riskoff += 1
            hold = set()
        else:
            dd = day.dropna(subset=["label_raw"])
            if mode == "C" or mode == "D":
                k = max(1, int(len(dd) * TOPK_FRAC))
                hold = set(dd.nlargest(k, "pred")["symbol"])
            else:
                hold = set(dd["symbol"])

        # 期间毛收益 = 所持股票 T+20 前向收益均值
        if hold:
            sub = dd[dd["symbol"].isin(hold)] if mode in ("C", "D") else dd
            gross = float(sub["label_raw"].mean())
        else:
            gross = 0.0

        # 换手成本: Σ|Δw| × 单边
        if prev_hold and hold:
            turnover = (len(prev_hold - hold) / len(prev_hold) +
                        len(hold - prev_hold) / len(hold))
        elif prev_hold and not hold:
            turnover = 1.0   # 全卖
        elif hold and not prev_hold:
            turnover = 1.0   # 全买
        else:
            turnover = 0.0
        cost = COST_SIDE * turnover
        net = gross - cost

        nav *= (1.0 + net)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
        period_rets.append(net)
        period_costs.append(cost)
        prev_hold = hold

        if t.year != cur_year:
            yearly_nav[cur_year] = round(nav, 4)
            cur_year = t.year
    yearly_nav[cur_year] = round(nav, 4)

    pr = np.array(period_rets)
    n = len(pr)
    ann = nav ** (252.0 / (H * n)) - 1.0 if n and nav > 0 else float("nan")
    t_stat = float(pr.mean() / pr.std(ddof=1) * np.sqrt(n)) if n > 2 and pr.std(ddof=1) > 0 else float("nan")
    results[mode] = {
        "name": name,
        "period_rets": [round(float(x), 6) for x in pr],
        "nav": round(nav, 4),
        "ann_ret": round(ann, 4) if n and nav > 0 else None,
        "mdd": round(mdd, 4),
        "t_stat": round(t_stat, 3) if n > 2 else None,
        "n_periods": n,
        "n_bear_periods": n_bear,
        "n_overlay_only_periods": n_overlay_only,
        "avg_turnover": round(float(np.mean([c / COST_SIDE for c in period_costs])), 3) if period_costs else 0,
        "total_cost_drag": round(sum(period_costs), 4),
        "yearly_nav": yearly_nav,
    }

# ---- 汇总输出 ----
print("\n== 策略对比 (T+20 非重叠调仓, 单边成本 %.2f%%) ==" % (COST_SIDE * 100))
print(f"{'策略':<28} {'NAV':>8} {'年化':>8} {'最大回撤':>9} {'t':>7} {'成本拖累':>8}")
for mode, (name, _, _) in STRATEGIES.items():
    r = results[mode]
    ann_s = f"{r['ann_ret']:+.1%}" if r["ann_ret"] is not None else "N/A"
    print(f"{mode} {name:<25} {r['nav']:>8.4f} {ann_s:>8} {r['mdd']:>9.1%} "
          f"{r['t_stat'] if r['t_stat'] is not None else 'N/A':>7} {r['total_cost_drag']:>8.2%}")

print("\n分年 NAV:")
year_keys = sorted({y for r in results.values() for y in r["yearly_nav"]})
print(f"{'年':<6} " + " ".join(f"{m:>12}" for m in STRATEGIES))
for y in year_keys:
    row = " ".join(f"{results[m]['yearly_nav'].get(y, float('nan')):>12.4f}" for m in STRATEGIES)
    print(f"{y:<6} {row}")

# 宽度代理分位描述(诚实标注)
bp_valid = breadth_pct[~np.isnan(breadth_pct)]
print(f"\n[口径标注] ROC20 宽度代理: {len(bp_valid)} 日有效, "
      f"20 分位阈值触发的调仓期 {results['D']['n_overlay_only_periods']} 个 "
      f"(bear 期 {results['D']['n_bear_periods']} 个)")

payload = {
    "meta": {
        "cost_side": COST_SIDE, "horizon": H, "topk_frac": TOPK_FRAC,
        "seeds": SEEDS, "n_features": len(FEAT),
        "oos_span": [str(oos['date'].min().date()), str(oos['date'].max().date())],
        "oos_rows": len(oos), "rebalance": "非重叠 T+20, 期末不足一期的不调仓",
        "overlay_note": "D 的崩溃叠加为 avoid 代理口径: 指数 20 日波动 500 日分位>0.9 "
                        "(regime.realized_vol_percentile, 分位池不含当日) 或 市场宽度 "
                        "(湖 breadth_history 真实上涨占比) 低于自身 250 日 20 分位; "
                        "非触发面板原版 1 日宽度。注: 面板内 vol_pct/regime/greed 为 "
                        "rank 归一化死列(常量 0.501), 不可用于叠加。",
        "oos_ic": {"mean": round(float(ic.mean()), 5), "nw_t": round(float(nw), 3),
                   "n_days": len(ic)},
        "top_bottom_spread": round(top_bot, 5),
    },
    "strategies": results,
    "pair_tests": {},
}
# 配对差检验(同期非重叠收益差, 普通 t——同调仓历, 无重叠结构)
import math as _m
def _pair(m1, m2):
    a = np.array(results[m1]["period_rets"]); b = np.array(results[m2]["period_rets"])
    d = a - b
    n = len(d)
    t = float(d.mean() / d.std(ddof=1) * _m.sqrt(n)) if n > 2 and d.std(ddof=1) > 0 else None
    return {"mean_per_period": round(float(d.mean()), 6), "t": round(t, 3) if t else None, "n": n}
payload["pair_tests"] = {
    "B_minus_A": _pair("B", "A"),
    "C_minus_A": _pair("C", "A"),
    "D_minus_C": _pair("D", "C"),
}
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("pair_tests:", json.dumps(payload["pair_tests"], ensure_ascii=False))
print("saved(更新)", OUT_JSON)
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", OUT_JSON)
