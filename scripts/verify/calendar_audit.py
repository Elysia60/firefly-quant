#!/usr/bin/env python3
"""[S3] 候选审计:春节效应 + 月末效应(侦察清单定案,2026-11-13)。

春节:事件日=节前最后交易日(交易日历中 1~3 月的 ≥3 天缺口自动识别,零外部数据);
假设=节后 5 日收益为正(Lunar January Effect, APJFS 2023)。对照=星期匹配+避开所有
春节窗口 ±15 天(置换检验, min_gap=15 自动实现)。n≈12,小样本如实标注。
月末:事件日=每月倒数第 2 个交易日;假设=月末效应(TOM)。min_gap=3。

通用纪律(侦察清单):对照星期匹配;排除窗口重叠;负面结果也归档。
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import calendar as astock_cal  # noqa: E402
from astock_monitor.audit import event_study  # noqa: E402
from astock_monitor.calendar import add_trading_days  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402
from astock_monitor.signals import load_index_closes  # noqa: E402

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
idx_rows = load_index_closes(lake, "000300.SH")
closes = dict(idx_rows)
days = astock_cal.load_calendar_cache(resolve_path(cfg, "collect.calendar_cache"))
if days is None:
    days = astock_cal.read_cnequity_calendar(lake)

fwd5 = {}
for d in days:
    if d not in closes:
        continue
    try:
        tgt = add_trading_days(d, 5, days)
    except ValueError:
        continue
    if tgt in closes:
        fwd5[d] = closes[tgt] / closes[d] - 1.0

# ---- 春节 T0 识别:交易日历 1~3 月的 ≥5 天缺口 = 法定长假(周末缺口=3 天,≥5 干净分离) ----
spring_festival = []
for i in range(len(days) - 1):
    gap = (days[i + 1] - days[i]).days
    if gap >= 5 and 1 <= days[i].month <= 3 and days[i].year >= 2015:
        spring_festival.append(days[i])

# ---- 月末倒数第 2 个交易日 ----
month_last2 = []
for i in range(len(days) - 1):
    if days[i + 1].month != days[i].month and i >= 1:
        month_last2.append(days[i - 1])  # 倒数第 2 个交易日
month_last2 = sorted(set(d for d in month_last2 if d >= date(2015, 1, 5)))

results = {"spring_festival": {"event_days": [str(d) for d in spring_festival], "n": len(spring_festival)},
           "month_end": {"n": len(month_last2)}}

es_sf = event_study(set(spring_festival), fwd5, days, K=5, min_gap=15, B=2000, seed=42)
results["spring_festival"]["audit"] = {k: (round(v, 5) if isinstance(v, float) else v)
                                       for k, v in es_sf.items()}
es_me = event_study(set(month_last2), fwd5, days, K=5, min_gap=3, B=2000, seed=42)
results["month_end"]["audit"] = {k: (round(v, 5) if isinstance(v, float) else v)
                                 for k, v in es_me.items()}

out_path = REPO_ROOT / "results" / "calendar_audit_verdict.json"
out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
print("saved", out_path)
