#!/usr/bin/env python3
"""[S2] 门控策略模拟:把 [S1] 注册结论变成可对账的净值曲线。

四组对照(全部 T-1 收盘决策、T 日开盘执行、扣单边成本):
  A. buy_hold      基准:始终满仓
  B. avoid_ungated avoid 信号日次日空仓(不门控)
  C. avoid_gated   [S1] 适用域门控:仅 neutral/bear 庭的 avoid 信号次日空仓
  D. avoid_bull_only 对照组(应最差):仅 bull 庭的 avoid 信号次日空仓

诚实边界:指数不可直接交易,成本按 ETF 单边 0.1% 近似(config.cost_round_trip/2);
信号来自注册流水线(forecast_log),regime 门控事前可算——无未来函数;逐日无重仓杠杆。
产出:各组年化/夏普/最大回撤/空仓天数/换手次数 → results/gated_strategy_sim.json
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import calendar as astock_cal  # noqa: E402
from astock_monitor import regime as R  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402
from astock_monitor.signals import load_index_closes  # noqa: E402
from astock_monitor.sentiment import compute_breadth_history  # noqa: E402

cfg = load_config()
COST_SIDE = float(cfg["backtest"]["cost_round_trip"]) / 2.0  # 单边
lake = resolve_path(cfg, "paths.cnequity_lake")
idx_rows = load_index_closes(lake, "000300.SH")
closes = dict(idx_rows)
days = astock_cal.load_calendar_cache(resolve_path(cfg, "collect.calendar_cache"))
if days is None:
    days = astock_cal.read_cnequity_calendar(lake)

# regime 状态(as-of 严格早于信号日)
import pandas as pd  # noqa: E402
from astock_monitor.sentiment import compute_breadth_history as cbh  # noqa: E402

files = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
bars = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date", "close", "pre_close"])
                  for f in files), ignore_index=True)
daily = cbh(bars, ma_windows=(250,))
daily = daily[daily["n"] >= 700]
bmap = {d: float(v) for d, v in zip(pd.to_datetime(daily["date"]).dt.date, daily["above_ma250"])}
regime = R.daily_regime(idx_rows, breadth250=bmap)

# 信号:账本中每日 verdict(T 日信号=T-1 收盘可知)
conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
sig_rows = conn.execute("SELECT signal_date, verdict FROM forecast_log WHERE window_days=5").fetchall()
conn.close()
verdict = {date.fromisoformat(ds): v for ds, v in sig_rows}


def regime_of(d: date) -> int:
    st = R.asof(regime, d)
    return st["regime"] if st else R.NEUTRAL


def flat_next(day: date, mode: str) -> bool:
    """T 日是否空仓:由 T-1 信号(及门控/去抖/纯 regime)决定。"""
    prior = [d for d in verdict if d < day]
    if not prior:
        return False
    sd = max(prior)
    if mode == "F":
        # 纯 regime 粒度:前一日 as-of 状态=bear 才空仓(门控自带 5 日去抖)
        return regime_of(sd) == R.BEAR
    if verdict.get(sd) != "avoid_watch":
        return False
    if mode == "B":
        return True
    g = regime_of(sd)  # 信号日收盘后的 regime 状态,供次日使用
    if mode == "C":
        return g in (R.NEUTRAL, R.BEAR)
    if mode == "D":
        return g == R.BULL
    if mode == "E":
        # csqaq 教训#2 药方:avoid 需连续 5 个信号日持久 + 门控在适用域,才空仓
        if g not in (R.NEUTRAL, R.BEAR):
            return False
        run, d = 0, sd
        while d in verdict and verdict[d] == "avoid_watch" and run < 5:
            run += 1
            earlier = [x for x in verdict if x < d]
            if not earlier:
                break
            d = max(earlier)
        return run >= 5
    return False


def target_pos(day: date, mode: str) -> float:
    """T 日目标仓位(0/0.5/1),由 T-1 信号+门控决定。[S2] 反方②:半仓变体。"""
    if mode in ('H', 'I') and flat_next(day, 'C' if mode == 'H' else 'E'):
        return 0.5   # 门控(或门控+去抖)avoid → 半仓而非空仓
    return 0.0 if flat_next(day, 'C' if mode == 'H' else 'E') else 1.0


SIM_START = date(2015, 1, 5)


def simulate(mode: str) -> dict:
    nav, peak, mdd = 1.0, 1.0, 0.0
    rets, switches, flat_days = [], 0, 0
    pos_prev = 1.0
    start = min(d for d in closes if d >= SIM_START)
    for i, d in enumerate(days):
        if d < start or d not in closes:
            continue
        prev = days[days.index(d) - 1] if days.index(d) > 0 else None
        if prev is None or prev not in closes:
            continue
        pos = target_pos(d, mode) if mode in ('H', 'I') else (0.0 if flat_next(d, mode) else 1.0)
        if pos != pos_prev:
            switches += 1
            nav *= (1 - COST_SIDE * abs(pos - pos_prev) * 2)  # 一开一平两次单边
        ret = closes[d] / closes[prev] - 1.0
        nav *= 1 + pos * ret
        if pos == 0:
            flat_days += 1
        rets.append(pos * ret)
        pos_prev = pos
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    years = len(rets) / 243.0
    ann = (nav ** (1 / years) - 1) if years > 0 else 0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sharpe = (mean * 243) / (math.sqrt(var) * math.sqrt(243)) if var > 0 else 0
    return {"mode": mode, "nav": round(nav, 4), "ann_ret": round(ann, 4),
            "sharpe": round(sharpe, 3), "max_dd": round(mdd, 4),
            "switches": switches, "flat_days": flat_days, "days": len(rets)}


import math  # noqa: E402
import os as _os

_modes_env = _os.environ.get("SIM_MODES", "A,B,C,D,E,F,H,I")
_start_env = _os.environ.get("SIM_START")
if _start_env:
    _y, _m, _dd = (int(x) for x in _start_env.split("-"))
    SIM_START = date(_y, _m, _dd)

out = {"cost_side": COST_SIDE, "start": str(SIM_START), "index": "000300.SH",
       "results": [simulate(m) for m in _modes_env.split(",")]}
out_path = REPO_ROOT / "results" / "gated_strategy_sim.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
print("saved", out_path)