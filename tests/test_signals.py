"""signals.py 黄金测试:SMA/RSI 已知答案 / 三分项公式 / 缺数据再归一 / 防泄漏(决策只用截至昨日)。"""

import unittest
from datetime import date, timedelta

from astock_monitor import signals as S


def _seq_days(n: int, start: date = date(2026, 1, 5)) -> list[date]:
    """连续 n 个自然日(测试用,不模拟交易日)。"""
    return [start + timedelta(days=i) for i in range(n)]


class IndicatorGoldenTest(unittest.TestCase):
    def test_sma_known_answer(self):
        vals = [float(i + 1) for i in range(20)]  # 1..20 → SMA20 = 10.5
        self.assertEqual(S.sma(vals, 20), 10.5)
        self.assertIsNone(S.sma(vals[:10], 20))  # 样本不足 → None,不造数

    def test_sma_rolling_matches_naive(self):
        vals = [10.0 + (i * 37 % 23) * 0.1 for i in range(500)]
        fast = S.sma(vals, 20)
        slow = sum(vals[-20:]) / 20
        self.assertAlmostEqual(fast, slow, places=9)

    def test_rsi_extremes(self):
        up = [float(i) for i in range(16)]          # 全涨 → 100
        down = [16.0 - i for i in range(16)]        # 全跌 → 0
        flat = [10.0] * 16                          # 恒定 → 50(无方向)
        self.assertEqual(S.rsi(up, 14), 100.0)
        self.assertEqual(S.rsi(down, 14), 0.0)
        self.assertEqual(S.rsi(flat, 14), 50.0)

    def test_rsi_wilder_small_n_golden(self):
        # n=3 手算:closes=[10,11,10,11] → 首窗 g=2/3,l=1/3;
        # 第4点 chg=0 → g=4/9,l=2/9 → rs=2 → RSI=100−100/3=66.6667
        self.assertAlmostEqual(S.rsi([10, 11, 10, 11], n=3), 66.6667, places=3)

    def test_rsi_insufficient(self):
        self.assertIsNone(S.rsi([1.0] * 14, 14))  # 需 15 点

    def test_trend_score_golden(self):
        self.assertEqual(S.trend_score(11.0, 10.0, 50.0), 70.0)   # +20 动量,RSI 中性
        self.assertEqual(S.trend_score(10.0, 10.0, 20.0), 65.0)   # 动量 0,+15 RSI 顶格
        self.assertEqual(S.trend_score(9.0, 10.0, 80.0), 15.0)    # −20 与 −15 双顶格
        self.assertIsNone(S.trend_score(9.0, None, 50.0))         # 缺输入不造分

    def test_sentiment_anchor_interpolation(self):
        self.assertEqual(S.sentiment_score(0), 100.0)
        self.assertEqual(S.sentiment_score(40), 85.0)
        self.assertEqual(S.sentiment_score(50), 70.0)   # 40-60 区间中点
        self.assertEqual(S.sentiment_score(100), 5.0)
        self.assertIsNone(S.sentiment_score(None))

    def test_momentum_golden(self):
        self.assertAlmostEqual(S.momentum_score(0.6, 3), 60.0)
        self.assertIsNone(S.momentum_score(None, 3))    # breadth 缺失不造分

    def test_composite_renormalization(self):
        score, meta = S.composite_score({"trend": 70.0, "momentum": None, "sentiment": None})
        self.assertAlmostEqual(score, 70.0)             # 只剩趋势 → 权重再归一
        self.assertTrue(meta["renormalized"])
        self.assertEqual(meta["missing"], ["momentum", "sentiment"])
        score2, meta2 = S.composite_score({"trend": None, "momentum": None, "sentiment": None})
        self.assertEqual(score2, 50.0)                  # 全缺 → 中性 50,不造假信号
        self.assertFalse(meta2["renormalized"])


class VerdictTest(unittest.TestCase):
    def test_buy_watch_needs_streak3_and_score(self):
        up3 = [100.0, 101.0, 102.0, 103.0]
        self.assertEqual(S.verdict_of(up3, 60.0), "buy_watch")
        self.assertEqual(S.verdict_of(up3, 50.0), "neutral")    # 连涨但分不够 → 不给买入

    def test_avoid_watch_streak2(self):
        down2 = [103.0, 102.0, 101.0]
        self.assertEqual(S.verdict_of(down2, 60.0), "avoid_watch")

    def test_neutral(self):
        self.assertEqual(S.verdict_of([100.0, 101.0, 100.5], 50.0), "neutral")


