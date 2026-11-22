# -*- coding: utf-8 -*-
"""hmm_regime_experiment.py — [S21] 预注册试验(部分执行 ①②,2026-11-23)

[S21] 判定写死(METHODS.md):
  ① 熊态前导:HMM 熊态起点相对三票二 bear 起点的中位前导 ≥ 0 天 → ①满足
  ② 熊态区分力:HMM 熊日 T+20 前向收益差(非重叠采样 t) ≥ 三票二 t − 0.5 容差 → ②满足
  ③ 注入 [S7] 后 OOS IC 提升 ≥10% 或 t≥2 —— **待全量湖定型,本轮不跑**(部分执行声明)
  采纳为增强 = ①∧②∧③;①或②不满足 → 维持三票二;③未跑 → 结论挂起,不判采纳。

公平性控制(预注册): 两分类器同输入(仅指数收盘,无宽度)——三票二 daily_regime(breadth=None),
HMM 特征=[日收益, 20日滚动波动](同一收盘序列派生);HMM 标签过同一 k=5 去抖。
状态语义: hmm_regime 状态按均值升序 → 状态 0=低均值(熊),2=高均值(牛),1=中性。

红线: 只读湖;HMM 固定 seed=0 全程确定;③未跑前本脚本输出不算"采纳"。
产物: results/hmm_regime_experiment.json
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from astock_monitor.config import load_config, resolve_path  # noqa: E402
from astock_monitor.hmm_regime import fit_hmm, regime_proba  # noqa: E402
from astock_monitor.regime import BEAR, BULL, daily_regime, debounce  # noqa: E402
from astock_monitor.signals import load_index_closes  # noqa: E402

OUT = REPO_ROOT / "results" / "hmm_regime_experiment.json"
H = 20          # 前向窗口,与 [S12]/[S18] 同口径
TOL = 0.5       # ② 容差(预注册)


def fwd_returns(closes: np.ndarray, h: int = H) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    out[:-h] = closes[h:] / closes[:-h] - 1.0
    return out


def nonoverlap_t(x: np.ndarray, h: int = H) -> float:
    """前向收益重叠虚高修正: 每 h 期取 1 个样本再算 t(同 [S18] 非重叠口径)。"""
    v = x[~np.isnan(x)][::h]
    if len(v) < 3 or v.std(ddof=1) < 1e-12:
        return float("nan")
    return float(v.mean() / (v.std(ddof=1) / len(v) ** 0.5))


def episodes(mask: np.ndarray) -> list[int]:
    """布尔序列 → 每段连续 True 的起点索引。"""
    onsets, prev = [], False
    for i, b in enumerate(mask):
        if b and not prev:
            onsets.append(i)
        prev = bool(b)
    return onsets


def main() -> int:
    cfg = load_config()
    lake = resolve_path(cfg, "paths.cnequity_lake")
    ic = load_index_closes(lake, "000300.SH")
    dates = [d for d, _ in ic]
    closes = np.array([c for _, c in ic])

    # ── 三票二基线(同输入: 无宽度) ──
    reg = daily_regime(ic, breadth250=None)
    r3v2 = np.array([reg[d]["regime"] for d in dates])
    bear3 = r3v2 == BEAR

    # ── HMM(同输入派生: [日收益, vol20]) ──
    rets = np.zeros(len(closes))
    rets[1:] = closes[1:] / closes[:-1] - 1.0
    vol20 = np.array([rets[max(0, i - 19):i + 1].std(ddof=1) for i in range(len(rets))])
    X = np.column_stack([rets, vol20])
    X = X[1:]  # 首日收益无效,对齐 drops
    m = fit_hmm(X, n_states=3, seed=0)
    P = regime_proba(m, X)
    raw_states = P.argmax(1)
    deb = debounce([int(s) for s in raw_states], k=5)  # 与三票二同 k=5 去抖
    hmm_bear = np.array([s == 0 for s in deb])          # 状态0=低均值=熊
    hmm_bull = np.array([s == 2 for s in deb])

    # ── ② 区分力(非重叠 T+20) ──
    fr = fwd_returns(closes)[1:]  # 对齐 X
    all_t = nonoverlap_t(fr)
    bear3_t = nonoverlap_t(np.where(bear3[1:], fr, np.nan))
    hmm_bear_t = nonoverlap_t(np.where(hmm_bear, fr, np.nan))
    hmm_bull_t = nonoverlap_t(np.where(hmm_bull, fr, np.nan))

    # ── ① 前导性: 三票二 bear 起点 × HMM 更早起点 ──
    onsets3 = episodes(bear3[1:])
    onsets_hmm = episodes(hmm_bear)
    date_idx = {d: i for i, d in enumerate(dates[1:])}
    leads = []
    for o3 in onsets3:
        d3 = dates[1:][o3]
        cands = [oh for oh in onsets_hmm
                 if 0 <= o3 - oh <= 60]  # 60 交易日内更早的 HMM 起点
        if cands:
            leads.append(o3 - max(cands))  # >0 = HMM 更早
    med_lead = float(np.median(leads)) if leads else None

    ok1 = med_lead is not None and med_lead >= 0
    ok2 = (not np.isnan(hmm_bear_t)) and (not np.isnan(bear3_t)) \
        and hmm_bear_t >= bear3_t - TOL
    rep = {
        "experiment": "[S21] 部分执行(①②;③待全量湖定型)",
        "window": {"dates": [str(dates[1]), str(dates[-1])], "n": int(len(X))},
        "hmm": {"n_states": 3, "seed": 0, "loglik_final": round(m["loglik_final"], 1),
                "converged": m["converged"],
                "state_means": m["mean"].ravel().round(5).tolist()},
        "counts": {"bear3_days": int(bear3[1:].sum()), "hmm_bear_days": int(hmm_bear.sum()),
                   "bear3_episodes": len(onsets3), "hmm_bear_episodes": len(onsets_hmm)},
        "discrimination_T20_nonoverlap": {
            "all_t": round(all_t, 3),
            "bear_3v2_t": round(bear3_t, 3),
            "hmm_bear_t": round(hmm_bear_t, 3),
            "hmm_bull_t": round(hmm_bull_t, 3)},
        "lead_1": {"median_lead_days": med_lead, "n_matched_onsets": len(leads),
                   "interpretation": ">0=HMM 熊态更早,0=同时,<0=HMM 滞后"},
        "criteria": {"c1_lead_ge0": ok1, "c2_discrimination_within_tol": ok2,
                     "c3_inject_ic": "deferred(全量湖定型后)"},
        "fairness": "两分类器同输入(仅指数收盘);HMM 同 k=5 去抖;状态语义按均值升序",
        "note": "③未跑 → 结论挂起,不判采纳(预注册纪律)",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("counts", "discrimination_T20_nonoverlap",
                                          "lead_1", "criteria")}, ensure_ascii=False, indent=1))
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
