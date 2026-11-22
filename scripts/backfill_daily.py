#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_daily.py — CNEquity TDX 日增量回填（2026-11-22 · 断链 10 天事故的根因自动化）

根因: 因子面板的 bars 来自 CNEquity TDX 湖,而 cne backfill 不在任何自动化里——
11-12 后没人跑,断链 10 天才被决策简报的新鲜度行暴露。本脚本把它接进 run_daily。

行为: hs800 宇宙 × 最近 9 个日历日(≥5 个交易日) 增量回填;幂等(已回填的分区
cne 自行去重)。TDX 源不经东财,与 EM 限流完全解耦。fail-soft: 失败 rc=1,
不阻塞流水线其余步骤(与 collect 解耦同纪律)。

用法: python scripts/backfill_daily.py [--days 9]
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CNE = Path(r"C:\Users\14676\.workbuddy\binaries\python\envs\default\Scripts\cne.exe")
CODES_FILE = REPO_ROOT / "data" / "state" / "hs800_codes.txt"
LAKE_CFG = REPO_ROOT / "configs" / "cnequity.toml"


def symbol_cne(code: str) -> str:
    code = code.strip()
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    return f"{code}.BJ"


def main() -> int:
    days = 9
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if not CNE.exists():
        print(json.dumps({"status": "cne_not_found", "path": str(CNE)}, ensure_ascii=False))
        return 1
    codes = [l.strip() for l in CODES_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    syms = ",".join(symbol_cne(c) for c in codes)
    start = (date.today() - timedelta(days=days)).isoformat()
    end = date.today().isoformat()
    proc = subprocess.run(
        [str(CNE), "backfill", "daily_bars", "--config", str(LAKE_CFG),
         "--start", start, "--end", end, "--symbols", syms],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800)
    ok = proc.returncode == 0
    summary = {"status": "ok" if ok else "failed", "window": [start, end],
               "universe": len(codes), "rc": proc.returncode,
               "stdout_tail": proc.stdout[-400:], "stderr_tail": proc.stderr[-400:]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
