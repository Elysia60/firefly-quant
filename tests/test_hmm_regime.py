# -*- coding: utf-8 -*-
"""test_hmm_regime.py — 最小 Gaussian HMM 测试(2026-11-23 · 合成两/三态语义)

EM 性质(loglik 单调) + 两态恢复 + 概率归一 + 确定性 + 状态语义稳定(均值升序)。
"""
import sys
import unittest

import numpy as np

sys.path.insert(0, r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor")
from astock_monitor.hmm_regime import fit_hmm, regime_proba, viterbi  # noqa: E402

RNG = np.random.default_rng(0)


def two_regime_X():
    """前 150 天低波动正漂移,后 150 天高波动负漂移。"""
    return np.concatenate([RNG.normal(0.001, 0.005, (150, 1)),
                           RNG.normal(-0.002, 0.02, (150, 1))])


class TestEMProperties(unittest.TestCase):
    def test_loglik_monotone_nondecreasing(self):
        """EM 的基本性质: 迭代 loglik 不降(数值容差内)。"""
        m = fit_hmm(two_regime_X(), n_states=2, n_iter=15, seed=0)
        drops = np.diff(m["logliks"])
        self.assertTrue((drops >= -1e-6).all(),
                        msg=f"loglik 出现下降: {drops.min():.3e}")

    def test_deterministic(self):
        X = two_regime_X()
        m1, m2 = fit_hmm(X, seed=7), fit_hmm(X, seed=7)
        self.assertAlmostEqual(m1["loglik_final"], m2["loglik_final"], places=8)
        self.assertTrue(np.allclose(m1["mean"], m2["mean"]))


class TestSemantics(unittest.TestCase):
    def test_two_regime_recovery(self):
        """两段合成市场 → 后验 argmax 恢复分段 ≥90%(状态 0=低均值=后半段)。"""
        X = two_regime_X()
        m = fit_hmm(X, n_states=2, seed=0)
        P = regime_proba(m, X)
        truth = (np.arange(300) < 150).astype(int)  # 前半段=高均值=状态 1
        self.assertGreaterEqual((P.argmax(1) == truth).mean(), 0.90)

    def test_state_order_semantics_stable(self):
        """状态按均值第一维升序——状态 0 永远是低均值态(语义可复现)。"""
        m = fit_hmm(two_regime_X(), n_states=2, seed=0)
        self.assertLess(m["mean"][0, 0], m["mean"][1, 0])

    def test_proba_normalized(self):
        P = regime_proba(fit_hmm(two_regime_X(), n_states=3, seed=0), two_regime_X())
        self.assertAlmostEqual(float(P.sum(1).mean()), 1.0, places=8)
        self.assertTrue((P >= 0).all() and (P <= 1).all())

    def test_viterbi_runs_and_aligns(self):
        path = viterbi(fit_hmm(two_regime_X(), n_states=2, seed=0), two_regime_X())
        self.assertEqual(len(path), 300)
        truth = (np.arange(300) < 150)  # 前半段=高均值=状态 1
        self.assertGreaterEqual((path == truth).mean(), 0.85)

    def test_three_states_spread(self):
        """三态合成(低/中/高均值) → 三个状态均值有序分开。"""
        X = np.concatenate([RNG.normal(-0.01, 0.005, (120, 1)),
                            RNG.normal(0.0, 0.005, (120, 1)),
                            RNG.normal(0.01, 0.005, (120, 1))])
        m = fit_hmm(X, n_states=3, seed=0)
        means = m["mean"].ravel()
        self.assertLess(means[0], means[1])
        self.assertLess(means[1], means[2])

    def test_constant_series_no_crash(self):
        """常数序列(var=0)不崩——EPS 兜底。"""
        X = np.full((100, 1), 0.0005)
        m = fit_hmm(X, n_states=2, seed=0)
        P = regime_proba(m, X)
        self.assertAlmostEqual(float(P.sum(1).mean()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
