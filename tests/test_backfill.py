"""backfill_cnequity 命令链单测:生成的 cne 命令与实测接口一致(2026-11-12 --plan 干跑验证)。"""

import tempfile
import unittest
from pathlib import Path

from astock_monitor.collect import backfill_cnequity
from tests.test_collect import _temp_cfg


class BackfillCommandTest(unittest.TestCase):
    def test_commands_match_real_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _temp_cfg(tmp)
            r = backfill_cnequity(cfg, ["600519", "000001"], "2024-11-12", "2025-11-12")
        self.assertEqual(r["status"], "prepared")
        self.assertEqual(r["universe_count"], 2)
        create, plan, fetch, delisted = r["commands"]
        self.assertIn("config create", create)
        self.assertIn("--data-root", create)
        self.assertIn("--force", create)
        self.assertIn("backfill daily_bars", plan)
        self.assertIn("--plan", plan)
        self.assertIn("--start 2024-11-12", plan)
        self.assertIn("--symbols 600519.SH,000001.SZ", plan)  # 后缀格式,instruments 实测口径
        self.assertIn("--plan", plan)
        self.assertNotIn("--plan", fetch)
        self.assertIn("--profile delisted", delisted)

    def test_lake_config_path_exists_in_repo(self):
        # 生产仓已由 cne config create 落盘(--plan 干跑实测通过)
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue((repo_root / "configs" / "cnequity.toml").exists())


if __name__ == "__main__":
    unittest.main()
