# -*- coding: utf-8 -*-
"""hmm_regime.py — 最小 Gaussian HMM(2026-11-23 · [S21] 预注册许可路径 · 零依赖 numpy)

[S21] 写死: "hmmlearn 不装 → numpy 手写最小 Gaussian HMM(前向-后向+EM)或试验顺延"。
本文件是许可路径的前半——工具先行,试验窗口等全量湖定型后开。

实现要点(外部侦察核实):
  - 前向-后向用**缩放**(scaling)防下溢(Gundersen 推导),不用 log 空间——
    γ 后验可直接得到,正是 regime 概率特征
  - Baum-Welch EM: E 步(α/β/γ/ξ) + M 步(π/A/μ/σ²,对角协方差——T 小时更稳)
  - 判据: loglik 随迭代单调不降(EM 性质,测试锁定)
  - 状态排序: 按状态均值第一维升序 → 状态 0=低均值(熊/低动量),编号语义稳定(可复现)

红线: 零依赖(纯 numpy);确定性(seed);不碰湖;本模块只是工具,[S21] 判定写死在 METHODS.md。
用法:
  from hmm_regime import fit_hmm, regime_proba
  model = fit_hmm(X, n_states=3, seed=0)          # X: T×k 特征(如 [日收益, 20日滚动波动])
  P = regime_proba(model, X)                       # T×n_states 后验概率(regime 特征矩阵)
  states = P.argmax(1)                             # 逐点最大后验;序列最优解码见 viterbi
"""
from __future__ import annotations

import numpy as np

EPS = 1e-10


def _gauss_logpdf(X: np.ndarray, mean: np.ndarray, var: np.ndarray) -> np.ndarray:
    """对角协方差高斯 logpdf,T×k → T×n_states。"""
    d = X[:, None, :] - mean[None, :, :]
    return -0.5 * (np.log(2 * np.pi * var)[None, :, :] + d * d / var[None, :, :]).sum(-1)


def _forward_scaled(logB: np.ndarray, A: np.ndarray, pi: np.ndarray):
    """缩放前向: 返回 α-hat(T×K)、逐帧 scale(T,)。logB: T×K 观测对数似然。"""
    T, K = logB.shape
    ahat = np.zeros((T, K))
    scale = np.zeros(T)
    ahat[0] = pi * np.exp(logB[0])
    scale[0] = ahat[0].sum() + EPS
    ahat[0] /= scale[0]
    for t in range(1, T):
        ahat[t] = (ahat[t - 1] @ A) * np.exp(logB[t])
        scale[t] = ahat[t].sum() + EPS
        ahat[t] /= scale[t]
    return ahat, scale


