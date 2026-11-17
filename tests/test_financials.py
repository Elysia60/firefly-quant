# -*- coding: utf-8 -*-
"""financials.py 单测:业绩报表采集(零联网,fake fetcher)。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from astock_monitor.collect import RateLimiter
from astock_monitor.financials import collect_yjbb
from astock_monitor.store import init_db

RL = RateLimiter(min_interval=0)


class CollectYjbbTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg = {"paths": {"lake_raw": str(Path(self.td.name) / "lake" / "raw"),
                              "db": str(Path(self.td.name) / "m.db")},
                    "collect": {"min_interval": 0}}
        self.conn = sqlite3.connect(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.td.cleanup()

    def _fake(self, period: str = "20260930"):
        import pandas as pd
        return pd.DataFrame({
            "股票代码": ["000001", "600519"],
            "股票简称": ["平安银行", "贵州茅台"],
            "每股收益": [1.2, 55.0],
            "营业收入-营业收入": [1000000000.0, 8000000000.0],
            "净利润-净利润": [200000000.0, 4000000000.0],
        })

    def test_collect_ok_and_idempotent(self):
        r1 = collect_yjbb(self.cfg, self.conn, "20260930", fetcher=self._fake,
                          limiter=RL)
        self.assertEqual(r1["status"], "ok")
        self.assertEqual(r1["rows"], 2)
        p = Path(r1["path"])
        self.assertTrue(p.exists())
        # 幂等:同报告期再跑 → skipped
        r2 = collect_yjbb(self.cfg, self.conn, "20260930", fetcher=self._fake,
                          limiter=RL)
        self.assertEqual(r2["status"], "skipped")

    def test_bad_period_rejected(self):
        with self.assertRaises(ValueError):
            collect_yjbb(self.cfg, self.conn, "2026Q3", fetcher=self._fake,
                         limiter=RL)

    def test_empty_raises(self):
        import pandas as pd
        with self.assertRaises(ValueError):
            collect_yjbb(self.cfg, self.conn, "20260930",
                         fetcher=lambda period: pd.DataFrame(), limiter=RL)


if __name__ == "__main__":
    unittest.main()
