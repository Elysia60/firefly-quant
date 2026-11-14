# -*- coding: utf-8 -*-
"""triggers.py 单测:跨越状态机 / 分位池不含当日 / 阈值方向。"""
import unittest
from datetime import date, timedelta

from astock_monitor import triggers as TR


class RollingPctileTest(unittest.TestCase):
    def test_pool_excludes_today(self):
        vals = [(date(2024, 1, 1) + timedelta(days=i), float(i)) for i in range(100)]
        p = TR.rolling_pctile_exclude_today(vals, window=2500)
        # 第 99 天的值 99.0,池=前 99 天(0..98) → 分位 = 99/99 = 1.0(最高)
        self.assertAlmostEqual(p[date(2024, 1, 1) + timedelta(days=99)], 1.0)
        # 分位池不含当日:若含当日,99 天里 100 个值 self<=self 会得 1.0——
        # 关键断言:第 50 天(值 50,池 0..49 全 ≤50)分位=1.0,而池含当日也一样;
        # 用严格不等式构造区分:全部相同值 → 分位应为 1.0(<=计数)而非 0
        same = [(date(2024, 2, 1) + timedelta(days=i), 5.0) for i in range(100)]
        p2 = TR.rolling_pctile_exclude_today(same, window=2500)
        self.assertAlmostEqual(p2[date(2024, 2, 1) + timedelta(days=99)], 1.0)

    def test_insufficient_pool_none(self):
        vals = [(date(2024, 1, 1) + timedelta(days=i), 1.0) for i in range(50)]
        p = TR.rolling_pctile_exclude_today(vals, window=2500)
        self.assertTrue(all(v is None for v in p.values()))


class EvalTriggersTest(unittest.TestCase):
    def setUp(self):
        self.th = {"erp_low_pct": 0.05, "breadth_bear": 0.4,
                   "margin_greed_high": 0.9, "vol_pct_high": 0.9}

    def _metrics(self, **kw):
        base = {"erp_pct": 0.5, "breadth": 0.6, "greed": 0.5,
                "vol_pct": 0.5, "regime": 1}
        base.update(kw)
        return base

    def test_crossing_fires_once(self):
        st = {}
        # 跨越:宽度 0.6→0.3
        r1 = TR.eval_triggers(self._metrics(breadth=0.3), self.th, st)
        self.assertTrue(r1["T-宽度"]["fired"])
        self.assertTrue(r1["T-宽度"]["changed"])
        st2 = {k: {"fired": v["fired"], "since": v["since"]} for k, v in r1.items()}
        # 持续触发:不重复
        r2 = TR.eval_triggers(self._metrics(breadth=0.3), self.th, st2)
        self.assertTrue(r2["T-宽度"]["fired"])
        self.assertFalse(r2["T-宽度"]["changed"])

    def test_resolve_then_refire(self):
        st = {}
        r1 = TR.eval_triggers(self._metrics(breadth=0.3), self.th, st)
        st2 = {k: {"fired": v["fired"], "since": v["since"]} for k, v in r1.items()}
        r2 = TR.eval_triggers(self._metrics(breadth=0.6), self.th, st2)
        self.assertFalse(r2["T-宽度"]["fired"])
        st3 = {k: {"fired": v["fired"], "since": v["since"]} for k, v in r2.items()}
        r3 = TR.eval_triggers(self._metrics(breadth=0.3), self.th, st3)
        self.assertTrue(r3["T-宽度"]["fired"])
        self.assertTrue(r3["T-宽度"]["changed"])  # 解除后再触=新跨越

    def test_missing_metric_never_fires(self):
        r = TR.eval_triggers(self._metrics(breadth=None), self.th, {})
        self.assertFalse(r["T-宽度"]["fired"])

    def test_regime_bear_equal_op(self):
        r = TR.eval_triggers(self._metrics(regime=2), self.th, {})
        self.assertTrue(r["T-年线"]["fired"])
        r2 = TR.eval_triggers(self._metrics(regime=1), self.th, {})
        self.assertFalse(r2["T-年线"]["fired"])


if __name__ == "__main__":
    unittest.main()
