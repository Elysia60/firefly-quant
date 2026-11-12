"""doctor.py 单测:冷却状态识别/涨跌停抽样回验/日历降级判定。零联网。"""

import json
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from astock_monitor import doctor
from astock_monitor.store import get_conn, init_db
from tests.test_collect import _temp_cfg


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = _temp_cfg(self.tmp.name)
        self.conn = get_conn(Path(self.cfg["paths"]["db"]))
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_overall_fail_without_calendar_source(self):
        # 空环境:湖不存在且无缓存 → calendar FAIL → overall FAIL
        report = doctor.run_doctor(self.cfg, self.conn)
        cal = next(c for c in report["checks"] if c["name"] == "calendar")
        self.assertEqual(cal["status"], "FAIL")
        self.assertEqual(report["overall"], "FAIL")

    def test_calendar_cache_fallback(self):
        days = []
        d = date(2026, 11, 2)
        while len(days) < 10:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        from astock_monitor.calendar import cache_to_json
        cache_to_json(days, self.cfg["collect"]["calendar_cache"])
        report = doctor.run_doctor(self.cfg, self.conn)
        cal = next(c for c in report["checks"] if c["name"] == "calendar")
        self.assertIn(cal["status"], ("PASS", "WARN"))  # 来源=cache;覆盖不足今日则 WARN
        self.assertIn("cache", cal["detail"])
        # overall 不再因日历 FAIL
        self.assertEqual(report["overall"], "PASS")

    def test_cooldown_warn(self):
        path = Path(self.cfg["collect"]["cooldown_file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"blocked_until": time.time() + 120}), encoding="utf-8")
        report = doctor.run_doctor(self.cfg, self.conn)
        rl = next(c for c in report["checks"] if c["name"] == "rate_limit")
        self.assertEqual(rl["status"], "WARN")
        self.assertIn("冷却中", rl["detail"])

    def test_limits_sample_with_snapshot(self):
        import pandas as pd

        snap_dir = Path(self.cfg["paths"]["lake_norm"]) / "daily_snapshot" / "dt=20261111"
        snap_dir.mkdir(parents=True)
        # 600519 主板真实涨停:昨收 10.00 → 涨停 11.00
        pd.DataFrame({
            "date": ["2026-11-11"], "code": ["600519"], "name": ["贵州茅台"],
            "open": [10.5], "high": [11.0], "low": [10.4], "close": [11.0],
            "prev_close": [10.0], "volume": [1], "amount": [1.0],
            "pct_chg": [10.0], "turnover": [1.0],
        }).to_parquet(snap_dir / "part.parquet", index=False)
        report = doctor.run_doctor(self.cfg, self.conn)
        lim = next(c for c in report["checks"] if c["name"] == "limits_sample")
        self.assertEqual(lim["status"], "PASS")
        self.assertIn("1 只", lim["detail"])

    def test_report_persisted(self):
        doctor.run_doctor(self.cfg, self.conn)
        path = Path(self.cfg["paths"]["state_dir"]) / "doctor_report.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("overall", data)
        self.assertEqual(len(data["checks"]), 7)


if __name__ == "__main__":
    unittest.main()
