#!/usr/bin/env python3
"""[P8-V0] 元标签实弹评估:元模型能否把 [S2] 的鞭打成本救回来?

流程:事件采样(avoid T+5 判卷日)→ triple-barrier 元标签(YZ 波动挡位)→
purged 5 折 OOS 概率 → V0 过滤策略(p>0.5 才执行 avoid→空仓)。
对照:A 买入持有 / C 全 avoid 空仓 / V0 元过滤。
诚实纪律:OOS 概率(purged+embargo);校准表按 p 十分位;负面结果也归档。
"""
import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import calendar as astock_cal  # noqa: E402
from astock_monitor import metamdl as M  # noqa: E402
from astock_monitor import regime as R  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")

# ---- 指数 OHLC(湖内 index_bars) ----
import pandas as pd  # noqa: E402

files = sorted((lake / "curated" / "index_bars").glob("**/*.parquet"))
idf = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
idf = idf[idf["symbol"] == "000300.SH"].drop_duplicates("trade_date").sort_values("trade_date")
bars = [(d.date() if hasattr(d, "date") else d, float(o), float(h), float(l), float(c))
        for d, o, h, l, c in zip(idf["trade_date"], idf["open"], idf["high"], idf["low"], idf["close"])]
closes = {d: c for d, _, _, _, c in bars}

days = astock_cal.load_calendar_cache(resolve_path(cfg, "paths.state_dir") / "trading_calendar.json")
if days is None:
    days = astock_cal.read_cnequity_calendar(lake)

# ---- 波动分位 + regime ----
idx_rows = [(d, c) for d, _, _, _, c in bars]
volp_list = R.realized_vol_percentile([c for _, c in idx_rows])
volp = {d: p for (d, _), p in zip(idx_rows, volp_list) if p is not None}
bf = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
bdf = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date", "close", "pre_close"])
                 for f in bf), ignore_index=True)
bdaily = cbh(bdf, ma_windows=(250,)) if (cbh := __import__("astock_monitor.sentiment", fromlist=["compute_breadth_history"]).compute_breadth_history) else None
bmap = {d: float(v) for d, v in zip(pd.to_datetime(bdaily["date"]).dt.date, bdaily["above_ma250"])}
regime = R.daily_regime(idx_rows, breadth250=bmap)

# ---- 事件集(账本 avoid 信号)+ 全 verdict(策略模拟需要非 avoid 日) ----
conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
rows = conn.execute(
    "SELECT signal_date, components_json FROM forecast_log"
    " WHERE verdict='avoid_watch' AND window_days=5").fetchall()
verdict = {date.fromisoformat(ds): v for ds, v in conn.execute(
    "SELECT signal_date, verdict FROM forecast_log WHERE window_days=5")}
conn.close()
events = M.build_events([{"signal_date": ds, "components_json": cj} for ds, cj in rows],
                        bars, volp, regime)
events = [e for e in events if e.label is not None]
events.sort(key=lambda e: e.day)
print(f"事件集: {len(events)} 个 avoid 事件,y=1 比例 {sum(e.label for e in events) / len(events):.3f}")

# ---- purged 5 折 OOS 概率 ----
FEAT = ("trend", "momentum", "sentiment", "greed", "vol_pct", "regime", "streak_up")
event_days = [e.day for e in events]
folds = M.purged_folds(event_days, k=5, purge_days=M.HORIZON + M.EMBARGO_DAYS)
oos_p: dict[date, float] = {}
for train_idx, test_idx in folds:
    Xtr = [events[i].x(FEAT) for i in train_idx if events[i].label is not None]
    ytr = [events[i].label for i in train_idx if events[i].label is not None]
    beta = M.irls_logistic(Xtr, ytr, l2=5.0)
    for i in test_idx:
        oos_p[events[i].day] = M.predict_prob([events[i].x(FEAT)], beta)[0]

# ---- 校准表(p 十分位 vs 实际 y=1 率) ----
pairs = sorted((p, e.label) for e in events if (p := oos_p.get(e.day)) is not None)
n = len(pairs)
calib = []
for k in range(10):
    seg = pairs[k * n // 10:(k + 1) * n // 10]
    if seg:
        calib.append({"p_bucket": round(sum(p for p, _ in seg) / len(seg), 3),
                      "actual_y1": round(sum(y for _, y in seg) / len(seg), 3),
                      "n": len(seg)})

# ---- 策略对照 ----
COST_SIDE = float(cfg["backtest"]["cost_round_trip"]) / 2.0
p_of = oos_p
start = min(d for d in closes if d >= date(2015, 1, 5))


def simulate(mode: str) -> dict:
    nav, peak, mdd = 1.0, 1.0, 0.0
    rets, switches, flat_days = [], 0, 0
    pos_prev = 1.0
    for i, d in enumerate(days):
        if d < start or d not in closes or i == 0:
            continue
        prev = days[i - 1]
        if prev not in closes:
            continue
        pos = 1.0
        if mode in ("C", "V0"):
            prior = [x for x in verdict if x < d]
            if prior:
                sd = max(prior)
                if verdict.get(sd) == "avoid_watch":
                    if mode == "C":
                        pos = 0.0
                    else:  # V0:元模型 p>0.5 才执行空仓
                        p = p_of.get(sd)
                        pos = 0.0 if (p is not None and p > 0.5) else 1.0
        if pos != pos_prev:
            switches += 1
            nav *= 1 - COST_SIDE * abs(pos - pos_prev) * 2
        ret = closes[d] / closes[prev] - 1.0
        nav *= 1 + pos * ret
        flat_days += pos == 0
        rets.append(pos * ret)
        pos_prev = pos
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    yrs = len(rets) / 243.0
    ann = nav ** (1 / yrs) - 1 if yrs else 0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sharpe = mean * 243 / (math.sqrt(var) * math.sqrt(243)) if var > 0 else 0
    return {"mode": mode, "nav": round(nav, 4), "ann_ret": round(ann, 4),
            "sharpe": round(sharpe, 3), "max_dd": round(mdd, 4),
            "switches": switches, "flat_days": flat_days}


out = {"n_events": len(events), "y1_rate": round(sum(e.label for e in events) / len(events), 4),
       "calibration": calib,
       "results": [simulate("A"), simulate("C"), simulate("V0")]}
out_path = REPO_ROOT / "results" / "meta_v0.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
print("saved", out_path)
