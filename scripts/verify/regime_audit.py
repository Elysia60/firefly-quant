#!/usr/bin/env python3
"""[S1] 最终审判:regime 门控分层事件研究(反方陈述② 的执行)。

方法:avoid T+5 信号按**事前可得** regime 状态(年线滞回+年线宽度+波动否决,三票二,
as-of 取用严格早于信号日)分庭;各庭内做事件研究(对照日=同庭+同星期,污染窗±6天)。
判读(METHODS §3d):
- 各庭 d_obs 均收缩向 0 → 信号只是 regime 代理 → 撤销
- 某庭内 d_obs 仍显著 → 信号有 regime 之外的信息 → 保留并限定适用域
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
from astock_monitor.audit import event_study  # noqa: E402
from astock_monitor.calendar import add_trading_days  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402
from astock_monitor.signals import load_index_closes  # noqa: E402

WINDOW = 5
BULL, NEUTRAL, BEAR = R.BULL, R.NEUTRAL, R.BEAR
NAMES = {BULL: "bull", NEUTRAL: "neutral", BEAR: "bear"}

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
idx_rows = load_index_closes(lake, "000300.SH")
closes = dict(idx_rows)
days = astock_cal.load_calendar_cache(resolve_path(cfg, "collect.calendar_cache"))
if days is None:
    days = astock_cal.read_cnequity_calendar(lake)

# ---- 年线宽度 breadth250(湖内回算,成分≥700 只的完整天) ----
import pandas as pd  # noqa: E402
from astock_monitor.sentiment import compute_breadth_history  # noqa: E402

files = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
bars = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date", "close", "pre_close"])
                  for f in files), ignore_index=True)
daily = compute_breadth_history(bars, ma_windows=(250,))
daily = daily[daily["n"] >= 700]
bmap = {d: float(v) for d, v in zip(pd.to_datetime(daily["date"]).dt.date,
                                    daily["above_ma250"])}

# ---- 逐日 regime(全部事前可算) ----
regime = R.daily_regime(idx_rows, breadth250=bmap)

# ---- 全历史 T+5 前向收益 ----
fwd = {}
for d in days:
    if d not in closes:
        continue
    try:
        tgt = add_trading_days(d, WINDOW, days)
    except ValueError:
        continue
    if tgt in closes:
        fwd[d] = closes[tgt] / closes[d] - 1.0

# ---- 账本:avoid T+5 已判卷信号 ----
conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
rows = conn.execute(
    "SELECT signal_date, fwd_ret FROM forecast_log"
    " WHERE verdict='avoid_watch' AND window_days=? AND judged=1", (WINDOW,)).fetchall()
conn.close()

groups: dict[int, list] = {BULL: [], NEUTRAL: [], BEAR: []}
for ds, fr in rows:
    d = date.fromisoformat(ds)
    st = R.asof(regime, d)
    g = st["regime"] if st else NEUTRAL
    groups[g].append((d, fr))

out = {"window": WINDOW, "breadth250_days": len(bmap),
       "regime_day_counts": {NAMES[g]: sum(1 for d in days if R.asof(regime, d) and R.asof(regime, d)["regime"] == g)
                             for g in (BULL, NEUTRAL, BEAR)},
       "courts": {}}
for g in (BULL, NEUTRAL, BEAR):
    sig_days = {d for d, _ in groups[g]}
    if len(sig_days) < 10:
        out["courts"][NAMES[g]] = {"signal_n": len(sig_days), "skipped": "n<10"}
        continue
    court_days = [d for d in days
                  if R.asof(regime, d) and R.asof(regime, d)["regime"] == g]
    es = event_study(sig_days, fwd, court_days, K=5, min_gap=WINDOW + 1, seed=42)
    out["courts"][NAMES[g]] = {
        "signal_n": es.get("signal_n"), "control_n": es.get("control_n"),
        "mean_signal": round(es["mean_signal"], 5) if "mean_signal" in es else None,
        "mean_control": round(es["mean_control"], 5) if "mean_control" in es else None,
        "d_obs": round(es["d_obs"], 5) if "d_obs" in es else None,
        "p_low": es.get("p_low"), "p_high": es.get("p_high"),
    }

out["verdict_rule"] = ("各庭 d_obs 收缩向 0 → 信号=regime 代理,撤销;"
                       "庭内仍显著 → regime 之外有信息,保留并限定适用域")
out_path = REPO_ROOT / "results" / "regime_audit_verdict.json"
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
print("saved", out_path)
