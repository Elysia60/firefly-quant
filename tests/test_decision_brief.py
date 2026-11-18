# -*- coding: utf-8 -*-
"""test_decision_brief.py — 决策简报测试（2026-11-19）

决策矩阵是心脏:四分支全覆盖 + 失效条件必在 + 渲染 smoke + DB 读函数。
零联网,fixture 驱动。
"""
import json
import sqlite3
import unittest
from datetime import date

from astock_monitor.decision_brief import (build_brief, decide_action,  # noqa: E402
                                           judge_accuracy, latest_signal_row, render)
from astock_monitor import forecast as F  # noqa: E402


def _sig_row(verdict="neutral", composite=0.0, day="2026-11-18", comps=None):
    return {"signal_date": day, "verdict": verdict, "composite": composite,
            "components": comps or {"breadth": 0.5, "sentiment": 55, "gap_days": 0}}


class TestDecisionMatrix(unittest.TestCase):
    """四分支:熔断压倒一切 → avoid → buy → neutral。"""

    def test_breaker_halt_overrides_everything(self):
        r = decide_action("halt", False, "buy_watch", None)
        self.assertEqual(r["action"], "禁止新开仓")

    def test_manual_reset_required_blocks(self):
        r = decide_action("normal", True, "buy_watch", None)
        self.assertEqual(r["action"], "禁止新开仓")

    def test_avoid_watch_observes(self):
        r = decide_action("normal", False, "avoid_watch", None)
        self.assertEqual(r["action"], "观望/规避")
        self.assertTrue(r["invalidated_when"])

    def test_buy_watch_allows_lots(self):
        r = decide_action("normal", False, "buy_watch", None)
        self.assertEqual(r["action"], "可分批建仓")
        self.assertIn("35%", r["reason"][1])  # SINGLE_CAP=0.35 渲染成 35%

    def test_neutral_holds(self):
        r = decide_action("normal", False, "neutral", None)
        self.assertEqual(r["action"], "持有观察，不加不减")

    def test_missing_signal_observes(self):
        r = decide_action("normal", False, None, None)
        self.assertIn("观望", r["action"])

    def test_every_branch_has_invalidation(self):
        """不可对账的建议不进简报——每条必须带失效条件。"""
        for verdict in ("avoid_watch", "buy_watch", "neutral", None):
            r = decide_action("normal", False, verdict, None)
            self.assertTrue(r.get("invalidated_when"), f"{verdict} 缺失效条件")


class TestBuildAndRender(unittest.TestCase):
    def test_build_brief_fuses_all(self):
        acct = {"cash": 1000000.0, "positions": {}, "high_water": 1000000.0,
                "last_day": "2026-11-18"}
        breaker = {"mode": "normal", "manual_reset_required": False,
                   "last_drawdown": None}
        brief = build_brief(_sig_row("buy_watch", 0.42), {"5": {"judged": 10, "hit": 7, "rate": 0.7}},
                            acct, breaker, [{"equity": 995000.0}], "2026-11-19")
        self.assertEqual(brief["action"]["action"], "可分批建仓")
        self.assertEqual(brief["paper"]["cash"], 1000000.0)
        self.assertEqual(brief["judge"]["5"]["rate"], 0.7)
        md = render(brief)
        self.assertIn("每日决策简报", md)
        self.assertIn("可分批建仓", md)
        self.assertIn("T+5", md)
        self.assertIn("不构成投资建议", md)

    def test_render_without_signal(self):
        acct = {"cash": 500000.0, "positions": {"000001.SZ": {"entry_price": 10.0}},
                "high_water": None, "last_day": None}
        brief = build_brief(None, None, acct, {"mode": "normal",
                                               "manual_reset_required": False},
                            None, "2026-11-19")
        self.assertEqual(brief["action"]["action"], "观望（信号缺失）")
        md = render(brief)
        self.assertIn("无信号", md)


class TestDbReaders(unittest.TestCase):
    def test_latest_and_accuracy_from_memory_db(self):
        conn = sqlite3.connect(":memory:")
        F.init_db(conn)
        from astock_monitor.signals import Signal, DataQuality
        dq = DataQuality(breadth="ok", sentiment="ok", gap_days=0)
        sig = Signal(signal_date=date(2026, 11, 18), trend_score=0.3,
                     composite=0.25, verdict="neutral",
                     components={"breadth": 0.5, "sentiment": 55, "gap_days": 0},
                     data_quality=dq)
        F.record_signal(conn, sig)
        latest = latest_signal_row(conn)
        self.assertEqual(latest["verdict"], "neutral")
        self.assertEqual(latest["signal_date"], "2026-11-18")
        # 无判卷 → None
        self.assertIsNone(judge_accuracy(conn))


if __name__ == "__main__":
    unittest.main()
