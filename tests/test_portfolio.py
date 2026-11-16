# -*- coding: utf-8 -*-
"""portfolio.py 单测:TopK/逆波动率/单票上限/regime 缩放/变动检测。"""
import unittest
from datetime import date

from astock_monitor.portfolio import (
    select_portfolio,
    portfolio_changes,
    portfolio_summary,
)
from astock_monitor import regime as R


def make_predictions(n=100, base_pred=0.5):
    import pandas as pd
    return pd.DataFrame({
        "symbol": [f"S{i:04d}" for i in range(n)],
        "pred": [base_pred + i * 0.001 for i in range(n)],
        "vol_20": [0.02 + (i % 10) * 0.001 for i in range(n)],
    })


class TopKTest(unittest.TestCase):
    def test_topk_selects_highest_pred(self):
        preds = make_predictions(100)
        result = select_portfolio(preds, topk=10)
        self.assertEqual(len(result), 10)
        # 应选预测分最高的(尾部,因为 pred 递增)
        self.assertIn("S0099", result)
        self.assertIn("S0090", result)
        self.assertNotIn("S0000", result)

    def test_single_cap_enforced(self):
        preds = make_predictions(20)
        result = select_portfolio(preds, topk=5, single_cap=0.30)
        for w in result.values():
            self.assertLessEqual(w, 0.30 + 0.01)  # 允许浮点误差

    def test_total_weight_positive(self):
        preds = make_predictions(50)
        result = select_portfolio(preds, topk=20)
        total = sum(result.values())
        self.assertGreater(total, 0.5)
        self.assertLessEqual(total, 1.01)

    def test_empty_predictions(self):
        import pandas as pd
        result = select_portfolio(pd.DataFrame(), topk=10)
        self.assertEqual(result, {})


class RegimeScaleTest(unittest.TestCase):
    def test_bear_reduces_position(self):
        preds = make_predictions(20)
        bull = select_portfolio(preds, regime_state=R.BULL, topk=10)
        bear = select_portfolio(preds, regime_state=R.BEAR, topk=10)
        total_bull = sum(bull.values())
        total_bear = sum(bear.values())
        self.assertGreater(total_bull, total_bear)  # bear 缩仓
        self.assertAlmostEqual(total_bull * 0.3, total_bear, places=2)


class ChangesTest(unittest.TestCase):
    def test_add_remove_adjust(self):
        old = {"A": 0.5, "B": 0.3}
        new = {"B": 0.4, "C": 0.3}
        added, removed, adjusted = portfolio_changes(old, new)
        self.assertIn("C", added)
        self.assertIn("A", removed)
        self.assertIn("B", adjusted)

    def test_small_change_ignored(self):
        old = {"A": 0.5}
        new = {"A": 0.503}  # <0.5% 差异
        added, removed, adjusted = portfolio_changes(old, new)
        self.assertEqual(adjusted, {})


class SummaryTest(unittest.TestCase):
    def test_summary(self):
        pos = {"A": 0.4, "B": 0.3, "C": 0.3}
        s = portfolio_summary(pos)
        self.assertEqual(s["n_stocks"], 3)
        self.assertAlmostEqual(s["total_weight"], 1.0, places=2)
        self.assertIn("A", s["top5"])


if __name__ == "__main__":
    unittest.main()