class SignalLeakProofTest(unittest.TestCase):
    """防泄漏:第 T 日信号只用 < T 的收盘;改动 T 日及以后数据,信号不变。"""

    def setUp(self):
        days = _seq_days(40)
        self.rows = [(d, 100.0 + (i % 5) * 0.5) for i, d in enumerate(days)]
        self.t = days[-1]

    def test_future_data_cannot_change_signal(self):
        base = S.generate_signal(self.rows, self.t)
        tampered = self.rows + [(self.t + timedelta(days=1), 999.0),
                                (self.t + timedelta(days=2), 888.0)]
        after = S.generate_signal(tampered, self.t)
        self.assertEqual(base.composite, after.composite)
        self.assertEqual(base.verdict, after.verdict)
        self.assertEqual(base.trend_score, after.trend_score)

    def test_yesterday_data_matters(self):
        base = S.generate_signal(self.rows, self.t)
        changed = list(self.rows)
        changed[-2] = (changed[-2][0], changed[-2][1] + 5.0)  # 改 T-1(最后一条**历史**;T 本身不入窗)
        after = S.generate_signal(changed, self.t)
        self.assertNotEqual(base.trend_score, after.trend_score)

    def test_gap_banner(self):
        days = _seq_days(60)
        hole = [d for d in days if not (days[20] < d < days[28])]  # 挖掉 days[21..27]
        rows = [(d, 100.0 + (i % 5) * 0.5) for i, d in enumerate(hole)]
        sig = S.generate_signal(rows, days[-1] + timedelta(days=1))
        self.assertEqual(sig.data_quality.gap_days, 8)  # days[20]→days[28] 相邻缺口 = 8 个自然日
        self.assertIn("缺口", sig.data_quality.banner)

    def test_insufficient_history_rejected(self):
        rows = self.rows[:10]
        with self.assertRaises(ValueError):
            S.generate_signal(rows, self.t)


class MomentumLegTest(unittest.TestCase):
    """信号 v2:动量分(宽度)激活;防泄漏——只用 < T 的宽度;缺失 → 再归一。"""

    def setUp(self):
        days = _seq_days(40)
        self.rows = [(d, 100.0 + (i % 5) * 0.5) for i, d in enumerate(days)]
        self.t = days[-1]

    def test_breadth_changes_composite(self):
        base = S.generate_signal(self.rows, self.t)
        bullish = S.generate_signal(self.rows, self.t,
                                    breadth_map={self.t - timedelta(days=1): 0.9})
        bearish = S.generate_signal(self.rows, self.t,
                                    breadth_map={self.t - timedelta(days=1): 0.1})
        self.assertGreater(bullish.composite, base.composite)
        self.assertLess(bearish.composite, base.composite)
        self.assertEqual(bullish.components["missing"], ["sentiment"])  # 只缺情绪
        self.assertTrue(bullish.components["renormalized"])  # 情绪恒缺 → 权重必然再归一
        self.assertIn("momentum", bullish.components)         # 但动量腿已实装参与合成

    def test_breadth_never_uses_same_day(self):
        # 宽度只提供 T 当天值 → 不可用(防泄漏),动量=None 再归一
        sig = S.generate_signal(self.rows, self.t, breadth_map={self.t: 0.9})
        self.assertIsNone(sig.components["momentum"])
        self.assertEqual(sig.data_quality.breadth, "missing")

    def test_renormalized_without_breadth(self):
        sig = S.generate_signal(self.rows, self.t)
        self.assertTrue(sig.components["renormalized"])
        self.assertEqual(sig.components["missing"], ["momentum", "sentiment"])

    def test_sentiment_leg(self):
        # 贪婪度升高 → 情绪分下降(反向锚点) → 综合分下降;防泄漏:只用 < T
        base = S.generate_signal(self.rows, self.t)
        greedy = S.generate_signal(self.rows, self.t,
                                   sentiment_map={self.t - timedelta(days=1): 95.0})
        fearful = S.generate_signal(self.rows, self.t,
                                    sentiment_map={self.t - timedelta(days=1): 5.0})
        self.assertLess(greedy.composite, base.composite)
        self.assertGreater(fearful.composite, base.composite)
        self.assertEqual(greedy.components["missing"], ["momentum"])
        same_day = S.generate_signal(self.rows, self.t, sentiment_map={self.t: 95.0})
        self.assertIsNone(same_day.components["sentiment"])  # T 日情绪不可用

    def test_three_legs_full(self):
        sig = S.generate_signal(self.rows, self.t,
                                breadth_map={self.t - timedelta(days=1): 0.6},
                                sentiment_map={self.t - timedelta(days=1): 50.0})
        self.assertEqual(sig.components["missing"], [])
        self.assertFalse(sig.components["renormalized"])
        self.assertIsNotNone(sig.components["sentiment"])


if __name__ == "__main__":
    unittest.main()
