# -*- coding: utf-8 -*-
"""paper_account.py 单测:纸面账户(熔断净值来源)。

覆盖:初始化/估值/高水位/回撤/持仓回撤/fail-closed(缺价)/幂等(同一天)/
调仓手数与费用/权重与单票上限校验/成本累计。
"""
import tempfile
import unittest
from pathlib import Path

from astock_monitor import paper_account as PA


class InitSaveTest(unittest.TestCase):
    def test_init_default_cash(self):
        acct = PA.init_account()
        self.assertEqual(acct["cash"], 1_000_000.0)
        self.assertEqual(acct["positions"], {})
        self.assertIsNone(acct["high_water"])

    def test_init_rejects_negative_cash(self):
        with self.assertRaises(ValueError):
            PA.init_account(-1)
        self.assertEqual(PA.init_account(0)["cash"], 0.0)  # 满仓(现金 0)合法

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "acct.json"
            PA.save_account(p, PA.init_account(1000, "2026-11-17"))
            got = PA.load_account(p)
            self.assertEqual(got["cash"], 1000)
            self.assertEqual(got["last_day"], "2026-11-17")

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(PA.load_account(Path(td) / "nope.json"))

    def test_load_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{oops", encoding="utf-8")
            self.assertIsNone(PA.load_account(p))


class MarkToMarketTest(unittest.TestCase):
    def test_cash_only_equity(self):
        acct = PA.init_account(1_000_000)
        s = PA.mark_to_market(acct, {}, "2026-11-17")
        self.assertEqual(s["status"], "ok")
        self.assertAlmostEqual(s["equity"], 1_000_000.0)
        self.assertAlmostEqual(s["drawdown"], 0.0)

    def test_high_water_and_drawdown(self):
        acct = PA.init_account(1_000_000)
        PA.mark_to_market(acct, {}, "2026-11-17")
        acct["cash"] = 900_000  # 模拟亏损
        s = PA.mark_to_market(acct, {}, "2026-11-18")
        self.assertAlmostEqual(s["high_water"], 1_000_000.0)
        self.assertAlmostEqual(s["drawdown"], -0.10)

    def test_position_valuation_and_circuit_input(self):
        acct = PA.init_account(0)
        acct["positions"] = {"000001": {"shares": 1000, "cost": 10.0}}
        s = PA.mark_to_market(acct, {"000001": 9.0}, "2026-11-17")
        self.assertAlmostEqual(s["equity"], 9000.0)
        self.assertAlmostEqual(s["positions_detail"]["000001"]["drawdown"], -0.10)
        ci = s["circuit_input"]
        self.assertAlmostEqual(ci["positions"]["000001"]["entry_price"], 10.0)
        self.assertAlmostEqual(ci["positions"]["000001"]["current_price"], 9.0)
        self.assertEqual(ci["portfolio_drawdown"], 0.0)  # 首日即高水位,组合回撤为 0

    def test_missing_price_fail_closed(self):
        acct = PA.init_account(0)
        acct["positions"] = {"000001": {"shares": 1000, "cost": 10.0}}
        s = PA.mark_to_market(acct, {}, "2026-11-17")
        self.assertEqual(s["status"], "data_missing")
        self.assertIn("000001", s["missing"])
        self.assertIsNone(s["equity"])

    def test_duplicate_day_is_idempotent(self):
        acct = PA.init_account(1_000_000)
        PA.mark_to_market(acct, {}, "2026-11-17")
        s2 = PA.mark_to_market(acct, {}, "2026-11-17")
        self.assertEqual(s2["status"], "duplicate")

    def test_equity_history_append(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "eq.jsonl"
            PA.append_equity(p, {"day": "2026-11-17", "equity": 1})
            PA.append_equity(p, {"day": "2026-11-18", "equity": 2})
            import json
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["day"] for r in rows], ["2026-11-17", "2026-11-18"])


class RebalanceTest(unittest.TestCase):
    def _acct(self, cash=1_000_000):
        acct = PA.init_account(cash)
        acct["last_day"] = "2026-11-16"
        return acct

    def test_buy_round_lot(self):
        acct = self._acct()
        trades = PA.rebalance(acct, {"000001": 0.3}, {"000001": 10.0}, "2026-11-17")
        pos = acct["positions"]["000001"]
        self.assertEqual(pos["shares"] % PA.LOT, 0)
        self.assertGreater(pos["shares"], 0)
        self.assertAlmostEqual(acct["cash"] + pos["shares"] * 10.0, 1_000_000.0, delta=5000)
        self.assertTrue(any(t["side"] == "buy" for t in trades))
        self.assertGreater(acct["fees_paid"], 0)

    def test_weight_sum_rejected(self):
        with self.assertRaises(ValueError):
            PA.rebalance(self._acct(), {"A": 0.6, "B": 0.6}, {"A": 10, "B": 10}, "2026-11-17")

    def test_single_cap_rejected(self):
        with self.assertRaises(ValueError):
            PA.rebalance(self._acct(), {"A": 0.4}, {"A": 10}, "2026-11-17")

    def test_missing_price_rejected(self):
        with self.assertRaises(ValueError):
            PA.rebalance(self._acct(), {"A": 0.3}, {}, "2026-11-17")

    def test_sell_reduces_position(self):
        acct = PA.init_account(0)
        acct["positions"] = {"A": {"shares": 10000, "cost": 10.0}}
        acct["cash"] = 0
        PA.rebalance(acct, {"A": 0.1}, {"A": 10.0}, "2026-11-17")
        self.assertLess(acct["positions"]["A"]["shares"], 10000)
        self.assertGreater(acct["cash"], 0)

    def test_empty_targets_noop(self):
        acct = self._acct()
        self.assertEqual(PA.rebalance(acct, {}, {}, "2026-11-17"), [])

    def test_cash_never_negative(self):
        acct = PA.init_account(1000)  # 只能买很少(30% 仓位也买不起一手 → 不动)
        PA.rebalance(acct, {"A": 0.3}, {"A": 1000.0}, "2026-11-17")
        self.assertGreaterEqual(acct["cash"], -1e-6)
        self.assertEqual(acct["positions"], {})


if __name__ == "__main__":
    unittest.main()
