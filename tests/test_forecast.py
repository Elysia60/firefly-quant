"""forecast.py 单测:判卷窗口跨国庆走交易日 / correct 口径 / 幂等 / 不到期不判 / 回放闭环。"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from astock_monitor import forecast as F
from astock_monitor import signals as S
from astock_monitor.store import get_conn
from tests.test_calendar import _synthetic_days

DAYS = _synthetic_days()  # 2026-09-21 ~ 10-16 工作日,扣国庆 10-01/02/05/06/07


def _closes_from_pattern(pattern: dict[date, float]) -> dict[date, float]:
    return {d: pattern.get(d, 100.0) for d in DAYS}


class ForecastJudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = get_conn(Path(self.tmp.name) / "m.db")
        F.init_db(self.conn)
        # 价格脚本:09-30=100;10-08..10-14 递增(供 T+5=110);10-15/16 下跌(供 T+20 不存在→只测 T+5)
        self.closes = _closes_from_pattern({
            date(2026, 9, 30): 100.0,
            date(2026, 10, 8): 102.0,
            date(2026, 10, 9): 104.0,
            date(2026, 10, 12): 106.0,
            date(2026, 10, 13): 108.0,
            date(2026, 10, 14): 110.0,
        })

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _signal(self, verdict: str, day: date = date(2026, 9, 30)) -> S.Signal:
        return S.Signal(signal_date=day, trend_score=70.0, composite=70.0,
                        verdict=verdict, components={}, data_quality=S.DataQuality())

    def test_t5_window_crosses_national_holiday(self):
        # 09-30 的 T+5 = 10-14(跳过国庆),fwd = 110/100−1 = +10%;T+20 超出日历不判
        F.record_signal(self.conn, self._signal("buy_watch"))
        n = F.judge_due(self.conn, self.closes, DAYS, today=date(2026, 10, 16))
        self.assertEqual(n, 1)
        row5 = self.conn.execute(
            "SELECT fwd_ret, correct, judged FROM forecast_log WHERE window_days=5").fetchone()
        self.assertEqual(row5[2], 1)
        self.assertAlmostEqual(row5[0], 0.10, places=6)
        self.assertEqual(row5[1], 1)  # buy_watch 且 fwd>0 → correct

    def test_t20_beyond_calendar_stays_unjudged(self):
        F.record_signal(self.conn, self._signal("buy_watch"))
        F.judge_due(self.conn, self.closes, DAYS, today=date(2026, 10, 16))
        row20 = self.conn.execute(
            "SELECT judged FROM forecast_log WHERE window_days=20").fetchone()
        self.assertEqual(row20[0], 0)  # 日历覆盖不足 → 留待,不提前猜

    def test_correct_semantics_by_verdict(self):
        # avoid_watch:T+5=110>100 → 躲跌失败 → correct=0
        F.record_signal(self.conn, self._signal("avoid_watch"))
        # neutral:方向不主张 → correct NULL 但 fwd 照记
        F.record_signal(self.conn, self._signal("neutral", day=date(2026, 10, 8)))
        F.judge_due(self.conn, self.closes, DAYS, today=date(2026, 10, 16))
        av = self.conn.execute(
            "SELECT correct FROM forecast_log WHERE verdict='avoid_watch' AND window_days=5").fetchone()
        self.assertEqual(av[0], 0)
        nu = self.conn.execute(
            "SELECT correct, fwd_ret FROM forecast_log WHERE verdict='neutral' AND window_days=5").fetchone()
        self.assertIsNone(nu[0])
        self.assertIsNotNone(nu[1])

    def test_record_idempotent(self):
        F.record_signal(self.conn, self._signal("buy_watch"))
        F.record_signal(self.conn, self._signal("buy_watch"))
        n = self.conn.execute("SELECT COUNT(*) FROM forecast_log").fetchone()[0]
        self.assertEqual(n, 2)  # 每窗一行,重跑不重复

    def test_not_due_not_judged(self):
        F.record_signal(self.conn, self._signal("buy_watch", day=date(2026, 10, 15)))
        n = F.judge_due(self.conn, self.closes, DAYS, today=date(2026, 10, 16))
        self.assertEqual(n, 0)  # T+5=10-22 未到

    def test_missing_signal_day_close_stays_unjudged(self):
        F.record_signal(self.conn, self._signal("buy_watch", day=date(2026, 10, 1)))  # 国庆,无收盘
        n = F.judge_due(self.conn, self.closes, DAYS, today=date(2026, 10, 16))
        self.assertEqual(n, 0)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = get_conn(Path(self.tmp.name) / "m.db")
        F.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_replay_closes_loop(self):
        # ~45 个工作日的确定性锯齿行情(振幅大,保证 SMA/RSI 有变化,verdict 覆盖多种)
        import calendar as _cal
        holidays = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
                    date(2026, 10, 6), date(2026, 10, 7)}
        extra = []
        for m in (10, 11):
            for d in range(1, _cal.monthrange(2026, m)[1] + 1):
                dt = date(2026, m, d)
                if dt.weekday() < 5 and dt not in holidays:
                    extra.append(dt)
        days = sorted(set(DAYS) | set(extra))
        rows = [(d, 100.0 + (i % 6) * 2.0 - 5.0) for i, d in enumerate(days)]
        start, end = days[25], days[-2]
        r = F.replay(self.conn, rows, days, start, end)
        self.assertGreater(r["recorded_signals"], 0)
        total = self.conn.execute("SELECT COUNT(*) FROM forecast_log").fetchone()[0]
        self.assertEqual(total, r["recorded_signals"])
        # 汇总结构:每窗都有数字;小样本标注打开
        for w, by_verdict in r["summary"]["windows"].items():
            for v, st in by_verdict.items():
                self.assertIn("small_sample", st)
                self.assertTrue(st["small_sample"])  # 回放样本 <30,诚实标注


if __name__ == "__main__":
    unittest.main()
