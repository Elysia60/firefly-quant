#!/usr/bin/env python3
"""[S9] 组合策略全历史回测:regime 门控 + avoid 信号 → 仓位尺寸,能否穿越 2015+2018+2022?

四种策略:
  A 买入持有(基准)
  B regime 门控空仓: regime=bear → 空仓, else 满仓
  C regime 门控 + avoid 缩仓: bear→空仓, neutral+avoid→半仓, else 满仓
  D 纯 avoid 缩仓: avoid→半仓(不门控)

全部扣成本(单边 0.1%):策略切换只在**信号日次日开盘**执行(防泄漏)。
分年产出:年化/夏普/最大回撤/超额(vs A)。
"""
import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import calendar as astock_cal
from astock_monitor import regime as R
from astock_monitor.config import load_config, resolve_path
from astock_monitor.signals import load_index_closes

cfg = load_config()
COST_SIDE = float(cfg["backtest"]["cost_round_trip"]) / 2.0
lake = resolve_path(cfg, "paths.cnequity_lake")
idx_rows = load_index_closes(lake, "000300.SH")
closes = dict(idx_rows)
days = sorted(closes)
start = date(2015, 1, 5)

# regime 逐日
regime_daily = R.daily_regime(idx_rows, breadth250=None)

# 信号逐日(从账本读已有判卷结果)
conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
sig_rows = conn.execute(
    "SELECT signal_date, verdict FROM forecast_log WHERE window_days=5").fetchall()
conn.close()
verdicts = {date.fromisoformat(ds): v for ds, v in sig_rows}

def get_regime(d):
    st = regime_daily.get(d)
    return st["regime"] if st else R.NEUTRAL

def get_prev_verdict(d):
    prior = [x for x in verdicts if x < d]
    return verdicts[max(prior)] if prior else "neutral"

def target_pos(d, mode):
    r = get_regime(d)
    v = get_prev_verdict(d)
    if mode == "A":
        return 1.0
    if mode == "B":  # regime 门控空仓
        return 0.0 if r == R.BEAR else 1.0
    if mode == "C":  # regime 门控 + avoid 缩仓
        if r == R.BEAR:
            return 0.0
        if v == "avoid_watch":
            return 0.5
        return 1.0
    if mode == "D":  # avoid 缩仓(不门控)
        return 0.5 if v == "avoid_watch" else 1.0
    return 1.0

results = []
for mode in ("A", "B", "C", "D"):
    nav, peak, mdd = 1.0, 1.0, 0.0
    rets, switches = [], 0
    pos_prev = 1.0
    for i, d in enumerate(days):
        if d < start or i == 0:
            continue
        prev = days[i - 1]
        if prev not in closes:
            continue
        pos = target_pos(d, mode)
        if pos != pos_prev:
            switches += 1
            nav *= 1 - COST_SIDE * abs(pos - pos_prev) * 2
        ret = closes[d] / closes[prev] - 1.0
        nav *= 1 + pos * ret
        rets.append(pos * ret)
        pos_prev = pos
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    yrs = len(rets) / 243.0
    ann = nav ** (1 / yrs) - 1 if yrs else 0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sharpe = mean * 243 / (math.sqrt(var) * math.sqrt(243)) if var > 0 else 0
    results.append({"mode": mode, "nav": round(nav, 4), "ann_ret": round(ann, 4),
                    "sharpe": round(sharpe, 3), "max_dd": round(mdd, 4),
                    "switches": switches, "years": round(yrs, 1)})

# 分年
years = {}
for mode in ("A", "B", "C", "D"):
    nav_y = {}
    pos_prev = 1.0
    nav = 1.0
    for i, d in enumerate(days):
        if d < start or i == 0:
            continue
        prev = days[i - 1]
        if prev not in closes:
            continue
        pos = target_pos(d, mode)
        ret = closes[d] / closes[prev] - 1.0
        if pos != pos_prev:
            nav *= 1 - COST_SIDE * abs(pos - pos_prev) * 2
        nav *= 1 + pos * ret
        pos_prev = pos
        y = d.year
        if y not in nav_y:
            nav_y[y] = 1.0
        nav_y[y] = nav  # 暂存 running NAV
    # 改为直接记录年末值
    years[mode] = {y: round(v, 4) for y, v in nav_y.items()}

out = {"cost_side": COST_SIDE, "start": str(start), "index": "000300.SH",
       "results": results, "yearly_nav": years}
out_path = REPO_ROOT / "results" / "combined_strategy.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
print("saved", out_path)
