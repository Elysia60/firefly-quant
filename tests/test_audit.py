"""audit.py 单测:NW HAC t / stationary bootstrap / 事件研究置换检验。纯标准库,零联网。"""

import math
import random
import unittest
from datetime import date, timedelta

from astock_monitor import audit as A


class NeweyWestTest(unittest.TestCase):
    def test_iid_noise_t_near_zero(self):
        rng = random.Random(7)
        series = [rng.gauss(0, 1) for _ in range(500)]
        self.assertLess(abs(A.newey_west_t(series)), 2.5)

    def test_trend_gives_large_t(self):
        series = [0.001 * i for i in range(300)]
        self.assertGreater(A.newey_west_t(series), 10)

    def test_ma_structure_naive_overstates_nw_honest(self):
        """重叠样本的核心陷阱:MA(4) 结构 + 微小正均值,朴素 t 虚高,NW(L=4) 诚实。"""
        rng = random.Random(11)
        shocks = [rng.gauss(0, 1) for _ in range(600)]
        # y_t = 0.05 + MA(4):每 5 天才有一个独立观测
        series = [0.05 + sum(shocks[max(0, i - 4):i + 1]) / 5 for i in range(600)]
        naive_t = sum(series) / len(series) / (math.sqrt(sum(
            (x - sum(series) / len(series)) ** 2 for x in series) / len(series)) / math.sqrt(len(series)))
        nw = A.newey_west_t(series, window=5)
        self.assertGreater(naive_t, 3.0)          # 朴素口径:虚假显著
        self.assertLess(abs(nw), naive_t)          # NW 修正后收缩

    def test_degenerate_constant_series(self):
        self.assertTrue(math.isinf(A.newey_west_t([5.0] * 100)))


class BootstrapTest(unittest.TestCase):
    def test_indices_in_range_and_length(self):
        rng = random.Random(3)
        idx = A.stationary_bootstrap_indices(100, 20, rng)
        self.assertEqual(len(idx), 100)
        self.assertTrue(all(0 <= i < 100 for i in idx))

    def test_block_size_effects(self):
        """块长越大越连续:b=T 时相邻索引基本连续;b=1 时几乎全独立。"""
        rng = random.Random(5)
        contiguous = A.stationary_bootstrap_indices(200, 200, rng)
        cont_ratio = sum(1 for a, b in zip(contiguous, contiguous[1:]) if b == (a + 1) % 200) / 199
        indep = A.stationary_bootstrap_indices(200, 1, rng)
        indep_ratio = sum(1 for a, b in zip(indep, indep[1:]) if b == (a + 1) % 200) / 199
        self.assertGreater(cont_ratio, 0.9)
        self.assertLess(indep_ratio, 0.1)

    def test_ci_covers_mean_for_stable_series(self):
        rng = random.Random(9)
        series = [rng.gauss(0.5, 0.1) for _ in range(300)]
        lo, hi = A.bootstrap_mean_ci(series, avg_block=25, B=500, seed=9)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_constant_series_degenerate_ci(self):
        lo, hi = A.bootstrap_mean_ci([2.0] * 100, avg_block=10, B=200, seed=1)
        self.assertEqual((lo, hi), (2.0, 2.0))


class EventStudyTest(unittest.TestCase):
    def _days(self, n=260, start=date(2025, 1, 6)):
        return [start + timedelta(days=i) for i in range(n)
                if (start + timedelta(days=i)).weekday() < 5]

    def test_true_effect_detected(self):
        days = self._days()
        fwd = {d: 0.0 for d in days}
        signals = set(days[10:40])           # 信号组真效应 +5%
        for d in signals:
            fwd[d] = 0.05
        r = A.event_study(signals, fwd, days, B=500, seed=13)
        self.assertGreater(r["d_obs"], 0.03)
        self.assertLess(r["p_high"], 0.05)

    def test_no_effect_not_significant(self):
        days = self._days()
        fwd = {d: 0.0 for d in days}         # 信号组与市场无差
        signals = set(days[10:40])
        r = A.event_study(signals, fwd, days, B=500, seed=13)
        self.assertGreater(r["p_high"], 0.05) and self.assertLess(r["p_low"], 0.95)

    def test_min_gap_excludes_contamination(self):
        days = self._days()
        fwd = {d: 0.0 for d in days}
        signals = {days[50], days[51], days[52]}
        r = A.event_study(signals, fwd, days, B=200, seed=3)
        # 对照按星期分层 K:1 匹配:3 个信号日 × K=5 → 15 个对照日
        self.assertEqual(r["control_n"], 15)
        self.assertEqual(r["skipped_missing_forward"], 0)


if __name__ == "__main__":
    unittest.main()
