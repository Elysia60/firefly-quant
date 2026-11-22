# -*- coding: utf-8 -*-
"""cscv_pbo.py — 回测过拟合概率 PBO(CSCV,2026-11-23 · 零依赖 numpy)

出处: Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting"
(Journal of Computational Finance 2017, ~550 引, SSRN 2326253)——CSCV
(Combinatorially Symmetric Cross-Validation): 把 T 期收益矩阵(T×N 策略/配置)
切 S 个偶数块,枚举全部 C(S, S/2) 种对半组合;每组合内:
  IS  最优策略 n* → OOS 里 n* 的相对秩 ω → logit λ=ln(ω/(1-ω))
λ≤0(IS 赢家 OOS 掉到中位数以下)记一次过拟合 → PBO=过拟合组合占比。

判卷纪律升级: 结论注册表的 DSR 计数从手工记账升级为量化概率——
"这个策略家族的样本内赢家,样本外掉下去的概率有多大"。

预注册判读阈值(写死):
  PBO ≤ 0.2  → 家族稳健(IS 赢家大概率 OOS 站得住)
  0.2 < PBO ≤ 0.5 → 中度,结论需保守读
  PBO > 0.5 → IS 赢家大概率是过拟合——负面结论的可信度反而上升

红线: 零依赖(numpy+itertools 精确枚举,不采样);纯函数可测;不碰湖/不碰交易。
用法:
  python cscv_pbo.py final_combination.json        # 对 A/B/C/D 家族跑 CSCV
  from cscv_pbo import cscv_pbo; cscv_pbo(matrix)  # matrix: T×N (list or ndarray)
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

THRESH_ROBUST = 0.2
THRESH_MODERATE = 0.5


def _perf_sharpe(returns: np.ndarray) -> float:
    """默认判据: 期收益 Sharpe(年化常数不影响排序,省略 ×√k)。"""
    s = returns.std(ddof=1)
    return float(returns.mean() / s) if s > 1e-12 else 0.0


def cscv_pbo(matrix, n_blocks: int = 16, perf_fn=None) -> dict:
    """matrix: T×N(T=期数,N=策略数)。返回 {pbo, logits, n_combos, n_blocks, n_strategies}。"""
    M = np.asarray(matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        raise ValueError(f"需要 T×N 矩阵(N≥2 策略),得到 shape={M.shape}")
    T, N = M.shape
    if T < n_blocks or T % n_blocks != 0:
        raise ValueError(f"T={T} 必须能被 n_blocks={n_blocks} 整除(或 T≥n_blocks)")
    perf = perf_fn or _perf_sharpe
    blocks = np.array_split(np.arange(T), n_blocks)
    half = n_blocks // 2
    logits, n_overfit = [], 0
    for combo in itertools.combinations(range(n_blocks), half):
        train_idx = np.concatenate([blocks[i] for i in combo])
        test_idx = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        is_perf = np.array([perf(M[train_idx, j]) for j in range(N)])
        oos_perf = np.array([perf(M[test_idx, j]) for j in range(N)])
        n_star = int(np.argmax(is_perf))          # IS 赢家
        # OOS 相对秩 ω∈[0,1](1=OOS 仍最优, 0.5=中位数)
        oos_rank = int(np.argsort(np.argsort(oos_perf))[n_star])
        omega = (oos_rank + 1) / N
        lam = float(np.log(omega / (1.0 - omega))) if 0.0 < omega < 1.0 else (
            50.0 if omega >= 1.0 else -50.0)
        logits.append(lam)
        if lam <= 0.0:
            n_overfit += 1
    n_combos = len(logits)
    pbo = n_overfit / n_combos if n_combos else float("nan")
    band = ("稳健" if pbo <= THRESH_ROBUST else
            "中度(结论保守读)" if pbo <= THRESH_MODERATE else
            "IS 赢家大概率过拟合(负面结论可信度上升)")
    return {"pbo": round(pbo, 4), "band": band, "n_combos": n_combos,
            "n_overfit": n_overfit, "n_blocks": n_blocks, "n_strategies": N,
            "T": T, "logit_mean": round(float(np.mean(logits)), 3),
            "method": "CSCV (Bailey-Borwein-Lopez de Prado-Zhu 2017), 精确枚举无采样"}


def run_on_file(path: Path) -> dict:
    """从 final_combination.json 读 A/B/C/D period_rets 矩阵跑 CSCV。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    strats = d["strategies"]
    names = sorted(strats.keys())
    T_raw = min(len(strats[k]["period_rets"]) for k in names)
    T = (T_raw // 16) * 16  # 截到 16 的倍数——取最近 T 期(研究惯例:弃最旧)
    M = np.array([strats[k]["period_rets"][T_raw - T:] for k in names]).T  # T×N
    rep = cscv_pbo(M, n_blocks=16)
    rep["strategies"] = names
    rep["T_trimmed"] = {"from": T_raw, "to": T, "rule": "取最近 16 的倍数期,弃最旧"}
    rep["note"] = "[S15]-[S17] 家族判卷——PBO 是对'家族整体'的过拟合概率,非单策略结论"
    return rep


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    rep = run_on_file(sys.argv[1])
    out = Path(sys.argv[1]).parent / "cscv_pbo_report.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"saved {out}")
