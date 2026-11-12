"""collect.py 单测:限速/退避/冷却持久化/manifest 幂等/列映射/宽度。零联网(fetcher 全注入)。"""

import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from astock_monitor import collect
from astock_monitor.store import get_conn, init_db


def _temp_cfg(tmp: str) -> dict:
    root = Path(tmp)
    return {
        "paths": {
            "data_dir": str(root / "data"),
            "db": str(root / "data" / "monitor.db"),
            "lake_raw": str(root / "data" / "lake" / "raw"),
            "lake_norm": str(root / "data" / "lake" / "normalized"),
            "state_dir": str(root / "data" / "state"),
            "cnequity_lake": str(root / "no" / "lake"),
        },
        "collect": {
            "min_interval_seconds": 0.01,
            "backoff_initial_seconds": 1.0,
            "backoff_max_seconds": 4.0,
            "cooldown_file": str(root / "data" / "state" / "cooldown.json"),
            "calendar_cache": str(root / "data" / "state" / "calendar.json"),
        },
    }


def _fake_spot_df():
    import pandas as pd

    return pd.DataFrame({
        "序号": [1, 2, 3, 4, 5],
        "代码": ["600519", "000001", "300123", "688981", "920001"],
        "名称": ["贵州茅台", "平安银行", "创业板X", "科创板X", "北交所X"],
        "今开": [10.0, 11.0, 5.0, 20.0, 3.0],
        "最高": [10.5, 11.5, 5.2, 21.0, 3.1],
        "最低": [9.9, 10.9, 4.9, 19.8, 2.9],
        "最新价": [10.3, 11.2, 4.9, 20.5, 3.0],
        "昨收": [10.0, 11.0, 5.0, 20.0, 3.0],
        "成交量": [100, 200, 300, 400, 500],
        "成交额": [1030.0, 2240.0, 1470.0, 8200.0, 1500.0],
        "涨跌幅": [3.0, 1.8, -2.0, 2.5, 0.0],
        "换手率": [1.1, 0.8, 2.0, 0.5, 3.0],
    })


class FakeLimiter(collect.RateLimiter):
    """不做真实 sleep 的限速器(测试提速)。"""

    def wait(self):
        self._last_call = time.monotonic()


class RateLimiterTest(unittest.TestCase):
    def test_interval_respected(self):
        # 间隔取 0.2s:Windows sleep 粒度 15.6ms,太小的间隔会引入计时噪声
        with tempfile.TemporaryDirectory() as tmp:
            rl = collect.RateLimiter(min_interval=0.2, state_path=Path(tmp) / "c.json")
            t0 = time.monotonic()
            rl.wait()
            rl.wait()
            self.assertGreaterEqual(time.monotonic() - t0, 0.19)

    def test_backoff_exponential_with_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            rl2 = collect.RateLimiter(min_interval=0.0, state_path=Path(tmp) / "c2.json",
                                      backoff_initial=1.0, backoff_max=4.0)
            for expected in (1.0, 2.0, 4.0, 4.0):
                until = rl2.trigger_backoff()
                remaining = until - time.time()
                self.assertGreaterEqual(remaining, expected - 0.05)
                self.assertLessEqual(remaining, expected)

    def test_cooldown_persisted_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "cooldown.json"
            rl1 = collect.RateLimiter(min_interval=0.0, state_path=state)
            rl1.trigger_backoff(hint_seconds=60)
            rl2 = collect.RateLimiter(min_interval=0.0, state_path=state)
            with self.assertRaises(collect.RateLimitTriggered):
                rl2.check_blocked()

    def test_is_rate_limit_error(self):
        class Push2RateLimitError(Exception):
            pass

        self.assertTrue(collect.is_rate_limit_error(Push2RateLimitError("x")))
        self.assertTrue(collect.is_rate_limit_error(ValueError("Push2RateLimitError: too many")))
        self.assertFalse(collect.is_rate_limit_error(ValueError("other")))

    def test_guarded_call_blocks_during_cooldown(self):
        rl = collect.RateLimiter(min_interval=0.0)
        rl.trigger_backoff(hint_seconds=60)
        calls = []

        def fn():
            calls.append(1)
            return "x"

        with self.assertRaises(collect.RateLimitTriggered):
            collect.guarded_call(rl, fn)
        self.assertEqual(calls, [])  # 冷却期内绝不发请求

    def test_guarded_call_translates_rate_limit_error(self):
        rl = collect.RateLimiter(min_interval=0.0)

        class Push2RateLimitError(Exception):
            pass

        def fn():
            raise Push2RateLimitError("sliding window")

        with self.assertRaises(collect.RateLimitTriggered):
            collect.guarded_call(rl, fn)
        self.assertIsNotNone(rl.blocked_until())  # 退避已记录


class CollectDailyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = _temp_cfg(self.tmp.name)
        self.conn = get_conn(Path(self.cfg["paths"]["db"]))
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _limiter(self):
        return FakeLimiter(min_interval=0.0,
                           state_path=Path(self.cfg["collect"]["cooldown_file"]))

    def test_collect_daily_ok_then_idempotent_skip(self):
        calls = []

        def fetcher():
            calls.append(1)
            return _fake_spot_df()

        r1 = collect.collect_daily(self.cfg, self.conn, day=date(2026, 11, 12),
                                   fetcher=fetcher, limiter=self._limiter())
        self.assertEqual(r1["status"], "ok")
        self.assertEqual(r1["breadth"]["up"], 3)
        self.assertEqual(r1["breadth"]["down"], 1)
        self.assertEqual(r1["breadth"]["flat"], 1)
        # 幂等:第二次不请求
        r2 = collect.collect_daily(self.cfg, self.conn, day=date(2026, 11, 12),
                                   fetcher=fetcher, limiter=self._limiter())
        self.assertEqual(r2["status"], "skipped")
        self.assertEqual(len(calls), 1)
        # 落盘文件存在
        self.assertTrue(Path(r1["norm_path"]).exists())
        self.assertTrue((Path(self.cfg["paths"]["lake_raw"]) / "akshare" / "spot"
                         / "dt=20261112" / "part.parquet").exists())

    def test_fetch_hist_sina_fallback(self):
        import pandas as pd

        def fetcher(symbol):
            self.assertEqual(symbol, "sz000003")  # 退市股映射
            return pd.DataFrame({
                "date": ["2000-01-04", "2000-01-05"],
                "open": [5.48, 5.75], "high": [5.85, 5.88], "low": [5.4, 5.6],
                "close": [5.74, 5.68], "volume": [1907300.0, 1934900.0],
                "amount": [10787120.0, 11129076.0],
                "outstanding_share": [None, None], "turnover": [None, None],
            })

        r = collect.fetch_hist_sina(self.cfg, self.conn, "000003",
                                    fetcher=fetcher, limiter=self._limiter())
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["rows"], 2)

    def test_symbol_sina_mapping(self):
        self.assertEqual(collect.symbol_sina("600519"), "sh600519")
        self.assertEqual(collect.symbol_sina("000003"), "sz000003")


class NormalizeTest(unittest.TestCase):
    def test_normalize_em_hist(self):
        import pandas as pd

        df = pd.DataFrame({"日期": ["2024-01-02"], "开盘": [10.0], "收盘": [10.1],
                           "最高": [10.2], "最低": [9.9], "成交量": [100],
                           "成交额": [1010.0], "涨跌幅": [1.0]})
        out = collect.normalize_em_hist(df)
        self.assertEqual(list(out.columns), collect.BAR_COLUMNS)
        self.assertIsNone(out["turnover"].iloc[0])  # 缺列置 None,不造数
        self.assertEqual(float(out["pct_chg"].iloc[0]), 1.0)

    def test_compute_breadth_handles_none(self):
        b = collect.compute_breadth([{"pct_chg": 1.0}, {"pct_chg": -0.5},
                                     {"pct_chg": 0.0}, {"pct_chg": None}])
        self.assertEqual((b["up"], b["down"], b["flat"]), (1, 1, 1))
        self.assertAlmostEqual(b["breadth_ratio"], 0.5)


if __name__ == "__main__":
    unittest.main()
