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
        self.assertEqual(len(data["checks"]), 10)


def _write_daily_bars(lake: Path, rows: list[dict]):
    """造一个最小 daily_bars 月度分区(DQ 检查测试用)。"""
    import pandas as pd
    part = lake / "curated" / "daily_bars" / "trade_date=2026-11"
    part.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(part / "part-merged.parquet", index=False)


class DataQualityTest(unittest.TestCase):
    """DQ 三检查: 日历对账(XSHG)/涨跌幅对拍(注入 fetcher 零联网)/sanity 清单。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = _temp_cfg(self.tmp.name)
        self.cfg["paths"]["cnequity_lake"] = str(Path(self.tmp.name) / "lake")
        self.lake = Path(self.cfg["paths"]["cnequity_lake"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_sanity_clean_pass(self):
        rows = [{"symbol": "000001.SZ", "trade_date": f"2026-11-{d:02d}",
                 "open": 10.0, "high": 11.2, "low": 9.9, "close": round(10.0 + 0.1 * i, 2),
                 "volume": 100} for i, d in enumerate(range(2, 12), start=1)]
        _write_daily_bars(self.lake, rows)
        rep = doctor.check_dq_sanity(self.cfg)
        self.assertEqual(rep["status"], "PASS")

    def test_sanity_ohlc_violation_fail(self):
        # high < close 违反 OHLC 一致性 → FAIL
        rows = [{"symbol": "000001.SZ", "trade_date": "2026-11-03",
                 "open": 10.0, "high": 9.5, "low": 9.9, "close": 10.0, "volume": 100}]
        _write_daily_bars(self.lake, rows)
        rep = doctor.check_dq_sanity(self.cfg)
        self.assertEqual(rep["status"], "FAIL")
        self.assertIn("OHLC", rep["detail"])

    def test_sanity_jump_over_limit_fail(self):
        # 单日 +50% 跳变(超北交所 30% 上限) → FAIL;每 symbol 首日无前收不算
        rows = [{"symbol": "000001.SZ", "trade_date": f"2026-11-{d}",
                 "open": p, "high": p, "low": p, "close": p, "volume": 100}
                for d, p in (("03", 10.0), ("04", 15.0))]
        _write_daily_bars(self.lake, rows)
        rep = doctor.check_dq_sanity(self.cfg)
        self.assertEqual(rep["status"], "FAIL")
        self.assertIn("跳变", rep["detail"])

    def test_sanity_empty_warn(self):
        rep = doctor.check_dq_sanity(self.cfg)
        self.assertEqual(rep["status"], "WARN")

    def test_returns_crosscheck_pass(self):
        # 湖与第二源涨跌幅一致 → PASS(fetcher 注入,零联网)
        import datetime as dt_mod
        import pandas as pd
        days = [f"2026-11-{d:02d}" for d in range(3, 13)]
        lake_rows, ext_rows = [], []
        price = 10.0
        for d in days:
            lake_rows.append({"symbol": "000001.SZ", "trade_date": d,
                              "open": price, "high": price, "low": price,
                              "close": round(price, 2), "volume": 100})
            ext_rows.append({"trade_date": dt_mod.date.fromisoformat(d),
                             "close": round(price, 2)})
            price *= 1.01
        _write_daily_bars(self.lake, lake_rows)
        rep = doctor.check_dq_returns(self.cfg, fetcher=lambda code6: pd.DataFrame(ext_rows))
        self.assertEqual(rep["status"], "PASS", rep["detail"])

    def test_returns_crosscheck_pollution_fail(self):
        # 第二源与湖涨跌幅系统性巨差(湖 +1%/日 vs 源 +3%/日, >1% 容差) → FAIL
        # 注意: 常数乘性偏移会在 pct_change 中约掉, 必须用不同增长率才构成真差异
        import datetime as dt_mod
        import pandas as pd
        days = [f"2026-11-{d:02d}" for d in range(3, 13)]
        lake_rows, ext_rows = [], []
        price, ext_price = 10.0, 10.0
        for d in days:
            lake_rows.append({"symbol": "000001.SZ", "trade_date": d,
                              "open": price, "high": price, "low": price,
                              "close": round(price, 2), "volume": 100})
            ext_rows.append({"trade_date": dt_mod.date.fromisoformat(d),
                             "close": round(ext_price, 2)})
            price *= 1.01
            ext_price *= 1.03
        _write_daily_bars(self.lake, lake_rows)
        rep = doctor.check_dq_returns(self.cfg, fetcher=lambda code6: pd.DataFrame(ext_rows))
        self.assertEqual(rep["status"], "FAIL")

    def test_returns_no_data_warn(self):
        rep = doctor.check_dq_returns(self.cfg)
        self.assertEqual(rep["status"], "WARN")

    def test_calendar_crosscheck_no_lake_warn(self):
        # 空环境(无湖) → WARN(不 FAIL: 对账缺源是降级不是污染)
        rep = doctor.check_dq_calendar(self.cfg)
        self.assertEqual(rep["status"], "WARN")


if __name__ == "__main__":
    unittest.main()
