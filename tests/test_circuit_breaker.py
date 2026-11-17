# -*- coding: utf-8 -*-
"""circuit_breaker.py 单测:回撤熔断 P6(利弗莫尔参数机器化)。

覆盖:阈值边界(含精确 -10%/-15%/-25%)/状态机滞回/清仓粘性/人工复位/
fail-closed/跌停挂单/高水位持久化/审计事件/日报渲染。
"""
import json
import tempfile
import unittest
from pathlib import Path

from astock_monitor import circuit_breaker as CB


def pos(entry=100.0, current=100.0, weight=0.1):
    return {"entry_price": entry, "current_price": current, "weight": weight}


class PositionDrawdownTest(unittest.TestCase):
    def test_exact_ten_percent(self):
        self.assertAlmostEqual(CB.position_drawdown(100, 90), -0.10, places=9)

    def test_gain_positive(self):
        self.assertAlmostEqual(CB.position_drawdown(100, 120), 0.20, places=9)

    def test_zero_current_is_total_loss(self):
        self.assertAlmostEqual(CB.position_drawdown(100, 0), -1.0, places=9)

    def test_invalid_entry_price(self):
        with self.assertRaises(ValueError):
            CB.position_drawdown(0, 90)
        with self.assertRaises(ValueError):
            CB.position_drawdown(-1, 90)

    def test_negative_current_rejected(self):
        with self.assertRaises(ValueError):
            CB.position_drawdown(100, -5)

    def test_drawdowns_mapping(self):
        out = CB.drawdowns({"A": pos(100, 90), "B": pos(100, 110)})
        self.assertAlmostEqual(out["A"], -0.10, places=9)
        self.assertAlmostEqual(out["B"], 0.10, places=9)


class SingleStopTest(unittest.TestCase):
    def test_exact_minus_10_forces_exit(self):
        r = CB.evaluate({"A": pos(100, 90)}, portfolio_drawdown=-0.02)
        exits = [e for e in r["forced_exits"] if e["symbol"] == "A"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["status"], "ready")

    def test_just_above_stop_holds(self):
        r = CB.evaluate({"A": pos(100, 90.01)}, portfolio_drawdown=-0.02)
        self.assertEqual(r["forced_exits"], [])
        self.assertEqual(r["mode"], CB.MODE_NORMAL)

    def test_limit_down_defers_exit(self):
        r = CB.evaluate({"A": pos(100, 85)}, portfolio_drawdown=-0.02, limit_down=("A",))
        exits = [e for e in r["forced_exits"] if e["symbol"] == "A"]
        self.assertEqual(exits[0]["status"], "pending_limit_down")
        self.assertTrue(any("跌停" in s for s in r["reasons"]))

    def test_stop_independent_of_portfolio_tier(self):
        r = CB.evaluate({"A": pos(100, 85)}, portfolio_drawdown=-0.16)
        self.assertEqual(r["mode"], CB.MODE_HALF)
        self.assertEqual(len(r["forced_exits"]), 1)


class PortfolioTierTest(unittest.TestCase):
    def test_half_at_exact_15(self):
        r = CB.evaluate({}, portfolio_drawdown=-0.15)
        self.assertEqual(r["mode"], CB.MODE_HALF)
        self.assertAlmostEqual(r["scale"], 0.5)

    def test_no_half_above_15(self):
        r = CB.evaluate({}, portfolio_drawdown=-0.1499)
        self.assertEqual(r["mode"], CB.MODE_NORMAL)
        self.assertAlmostEqual(r["scale"], 1.0)

    def test_clear_at_exact_25(self):
        r = CB.evaluate({"A": pos()}, portfolio_drawdown=-0.25)
        self.assertEqual(r["mode"], CB.MODE_CLEARED)
        self.assertAlmostEqual(r["scale"], 0.0)
        self.assertTrue(r["requires_manual_reset"])
        self.assertTrue(r["block_new_entries"])
        self.assertTrue(any(a["action"] == "clear_all" for a in r["actions"]))

    def test_clear_exits_everything(self):
        r = CB.evaluate({"A": pos(), "B": pos()}, portfolio_drawdown=-0.30)
        self.assertEqual({e["symbol"] for e in r["forced_exits"]}, {"A", "B"})

    def test_half_recovery_hysteresis(self):
        half_state = {"mode": CB.MODE_HALF, "high_water": 1.0}
        r = CB.evaluate({}, portfolio_drawdown=-0.05, state=half_state)
        self.assertEqual(r["mode"], CB.MODE_NORMAL)
        self.assertAlmostEqual(r["scale"], 1.0)

    def test_half_sticks_between_lines(self):
        half_state = {"mode": CB.MODE_HALF, "high_water": 1.0}
        r = CB.evaluate({}, portfolio_drawdown=-0.12, state=half_state)
        self.assertEqual(r["mode"], CB.MODE_HALF)

    def test_cleared_is_sticky_despite_recovery(self):
        cleared = {"mode": CB.MODE_CLEARED, "high_water": 1.0, "manual_reset_required": True}
        r = CB.evaluate({}, portfolio_drawdown=-0.01, state=cleared)
        self.assertEqual(r["mode"], CB.MODE_CLEARED)
        self.assertAlmostEqual(r["scale"], 0.0)
        self.assertTrue(r["block_new_entries"])


