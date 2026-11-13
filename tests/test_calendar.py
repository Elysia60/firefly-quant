"""calendar.py 单测:跨 2026 国庆窗口加法 / 对拍 / 缓存往返 / 合成湖读取。零联网。"""

import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

from astock_monitor import calendar as cal


def _synthetic_days() -> list[date]:
    """2026-09-21 ~ 2026-10-16 工作日,扣除国庆假期 10-01/02/05/06/07。"""
    holidays = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
                date(2026, 10, 6), date(2026, 10, 7)}
    days = []
    d = date(2026, 9, 21)
    while d <= date(2026, 10, 16):
        if d.weekday() < 5 and d not in holidays:  # Mon-Fri
            days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    return days


class CalendarWindowTest(unittest.TestCase):
    def setUp(self):
        self.days = _synthetic_days()

    def test_add_one_skips_national_holiday(self):
        # 2026-09-30(周三) + 1 交易日 = 10-08(周四),跳过 10-01~10-07
        self.assertEqual(cal.add_trading_days(date(2026, 9, 30), 1, self.days), date(2026, 10, 8))

    def test_add_five_trading_days(self):
        # 09-30 + 5 交易日 = 10-14(10-08,09,12,13,14)——判卷窗口不因长假漂移
        self.assertEqual(cal.add_trading_days(date(2026, 9, 30), 5, self.days), date(2026, 10, 14))

    def test_add_zero_semantics(self):
        self.assertEqual(cal.add_trading_days(date(2026, 9, 30), 0, self.days), date(2026, 9, 30))
        # 落在假日:回退到下一交易日
        self.assertEqual(cal.add_trading_days(date(2026, 10, 1), 0, self.days), date(2026, 10, 8))
        self.assertEqual(cal.add_trading_days(date(2026, 10, 3), 0, self.days), date(2026, 10, 8))  # 周六

    def test_out_of_coverage_fails_loud(self):
        with self.assertRaises(ValueError):
            cal.add_trading_days(date(2026, 10, 15), 10, self.days)
        with self.assertRaises(ValueError):
            cal.add_trading_days(date(2026, 10, 16), 1, self.days)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            cal.add_trading_days(date(2026, 9, 30), -1, self.days)

    def test_trading_days_slice(self):
        got = cal.trading_days(self.days, start=date(2026, 10, 8), end=date(2026, 10, 12))
        self.assertEqual(got, [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)])


class CrosscheckTest(unittest.TestCase):
    def test_identical(self):
        days = _synthetic_days()
        r = cal.crosscheck(days, list(days))
        self.assertTrue(r["identical"])
        self.assertEqual(r["count_a"], r["count_b"])

    def test_divergence_detected(self):
        days = _synthetic_days()
        polluted = [d for d in days if d != date(2026, 10, 8)]  # 对方少了 10-08
        r = cal.crosscheck(days, polluted)
        self.assertFalse(r["identical"])
        self.assertEqual(r["only_in_a"], ["2026-10-08"])


class CacheTest(unittest.TestCase):
    def test_cache_roundtrip(self):
        days = _synthetic_days()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.json"
            cal.cache_to_json(days, path)
            self.assertEqual(cal.load_calendar_cache(path), days)

    def test_missing_cache_returns_none(self):
        self.assertIsNone(cal.load_calendar_cache("Z:/definitely/not/here.json"))


@unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("pyarrow"),
                     "需要 pandas+pyarrow")
class SyntheticLakeTest(unittest.TestCase):
    def test_read_cnequity_calendar(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp:
            lake = Path(tmp)
            df = pd.DataFrame({
                "trade_date": [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 8)],
                "is_trading": [1, 0, 1],
            })
            for td in ("2026-09-30", "2026-10-01", "2026-10-08"):
                part = lake / "curated" / "trading_calendar" / f"trade_date={td}"
                part.mkdir(parents=True)
                df.to_parquet(part / "part-merged.parquet", index=False)
            days = cal.read_cnequity_calendar(lake)
            self.assertEqual(days, [date(2026, 9, 30), date(2026, 10, 8)])


class SessionDayTest(unittest.TestCase):
    """is_session_day: P4 信号守卫(周末/节假日拒绝, 覆盖外也拒绝——宁可少出不造伪)."""

    def test_member_day_true(self):
        days = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16)]
        self.assertTrue(cal.is_session_day(date(2026, 11, 13), days))

    def test_weekend_false(self):
        days = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16)]
        self.assertFalse(cal.is_session_day(date(2026, 11, 14), days))  # 周六
        self.assertFalse(cal.is_session_day(date(2026, 11, 15), days))  # 周日

    def test_outside_coverage_false(self):
        """日历覆盖不到的日期一律 False(fail-closed): 宁可跳过一天信号."""
        days = [date(2026, 11, 12), date(2026, 11, 13)]
        self.assertFalse(cal.is_session_day(date(2026, 11, 16), days))

    def test_holiday_false(self):
        days = [date(2026, 9, 30), date(2026, 10, 8)]  # 国庆 10-01~07 缺席
        self.assertFalse(cal.is_session_day(date(2026, 10, 1), days))
        self.assertTrue(cal.is_session_day(date(2026, 10, 8), days))


if __name__ == "__main__":
    unittest.main()
