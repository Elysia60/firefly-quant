"""metamdl.py 单测:YZ 波动 / triple-barrier 黄金路径 / IRLS 逻辑回归 / purged 折无泄漏。"""

import math
import unittest
from datetime import date, timedelta

from astock_monitor import metamdl as M


class YangZhangTest(unittest.TestCase):
    def test_constant_prices_near_zero(self):
        bars = [(100.0, 100.0, 100.0, 100.0)] * 40
        v = M.yang_zhang_vol(bars, window=21)
        self.assertLess(v[-1], 1e-9)

    def test_volatile_series_positive(self):
        bars = []
        c = 100.0
        for i in range(40):
            o = c
            c = c * (1 + (0.02 if i % 2 == 0 else -0.019))
            h, l = max(o, c) * 1.01, min(o, c) * 0.99
            bars.append((o, h, l, c))
        v = M.yang_zhang_vol(bars, window=21)
        self.assertGreater(v[-1], 0.005)

    def test_insufficient_window_none(self):
        v = M.yang_zhang_vol([(100.0, 101.0, 99.0, 100.0)] * 10, window=21)
        self.assertTrue(all(x is None for x in v))


class TripleBarrierTest(unittest.TestCase):
    def test_down_touched_first_is_one(self):
        # entry=100, σ=0.01 → 下挡 99, 上挡 101;第 2 日 low=98.5 触下挡
        o_dir = [(100.8, 99.5, 100.0), (100.2, 98.5, 99.0), (99.0, 98.0, 98.2)]
        self.assertEqual(M.triple_barrier_label(100.0, o_dir, 0.01), 1)

    def test_up_touched_first_is_zero(self):
        o_dir = [(100.8, 99.5, 100.5), (101.3, 100.1, 101.0)]
        self.assertEqual(M.triple_barrier_label(100.0, o_dir, 0.01), 0)

    def test_same_day_both_touch_conservative_zero(self):
        # 同日 H≥上挡 且 L≤下挡 → 保守 0
        o_dir = [(101.5, 98.5, 100.0)]
        self.assertEqual(M.triple_barrier_label(100.0, o_dir, 0.01), 0)

    def test_expiry_uses_direction(self):
        o_dir = [(100.5, 99.6, 100.2), (100.4, 99.5, 100.1), (100.3, 99.4, 99.8),
                 (100.2, 99.3, 99.6), (100.1, 99.2, 99.4)]  # 5 日均未触挡,末收 99.4<100
        self.assertEqual(M.triple_barrier_label(100.0, o_dir, 0.01), 1)  # 空方赌注到期方向=跌

    def test_bad_sigma_none(self):
        self.assertIsNone(M.triple_barrier_label(100.0, [(99.0, 98.0, 98.5)], 0.0))


class IRLSTest(unittest.TestCase):
    def test_separable_data_learns_sign(self):
        rng_x = [(-3.0 + i * 0.1) for i in range(60)]
        X = [[1.0, x] for x in rng_x]
        y = [1 if x > 0 else 0 for x in rng_x]
        beta = M.irls_logistic(X, y, l2=0.1)
        p = M.predict_prob(X, beta)
        # 单调:正 x 概率高于负 x
        self.assertGreater(p[-1], p[0])
        self.assertGreater(p[-1], 0.9)
        self.assertLess(p[0], 0.1)
        self.assertGreater(beta[1], 0)

    def test_predictions_bounded(self):
        X = [[1.0, i * 0.1] for i in range(50)]
        y = [i % 2 for i in range(50)]
        beta = M.irls_logistic(X, y, l2=1.0)
        for pi in M.predict_prob(X, beta):
            self.assertTrue(0.0 <= pi <= 1.0)
            self.assertTrue(math.isfinite(pi))


class PurgedFoldsTest(unittest.TestCase):
    def test_no_train_within_purge_window(self):
        days = [date(2020, 1, 1) + timedelta(days=i) for i in range(200)]
        folds = M.purged_folds(days, k=5, purge_days=10)
        seen_test = []
        for train_idx, test_idx in folds:
            test_days = {days[i] for i in test_idx}
            for i in train_idx:
                for td in test_days:
                    self.assertGreaterEqual(abs((days[i] - td).days), 11)
            seen_test += test_idx
        self.assertEqual(sorted(seen_test), list(range(200)))  # 每事件恰好测试一次

    def test_k_folds_cover_all(self):
        days = [date(2021, 1, 1) + timedelta(days=i) for i in range(120)]
        folds = M.purged_folds(days, k=5, purge_days=10)
        self.assertEqual(len(folds), 5)
        total = sum(len(t) for _, t in folds)
        self.assertEqual(total, 120)


class MetaEventTest(unittest.TestCase):
    def test_neutral_imputation(self):
        ev = M.MetaEvent(day=date(2026, 1, 1), label=1,
                         features={"trend": 70.0, "momentum": None})
        x = ev.x(("trend", "momentum", "sentiment"))
        self.assertEqual(x, [1.0, 70.0, 50.0, 50.0])  # 截距 + 缺失中性填充


if __name__ == "__main__":
    unittest.main()
