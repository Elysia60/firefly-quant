# -*- coding: utf-8 -*-
"""proof_run.py — 萤火全链路实弹证明（2026-11-23 · 逐环节计时 + 工件核验）

跑的即是 run_daily.bat 的同款步骤（collect→signal→judge→summary→paper-mark→
candidates→decision-brief），外加 doctor。每步计时、每步工件核验存在性。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STEPS = [
    ("doctor", ["python", "-m", "astock_monitor.cli", "doctor"], []),
    ("collect-daily", ["python", "-m", "astock_monitor.cli", "collect-daily"], []),
    ("signal", ["python", "-m", "astock_monitor.cli", "signal",
                "--require-session", "--date", "2026-11-20"], ["forecast_log"]),
    ("forecast-judge", ["python", "-m", "astock_monitor.cli", "forecast-judge"], []),
    ("forecast-summary", ["python", "-m", "astock_monitor.cli", "forecast-summary",
                          "--out", "data/state/scoreboard_daily.json"], ["scoreboard"]),
    ("paper-mark", ["python", "-m", "astock_monitor.cli", "paper-mark"], ["paper_account"]),
    ("candidates", ["python", "-m", "astock_monitor.cli", "candidates"], ["candidates_json"]),
    ("decision-brief", ["python", "-m", "astock_monitor.cli", "decision-brief"], ["brief_md"]),
]
ARTIFACTS = {
    "forecast_log": ROOT / "data" / "monitor.db",  # forecast_log 表在 monitor.db
    "scoreboard": ROOT / "data" / "state" / "scoreboard_daily.json",
    "paper_account": ROOT / "data" / "state" / "paper_account.json",
    "candidates_json": ROOT / "data" / "state" / "candidates_latest.json",
    "brief_md": ROOT / "results" / "decision_brief" / "2026-11-23.md",
}

results = []
t_all = time.time()
for name, cmd, arts in STEPS:
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT), timeout=900)
    dt = time.time() - t0
    missing = [a for a in arts if not ARTIFACTS[a].exists()]
    results.append({"step": name, "rc": r.returncode, "seconds": round(dt, 1),
                    "artifacts_missing": missing,
                    "tail": (r.stdout or "")[-150:]})
    protective = name == "collect-daily" and "RateLimit" in (r.stderr or "") + (r.stdout or "")
    if protective:
        flag = "🛡"
    elif r.returncode == 0 and not missing:
        flag = "✅"
    elif r.returncode == 0:
        flag = "⚠"
    else:
        flag = "❌"
    print(f"{flag} {name:<18} rc={r.returncode} {dt:6.1f}s "
          f"{'工件:' + ','.join(arts) if arts else '(过程性)'}"
          + (f" 缺失:{missing}" if missing else ""))

total = time.time() - t_all
print(f"\n总耗时: {total:.1f}s")
ok = all(r["rc"] == 0 and not r["artifacts_missing"] for r in results)
print("全链路:", "✅ 全通" if ok else "⚠ 有环节异常(明细如上)")
Path(ROOT / "results" / "proof_run_2026-11-23.json").write_text(
    json.dumps({"total_seconds": round(total, 1), "steps": results,
                "all_ok": ok}, ensure_ascii=False, indent=1), encoding="utf-8")
print("证据落盘 results/proof_run_2026-11-23.json")