def _backward_scaled(logB: np.ndarray, A: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """缩放后向: β-hat(T×K)。"""
    T, K = logB.shape
    bhat = np.zeros((T, K))
    bhat[-1] = 1.0
    for t in range(T - 2, -1, -1):
        bhat[t] = (A @ (np.exp(logB[t + 1]) * bhat[t + 1])) / scale[t + 1]
    return bhat


def _e_step(X, A, pi, mean, var):
    logB = _gauss_logpdf(X, mean, var)
    ahat, scale = _forward_scaled(logB, A, pi)
    bhat = _backward_scaled(logB, A, scale)
    gamma = ahat * bhat
    gamma /= gamma.sum(1, keepdims=True) + EPS
    # ξ: 相邻状态转移后验(T-1, K, K)
    T, K = logB.shape
    xi = np.zeros((T - 1, K, K))
    for t in range(T - 1):
        num = ahat[t][:, None] * A * (np.exp(logB[t + 1]) * bhat[t + 1])[None, :]
        xi[t] = num / (num.sum() + EPS)
    loglik = float(np.log(scale).sum())
    return gamma, xi, loglik


def fit_hmm(X, n_states: int = 3, n_iter: int = 50, seed: int = 0,
            tol: float = 1e-6) -> dict:
    """Baum-Welch EM 拟合。X: T×k。返回模型 dict(loglik 迭代序列含在内)。"""
    X = np.asarray(X, dtype=float)
    T, k = X.shape
    # 初始: 分位数撒状态中心(确定性,好过纯随机)
    q = np.quantile(X[:, 0], np.linspace(0, 1, n_states + 1)[1:-1])
    assign = np.searchsorted(q, X[:, 0])
    mean = np.array([X[assign == s].mean(0) if (assign == s).any() else X.mean(0)
                     for s in range(n_states)])
    var = np.array([np.maximum(X.var(axis=0), EPS) for _ in range(n_states)])
    A = np.full((n_states, n_states), 1.0 / n_states) + np.eye(n_states) * (0.5 / n_states)
    A /= A.sum(1, keepdims=True)  # 行随机化——非随机阵会让首个 loglik 成伪值,破坏 EM 单调性
    pi = np.full(n_states, 1.0 / n_states)
    logliks = []
    for _ in range(n_iter):
        gamma, xi, loglik = _e_step(X, A, pi, mean, var)
        logliks.append(loglik)
        # M 步
        pi = gamma[0] + EPS
        pi /= pi.sum()
        A = xi.sum(0) + EPS
        A /= A.sum(1, keepdims=True)
        Nk = gamma.sum(0) + EPS
        mean = (gamma.T @ X) / Nk[:, None]
        for s in range(n_states):
            d = (X - mean[s]) ** 2
            var[s] = np.maximum((gamma[:, s][:, None] * d).sum(0) / Nk[s], EPS)
        if len(logliks) > 1 and logliks[-1] - logliks[-2] < tol:
            break
    # 状态语义稳定化: 按均值第一维升序重排(状态 0=低均值,编号可复现)
    order = np.argsort(mean[:, 0])
    return {"n_states": n_states, "mean": mean[order], "var": var[order],
            "A": A[np.ix_(order, order)], "pi": pi[order],
            "logliks": logliks, "loglik_final": logliks[-1],
            "converged": len(logliks) < n_iter}


def regime_proba(model: dict, X) -> np.ndarray:
    """平滑后验 γ: T×n_states——regime 概率特征([S21] 注入 [S7] 的形态)。"""
    X = np.asarray(X, dtype=float)
    gamma, _, _ = _e_step(X, model["A"], model["pi"], model["mean"], model["var"])
    return gamma


def viterbi(model: dict, X) -> np.ndarray:
    """序列最优状态路径(Viterbi)。"""
    X = np.asarray(X, dtype=float)
    logB = _gauss_logpdf(X, model["mean"], model["var"])
    A, pi = model["A"], model["pi"]
    T, K = logB.shape
    delta = np.zeros((T, K))
    psi = np.zeros((T, K), dtype=int)
    delta[0] = np.log(pi + EPS) + logB[0]
    for t in range(1, T):
        cand = delta[t - 1][:, None] + np.log(A + EPS)
        psi[t] = cand.argmax(0)
        delta[t] = cand.max(0) + logB[t]
    path = np.zeros(T, dtype=int)
    path[-1] = int(delta[-1].argmax())
    for t in range(T - 2, -1, -1):
        path[t] = psi[t + 1][path[t + 1]]
    return path


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rng = np.random.default_rng(0)
    # 合成两态市场: 前 150 天低波动正漂移,后 150 天高波动负漂移
    X = np.concatenate([rng.normal(0.001, 0.005, (150, 1)),
                        rng.normal(-0.002, 0.02, (150, 1))])
    m = fit_hmm(X, n_states=2, seed=0)
    P = regime_proba(m, X)
    print(f"loglik: {m['logliks'][0]:.1f} → {m['loglik_final']:.1f} (EM 单调)")
    print(f"状态均值: {m['mean'].ravel().round(5)} (低→高排序)")
    # 状态 0=低均值=后半段(-0.002),状态 1=高均值=前半段(+0.001)
    acc = (P.argmax(1) == (np.arange(300) < 150).astype(int)).mean()
    print(f"两段恢复准确率: {acc:.0%}")
