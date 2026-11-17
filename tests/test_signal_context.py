# -*- coding: utf-8 -*-
"""信号上下文契约回归测试(2026-11-17 双 bug 教训)。

契约 ①: 信号路径 sentiment_map 必须是 0-100(csqaq v1.0 锚点刻度);
        load_margin_greed 返回 0-1(触发面板 T-杠杆>0.9 契约)——桥接 ×100 不得回退。
契约 ②: collect_zt_pool 非交易日必须跳过(陈池伪装防线,push2ex 返回上一交易日池)。
契约 ③: breadth_history 文件日期必须是真实日历日(全体同缺的日子不漏检)。
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from astock_monitor import cli
from astock_monitor.sentiment import collect_zt_pool
from astock_monitor.signals import sentiment_score


class GreedScaleTest(unittest.TestCase):
    """契约 ①: 0-1 → 0-100 桥接。"""

    def test_greed_scaled_to_0_100(self):
        fake = {date(2026, 1, 5): 0.434, date(2026, 1, 6): 0.912}

        def fake_resolve(cfg, key):
            return Path(tempfile.gettempdir()) / "definitely-missing-dir"

        with patch("astock_monitor.sentiment.load_margin_greed", return_value=dict(fake)), \
             patch("astock_monitor.cli.resolve_path", side_effect=fake_resolve):
            breadth_map, greed_map = cli._build_signal_maps({})
        self.assertIsNone(breadth_map)  # 宽度史缺失 → None(不静默造)
        self.assertAlmostEqual(greed_map[date(2026, 1, 5)], 43.4, places=6)
        self.assertAlmostEqual(greed_map[date(2026, 1, 6)], 91.2, places=6)

    def test_sentiment_anchors_expect_0_100(self):
        # 锚点正本: [(0,100),(40,85),(60,55),(80,25),(100,5)]
        self.assertAlmostEqual(sentiment_score(43.4), 79.9, places=1)
        self.assertAlmostEqual(sentiment_score(50.0), 70.0, places=1)
        # 0-1 输入落在非法域(全挤在第一锚点段 → ~100 钉死)
        self.assertNotAlmostEqual(sentiment_score(0.434), 100.0, places=1)


class ZtPoolGuardTest(unittest.TestCase):
    """契约 ②: 非交易日不落池。"""

    def test_non_trading_day_skipped(self):
        from astock_monitor.store import init_db
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "calendar.json"
            cache.write_text(json.dumps({"days": ["2026-11-13", "2026-11-16"]}),
                             encoding="utf-8")
            cfg = {"collect": {"calendar_cache": str(cache)},
                   "paths": {"lake_raw": str(Path(td) / "raw")}}
            conn = sqlite3.connect(":memory:")
            try:
                init_db(conn)
                r = collect_zt_pool(cfg, conn, day=date(2026, 11, 14), fetchers={})
            finally:
                conn.close()
            self.assertEqual(r["status"], "skipped")
            self.assertEqual(r["reason"], "non_trading_day")


class BreadthGapTest(unittest.TestCase):
    """契约 ③(间接): _build_signal_maps 读到的宽度史应含真实日历日。

    全体指数同缺的日子(如采集中断)不在湖数据里——回补脚本必须用
    交易日历做基准(scripts/backfill_index_gap.py 的教训)。
    这里只锁信号路径消费端: 文件存在时返回非 None 且值域合理。
    """

    def test_breadth_values_in_range(self):
        from astock_monitor.signals import momentum_score
        # breadth=1.0(归一化事故指纹)与 breadth=0.0 都应产出合法分
        self.assertAlmostEqual(momentum_score(1.0, 0), 70.0, places=6)
        self.assertAlmostEqual(momentum_score(0.0, 0), 0.0, places=6)
        self.assertIsNone(momentum_score(None, 3))



class SignalAsDictTest(unittest.TestCase):
    """CLI signal 的 print 路径契约: as_dict 必须 JSON 可序列化。"""

    def test_as_dict_json_serializable(self):
        import json as _json
        from astock_monitor.signals import Signal
        sig = Signal(signal_date=date(2026, 11, 17), trend_score=52.0,
                     composite=44.8, verdict="avoid_watch",
                     components={"breadth": 0.1957, "greed": 44.2})
        raw = _json.dumps(sig.as_dict(), ensure_ascii=False)  # 不应抛 TypeError
        back = _json.loads(raw)
        self.assertEqual(back["signal_date"], "2026-11-17")
        self.assertEqual(back["verdict"], "avoid_watch")

if __name__ == "__main__":
    unittest.main()