class FailClosedTest(unittest.TestCase):
    def test_missing_drawdown_blocks_new_entries(self):
        r = CB.evaluate({"A": pos()}, portfolio_drawdown=None)
        self.assertTrue(r["block_new_entries"])
        self.assertEqual(r["actions"][0]["action"], "fail_closed")
        self.assertEqual(r["mode"], CB.MODE_NORMAL)

    def test_missing_drawdown_keeps_previous_mode(self):
        st = {"mode": CB.MODE_HALF, "high_water": 1.0}
        r = CB.evaluate({}, portfolio_drawdown=None, state=st)
        self.assertEqual(r["mode"], CB.MODE_HALF)

    def test_positive_drawdown_rejected(self):
        with self.assertRaises(ValueError):
            CB.evaluate({}, portfolio_drawdown=0.05)


class ResetTest(unittest.TestCase):
    def test_reset_from_cleared(self):
        st = {"mode": CB.MODE_CLEARED, "high_water": 1.2, "manual_reset_required": True}
        new = CB.reset(st, approved_by="主人", reason="复盘通过")
        self.assertEqual(new["mode"], CB.MODE_NORMAL)
        self.assertFalse(new["manual_reset_required"])
        self.assertEqual(new["reset_by"], "主人")

    def test_reset_requires_approver(self):
        st = {"mode": CB.MODE_CLEARED, "manual_reset_required": True}
        with self.assertRaises(ValueError):
            CB.reset(st, approved_by="")

    def test_reset_noop_from_normal(self):
        st = {"mode": CB.MODE_NORMAL}
        self.assertEqual(CB.reset(st, approved_by="x")["mode"], CB.MODE_NORMAL)


class PersistenceTest(unittest.TestCase):
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cb.json"
            st = CB.evaluate({}, portfolio_drawdown=-0.16)["state"]
            CB.save_state(p, st)
            loaded = CB.load_state(p)
            self.assertEqual(loaded["mode"], CB.MODE_HALF)
            self.assertAlmostEqual(loaded["last_drawdown"], -0.16, places=6)

    def test_load_missing_or_corrupt_returns_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(CB.load_state(Path(td) / "nope.json")["mode"], CB.MODE_NORMAL)
            bad = Path(td) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(CB.load_state(bad)["mode"], CB.MODE_NORMAL)

    def test_event_append(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            CB.append_event(p, {"event": "eval", "mode": "normal"})
            CB.append_event(p, {"event": "reset", "by": "主人"})
            rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["event"] for r in rows], ["eval", "reset"])

    def test_high_water_initialized(self):
        r = CB.evaluate({}, portfolio_drawdown=-0.02)
        self.assertEqual(r["state"]["high_water"], 1.0)


class RenderTest(unittest.TestCase):
    def test_render_normal(self):
        line = CB.render_line(CB.evaluate({}, portfolio_drawdown=-0.02))
        self.assertIn("回撤熔断(P6)", line)
        self.assertIn("normal", line)

    def test_render_cleared_warns_reset(self):
        line = CB.render_line(CB.evaluate({}, portfolio_drawdown=-0.30))
        self.assertIn("清仓冷却", line)
        self.assertIn("circuit-reset", line)


class ReportIntegrationTest(unittest.TestCase):
    def test_build_report_renders_circuit_breaker(self):
        from astock_monitor.report import build_report
        kw = dict(date_str="2026-11-18", regime_state=1, regime_label="neutral",
                  erp_pct=77.0, breadth=0.24, margin_greed=0.44, vol_pct=0.55,
                  triggers={}, signals_today=None, portfolio={}, portfolio_changes={},
                  doctor_summary=None, conclusions_snapshot={"total": 1})
        rep = CB.evaluate({}, portfolio_drawdown=-0.16)
        txt = build_report(circuit_breaker=rep, **kw)
        self.assertIn("回撤熔断(P6)", txt)
        self.assertIn("half", txt)
        # 未接线时如实说明模块状态（不假称已接入实时净值）
        txt2 = build_report(**kw)
        self.assertIn("模块已实装", txt2)


if __name__ == "__main__":
    unittest.main()
