# -*- coding: utf-8 -*-
"""report.py 单测: 五层方法论自检段 + 剧本阶段映射 + 逻辑层适用域警示。"""
import unittest

from astock_monitor.report import build_report


def _base_kwargs():
    return dict(
        date_str="2026-11-18",
        regime_state=1,
        regime_label="neutral",
        erp_pct=77.0,
        breadth=0.2435,
        margin_greed=0.442,
        vol_pct=0.55,
        triggers={},
        signals_today={"verdict": "neutral", "tier": "观察", "composite": 54.0},
        portfolio={},
        portfolio_changes={},
        doctor_summary={"red": 0, "yellow": 1},
        conclusions_snapshot={"total": 17, "negative": 8, "rebuttal_open": 5},
    )


class FiveLayerTest(unittest.TestCase):
    def test_five_layer_section_present(self):
        report = build_report(**_base_kwargs())
        self.assertIn("## ⑥ 方法论自检(五层)", report)
        for layer in ("信息层", "逻辑层", "系统层", "人性层", "意义层"):
            self.assertIn(f"- {layer}问", report)

    def test_phase_observation(self):
        report = build_report(**_base_kwargs())
        self.assertIn("剧本阶段=观察", report)

    def test_phase_guard_with_single_trigger(self):
        kw = _base_kwargs()
        kw["triggers"] = {"T-ERP": {"fired": True}}
        report = build_report(**kw)
        self.assertIn("剧本阶段=戒备", report)

    def test_phase_defense_bear(self):
        kw = _base_kwargs()
        kw["regime_state"] = 2
        report = build_report(**kw)
        self.assertIn("剧本阶段=防御", report)

    def test_phase_defense_two_triggers(self):
        kw = _base_kwargs()
        kw["triggers"] = {"T-宽度": {"fired": True}, "T-波动": {"fired": True}}
        report = build_report(**kw)
        self.assertIn("剧本阶段=防御", report)
        self.assertIn("2/5 激活", report)

    def test_logic_note_avoid_watch_domain(self):
        kw = _base_kwargs()
        kw["signals_today"] = {"verdict": "avoid_watch", "tier": "观察", "composite": 44.8}
        report = build_report(**kw)
        self.assertIn("[S1]", report)
        self.assertIn("必要方向非充分信号", report)
        self.assertIn("剧本阶段=戒备", report)  # avoid_watch → 戒备

    def test_logic_note_buy_watch_no_action(self):
        kw = _base_kwargs()
        kw["signals_today"] = {"verdict": "buy_watch", "tier": "观察", "composite": 57.8}
        report = build_report(**kw)
        self.assertIn("[S2] 日频开关已证伪", report)

    def test_missing_data_renders_placeholder(self):
        kw = _base_kwargs()
        kw.update(margin_greed=None, breadth=None, erp_pct=None, doctor_summary=None)
        report = build_report(**kw)
        self.assertIn("缺", report)
        self.assertIn("体检未运行", report)


if __name__ == "__main__":
    unittest.main()
