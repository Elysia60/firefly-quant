"""store.py 单测:账本幂等 / WAL / task_key 稳定性 / Parquet 原子写。零联网。"""

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from astock_monitor import store


def _have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "monitor.db"
        self.conn = store.get_conn(self.db)
        store.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_wal_mode_enabled(self):
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_task_key_order_insensitive(self):
        k1 = store.task_key("akshare", "hist", {"code": "600519", "start": "2024"})
        k2 = store.task_key("akshare", "hist", {"start": "2024", "code": "600519"})
        self.assertEqual(k1, k2)

    def test_manifest_idempotent_upsert(self):
        k = store.task_key("akshare", "hist", {"code": "600519"})
        self.assertIsNone(store.has_task(self.conn, k))
        store.record_task(self.conn, k, "akshare", "hist", {"code": "600519"}, 242, "2024-01-02", "2024-12-31", "x.parquet")
        store.record_task(self.conn, k, "akshare", "hist", {"code": "600519"}, 243, "2024-01-02", "2024-12-31", "x.parquet")
        rows = self.conn.execute("SELECT COUNT(*) FROM collect_manifest").fetchone()[0]
        self.assertEqual(rows, 1)
        rec = store.has_task(self.conn, k)
        self.assertEqual(rec["rows"], 243)

    def test_log_event(self):
        store.log_event(self.conn, "INFO", "test_event", "detail")
        n = self.conn.execute("SELECT COUNT(*) FROM collect_log WHERE event='test_event'").fetchone()[0]
        self.assertEqual(n, 1)

    @unittest.skipUnless(_have("pandas") and _have("pyarrow"), "需要 pandas+pyarrow")
    def test_parquet_atomic_roundtrip(self):
        import pandas as pd

        path = Path(self.tmp.name) / "lake" / "x" / "part.parquet"
        df = pd.DataFrame({"code": ["600519"], "close": [1730.01]})
        store.write_parquet_atomic(df, path)
        self.assertTrue(path.exists())
        self.assertFalse(path.with_suffix(".parquet.tmp").exists())
        back = store.read_parquet(path)
        self.assertEqual(float(back["close"].iloc[0]), 1730.01)


if __name__ == "__main__":
    unittest.main()
