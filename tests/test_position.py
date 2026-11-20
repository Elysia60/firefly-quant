# -*- coding: utf-8 -*-
"""test_position.py — 三选最小仓位引擎测试（2026-11-21 · P6 预注册项落地）"""
import unittest

from astock_monitor.position import (kelly_half, ladder_cap,  # noqa: E402
                                     suggested_size, vol_scalar)


class TestVolScalar(unittest.TestCase):
    def test_scales_down_for_high_vol(self):
        self.assertEqual(vol_scalar(40.0, 20.0), 0.5)

    def test_caps_at_one_for_low_vol(self):
        self.assertEqual(vol_scalar(10.0, 20.0), 1.0)

    def test_honest_none_on_bad_input(self):
        self.assertIsNone(vol_scalar(None, 20.0))
        self.assertIsNone(vol_scalar(0, 20.0))


class TestKelly(unittest.TestCase):
    def test_positive_edge(self):
        # W=0.7, R=2 → f* = 0.7 - 0.3/2 = 0.55 → half = 0.275 → cap 0.25
        self.assertEqual(kelly_half(0.7, 2.0), 0.25)

    def test_negative_edge_bets_zero(self):
        # W=0.4, R=1.5 → f* = 0.4 - 0.6/1.5 = 0.0 → 0
        self.assertEqual(kelly_half(0.4, 1.5), 0.0)

    def test_honest_none_when_no_judge_data(self):
        self.assertIsNone(kelly_half(None, None))
        self.assertIsNone(kelly_half(0.6, 0))  # payoff<=0 → None


class TestLadder(unittest.TestCase):
    def test_pre_registered_ladder(self):
        self.assertEqual(ladder_cap(0), 1.0)
        self.assertEqual(ladder_cap(1), 0.6)
        self.assertEqual(ladder_cap(2), 0.3)
        self.assertIsNone(ladder_cap(None))


class TestSuggestedSize(unittest.TestCase):
    def test_min_binding_semantics(self):
        """三选最小:约束源 = 最小项。vol=40%→0.5, ladder NEUTRAL→0.6 → vol 约束。"""
        r = suggested_size(40.0, None, None, 1, "normal", False)
        self.assertEqual(r["binding"], "vol")
        self.assertEqual(r["size"], 0.5)

    def test_breaker_overrides_to_zero(self):
        r = suggested_size(20.0, 0.7, 2.0, 0, "halt", False)
        self.assertEqual(r["size"], 0.0)
        self.assertEqual(r["binding"], "breaker")

    def test_bear_ladder_binds(self):
        """BEAR 阶梯 0.3 < vol 缩放 0.71 → ladder 约束。"""
        r = suggested_size(28.0, None, None, 2, "normal", False)
        self.assertEqual(r["binding"], "ladder")
        self.assertEqual(r["size"], 0.3)

    def test_kelly_counts_when_judged(self):
        """有判卷数据时 Kelly 参与 min:W=0.7 R=2 → cap 0.25 → kelly 约束。"""
        r = suggested_size(20.0, 0.7, 2.0, 0, "normal", False)
        self.assertEqual(r["binding"], "kelly")
        self.assertEqual(r["size"], 0.25)

    def test_all_missing_no_fake_number(self):
        r = suggested_size(None, None, None, None, "normal", False)
        self.assertIsNone(r["size"])
        self.assertIn("不造数", r["note"])


if __name__ == "__main__":
    unittest.main()
