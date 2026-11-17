# -*- coding: utf-8 -*-
"""能力路由/税制成本/策略守护/契约快照 四组回归测试(P-REA-1/2/3 落地)。

契约纪律:本文件的 schema 断言是**对外口径契约**——任何字段/类型变更必须
显式修改本文件,防止静默口径漂移(11-17 宽度史事故的测试层防线)。
"""
import json
import unittest
from datetime import date
from pathlib import Path

from astock_monitor.capability_router import CAPABILITIES, CapabilityRouter, SourceDecl
from astock_monitor.cost_schedule import round_trip_cost, stamp_rate
from astock_monitor.signals import Signal
from astock_monitor.strategy_guard import judge_from_final_combination, judge_strategy, robust_score


class CapabilityRouterTest(unittest.TestCase):
    def setUp(self):
        self.r = CapabilityRouter.default(now=lambda: 1000.0)

    def test_capability_catalog_registered(self):
        for cap in ("daily_bars", "spot_snapshot", "index_bars", "zt_pool",
                    "margin", "erp", "calendar"):
            self.assertIn(cap, CAPABILITIES)

    def test_route_primary_source(self):
        self.assertEqual(self.r.route("spot_snapshot"), "eastmoney")
        self.assertEqual(self.r.route("margin"), "csf_margin")   # 非 EM 域
        self.assertEqual(self.r.route("erp"), "legu")

    def test_route_failover_on_cooldown(self):
        # EM 冷却后,index_bars 自动降级到 sina(11-16 回补同款路径的制度化)
        self.r.report_failure("eastmoney")
        self.assertEqual(self.r.route("index_bars"), "sina")
        self.assertEqual(self.r.route("spot_snapshot"), None)  # 实时快照无备源→fail-closed

    def test_fail_closed_on_undeclared_capability(self):
        self.assertEqual(self.r.route("lhb"), None)            # 无源声明→拒绝
        self.assertEqual(self.r.route("unknown_cap"), None)    # 未登记能力→拒绝

    def test_exponential_cooldown_and_recovery(self):
        self.r.report_failure("eastmoney")
        s = self.r._get("eastmoney")
        self.assertEqual(s.health.fails, 1)
        self.assertAlmostEqual(s.health.cooldown_until - 1000.0, 60.0)
        self.r.report_failure("eastmoney")                     # 二连败
        self.assertAlmostEqual(s.health.cooldown_until - 1000.0, 120.0)  # 指数退避
        # 冷却期满恢复
        r2 = CapabilityRouter.default(now=lambda: 1000.0 + 3600.0)
        self.assertEqual(r2.route("spot_snapshot"), "eastmoney")

    def test_success_resets_health(self):
        self.r.report_failure("eastmoney")
        self.r.report_success("eastmoney")
        self.assertEqual(self.r.route("spot_snapshot"), "eastmoney")
        self.assertEqual(self.r._get("eastmoney").health.fails, 0)

    def test_state_persist_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            self.r.report_failure("eastmoney")
            self.r.save_state(p)
            r2 = CapabilityRouter.default(now=lambda: 1000.0)
            r2.load_state(p)
            self.assertEqual(r2.route("index_bars"), "sina")   # 冷却跨进程生效
            self.assertEqual(r2.route("spot_snapshot"), None)

    def test_corrupt_state_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{not json", encoding="utf-8")
            r2 = CapabilityRouter.default()
            r2.load_state(p)  # 不应抛异常
            self.assertEqual(r2.route("spot_snapshot"), "eastmoney")


class CostScheduleTest(unittest.TestCase):
    def test_stamp_history_segments(self):
        self.assertAlmostEqual(stamp_rate(date(2008, 9, 18)), 0.002)   # 双边 1‰
        self.assertAlmostEqual(stamp_rate(date(2008, 9, 19)), 0.001)   # 改卖出单边
        self.assertAlmostEqual(stamp_rate(date(2023, 8, 27)), 0.001)
        self.assertAlmostEqual(stamp_rate(date(2023, 8, 28)), 0.0005)  # 减半
        self.assertAlmostEqual(stamp_rate(date(2026, 11, 18)), 0.0005)

    def test_round_trip_alignment_with_registry(self):
        # 现行段(2023-08-28 后)必须与注册表 [S15] 用的 0.002 完全一致
        self.assertAlmostEqual(round_trip_cost(date(2026, 11, 18)), 0.002)
        # 2023-08-28 前 = 0.0025(更高 → [S15] 类负面结论方向性加固)
        self.assertAlmostEqual(round_trip_cost(date(2020, 1, 1)), 0.0025)
        # 2008-09-19 前 = 0.0035
        self.assertAlmostEqual(round_trip_cost(date(2005, 1, 1)), 0.0035)

    def test_type_error_on_non_date(self):
        with self.assertRaises(TypeError):
            round_trip_cost("2026-11-18")


class StrategyGuardTest(unittest.TestCase):
    def test_robust_score_formula(self):
        # 0.6×中位 + 0.4×最差(TSP 公式,中位抗离群,最差防幸存)
        self.assertAlmostEqual(robust_score([0.30, 0.07, 0.17, 0.32, 0.51]), 0.6*0.30 + 0.4*0.07)
        self.assertAlmostEqual(robust_score([0.10, 0.20]), 0.6*0.15 + 0.4*0.10)

    def test_three_states(self):
        healthy = judge_strategy("A", {2024: 0.30, 2025: 0.40, 2026: 0.20})
        self.assertEqual(healthy["state"], "healthy")
        retired = judge_strategy("B", {2024: -0.20, 2025: -0.30})
        self.assertEqual(retired["state"], "retired")
        watch = judge_strategy("C", {2024: 0.05, 2025: 0.03, 2026: -0.02})
        self.assertEqual(watch["state"], "watch")
        # 规则自洽检查:近一年为负但稳健分≥0 → watch(保守:近一年为负必须观察)

    def test_unknown_when_insufficient(self):
        self.assertEqual(judge_strategy("D", {2026: 0.10})["state"], "unknown")

    def test_json_serializable(self):
        r = judge_strategy("A", {2024: 0.30, 2025: -0.05})
        json.dumps(r, ensure_ascii=False)  # 不应抛异常


class ContractSnapshotTest(unittest.TestCase):
    """P-REA-2:对外口径契约快照——字段/类型变更必须显式改这里。"""

    def test_signal_as_dict_contract(self):
        sig = Signal(signal_date=date(2026, 11, 18), trend_score=50.65,
                     composite=44.29, verdict="avoid_watch",
                     components={"trend": 50.65, "momentum": 13.7,
                                 "sentiment": 78.7, "breadth": 0.1957,
                                 "greed": 44.2, "streak_up": 0,
                                 "renormalized": False, "missing": []})
        d = sig.as_dict()
        self.assertEqual(set(d.keys()),
                         {"signal_date", "trend_score", "composite", "verdict",
                          "tier", "components", "data_quality"})
        self.assertIsInstance(d["signal_date"], str)
        self.assertIsInstance(d["composite"], float)
        self.assertIsInstance(d["components"], dict)
        json.dumps(d, ensure_ascii=False)  # 全可序列化

    def test_registry_payload_contract(self):
        p = Path(__file__).resolve().parents[1] / "results" / "final_combination.json"
        if not p.exists():
            self.skipTest("results 未随仓(本地生成)")
        payload = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("meta", payload)
        self.assertIn("strategies", payload)
        self.assertIn("pair_tests", payload)
        for m in ("A", "B", "C", "D"):
            s = payload["strategies"].get(m)
            if s is None:
                continue
            self.assertEqual(set(s.keys()) >=
                             {"name", "nav", "ann_ret", "mdd", "n_periods",
                              "period_rets", "yearly_nav"}, True,
                             f"{m} 缺契约字段")

    def test_guard_from_final_combination(self):
        p = Path(__file__).resolve().parents[1] / "results" / "final_combination.json"
        if not p.exists():
            self.skipTest("results 未随仓(本地生成)")
        payload = json.loads(p.read_text(encoding="utf-8"))
        rows = judge_from_final_combination(payload)
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertIn(row["state"], ("healthy", "watch", "retired", "unknown"))
            json.dumps(row, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
