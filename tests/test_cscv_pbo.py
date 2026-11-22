# -*- coding: utf-8 -*-
"""test_cscv_pbo.py — CSCV-PBO 测试(2026-11-23 · 合成矩阵语义 + 边界)

语义校准: 有真实边际的策略 → PBO 低;纯噪声 → PBO≈0.5;
前半程赢后半程输的"过拟合形" → PBO 升高。全部精确枚举,输出确定。
"""
import sys
import unittest

import numpy as np

sys.path.insert(0, r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor")
from astock_monitor.cscv_pbo import cscv_pbo  # noqa: E402

RNG = np.random.default_rng(42)


def noise_matrix(T=320, N=4):
    return RNG.normal(0.0, 0.01, size=(T, N))


class TestSemantics(unittest.TestCase):
    def test_informed_strategy_low_pbo(self):
        """一个策略每期都有稳定正边际 → IS 赢家 OOS 站得住 → PBO 低。"""
        M = noise_matrix()
        M[:, 0] += 0.02  # 真实边际,全程存在
        rep = cscv_pbo(M)
        self.assertLessEqual(rep["pbo"], 0.05)
        self.assertEqual(rep["band"], "稳健")

    def test_pure_noise_pbo_near_half(self):
        """全部同分布噪声 → IS 赢家 OOS 掉中位数以下的概率 ≈ 0.5。

        容差放宽到 (0.15, 0.85): 12870 组合共享块 → 强相关,有效样本远小于
        组合数,PBO 实现值方差大——这是 Bailey 论文承认的特性,不是 bug。
        """
        rep = cscv_pbo(noise_matrix())
        self.assertGreater(rep["pbo"], 0.15)
        self.assertLess(rep["pbo"], 0.85)

    def test_regime_flip_elevates_pbo(self):
        """前半程强赢后半程强输(过拟合形) → PBO 显著升高。"""
        M = noise_matrix()
        M[:, 0] += np.concatenate([np.full(160, 0.03), np.full(160, -0.03)])
        rep = cscv_pbo(M)
        self.assertGreater(rep["pbo"], 0.3)

    def test_two_strategies_symmetric(self):
        """N=2 时相对秩只有 0.5/1.0,λ 对称——有边际者 PBO 低。"""
        M = noise_matrix()
        M[:, 1] += 0.02
        rep = cscv_pbo(M)
        self.assertLessEqual(rep["pbo"], 0.1)


class TestBoundary(unittest.TestCase):
    def test_exact_enumeration_deterministic(self):
        """C(16,8)=12870 全枚举,同输入同输出(无采样)。"""
        M = noise_matrix()
        r1, r2 = cscv_pbo(M), cscv_pbo(M)
        self.assertEqual(r1["n_combos"], 12870)
        self.assertEqual(r1["pbo"], r2["pbo"])

    def test_bad_shape_raises(self):
        with self.assertRaises(ValueError):
            cscv_pbo(np.zeros((10, 1)))       # N<2
        with self.assertRaises(ValueError):
            cscv_pbo(np.zeros((100, 3)), n_blocks=16)  # T 不整除

    def test_small_matrix_works(self):
        rep = cscv_pbo(noise_matrix(T=32, N=3), n_blocks=8)
        self.assertEqual(rep["n_combos"], 70)  # C(8,4)


if __name__ == "__main__":
    unittest.main()
