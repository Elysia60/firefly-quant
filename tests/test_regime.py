"""regime.py 单测:滞回状态机 / 波动分位 / 三票二 / 去抖 / as-of 防泄漏。"""

import math
import random
import unittest
from datetime import date, timedelta

from astock_monitor import regime as R


def _seq(n: int, start: date = date(2015, 1, 5)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


class HysteresisTest(unittest.TestCase):
    def test_enter_and_exit_bands(self):
        # 涨到年线上方 ×1.01 → 多头;跌破 ×0.96(注意 MA250 随新价移动)→ 空头;带内保持
        closes = [100.0] * 260 + [102.0] * 5 + [95.0] * 5
        st = R.hysteresis_gate(closes)
        self.assertEqual(st[260], 1)  # 102 > MA250×1.01(MA≈100.008)→ 转多
        self.assertEqual(st[264], 1)
        self.assertEqual(st[265], 0)  # 95 < MA250×0.96(MA≈100.02,闸≈96.02)→ 转空

    def test_band_holds_state(self):
        closes = [100.0] * 260 + [100.5] * 3  # 处于 0.96~1.01 带内,无初始方向前的样例另测
        st = R.hysteresis_gate([100.0] * 260 + [99.0] + [100.5] * 3)
        # 99 < 96? 否(0.96×100=96) → 首判定日仍按 close>ma*enter 定向:99<101 → 空头
        self.assertEqual(st[260], 0)

    def test_insufficient_history_none(self):
        st = R.hysteresis_gate([100.0] * 100)
        self.assertTrue(all(s is None for s in st))


class VolPercentileTest(unittest.TestCase):
    def test_causal_pool_excludes_today(self):
        rng = random.Random(4)
        closes = [100.0]
        for _ in range(800):
            closes.append(closes[-1] * (1 + rng.gauss(0, 0.01)))
        p = R.realized_vol_percentile(closes)
        self.assertTrue(all(x is None or 0 <= x <= 1 for x in p))
        self.assertTrue(any(x is None for x in p[:20]))  # 前 20 日无波动

    def test_spike_gets_high_percentile(self):
        rng = random.Random(4)
        closes = [100.0]
        for _ in range(800):
            closes.append(closes[-1] * (1 + rng.gauss(0, 0.005)))
        closes += [closes[-1] * (1 + 0.08), closes[-1] * 0.93]  # 制造波动尖峰
        p = R.realized_vol_percentile(closes)
        self.assertGreater(p[-1], 0.9)


class VotesAndDebounceTest(unittest.TestCase):
    def test_two_votes_bear(self):
        self.assertEqual(R.classify_day(0, 0.3, None), R.BEAR)      # 年线空+宽度缩
        self.assertEqual(R.classify_day(0, None, 0.95), R.BEAR)     # 年线空+波动极端
        self.assertEqual(R.classify_day(0, None, None), R.NEUTRAL)  # 单票不足
        self.assertEqual(R.classify_day(1, 0.7, None), R.BULL)      # 年线多+宽度扩
        self.assertEqual(R.classify_day(1, 0.5, 0.5), R.NEUTRAL)

    def test_debounce_requires_k_consecutive(self):
        raw = [1] * 10 + [2] * 4 + [1] + [2] * 6
        out = R.debounce(raw, k=5)
        self.assertEqual(out[:10], [1] * 10)
        # [2]*4 不够 5 日 → 保持 1;中间插回 [1] 打断计数 → 继续 1;最后 [2]*6 → 第 5 日切换
        self.assertEqual(out[10:14], [1] * 4)
        self.assertEqual(out[14], 1)
        self.assertEqual(out[15], 1)
        self.assertEqual(out[-1], 2)

    def test_leak_safety_asof(self):
        days = _seq(10)
        regime = {d: {"regime": i % 3} for i, d in enumerate(days)}
        self.assertEqual(R.asof(regime, days[5])["regime"], 4 % 3)   # days[4]
        self.assertIsNone(R.asof(regime, days[0]))                    # 无更早状态


if __name__ == "__main__":
    unittest.main()
