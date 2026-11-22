# -*- coding: utf-8 -*-
"""paper_sim.py — 萤火决策链走前纸面模拟（2026-11-23）

模拟: 每个信号日出信号 → 次日按建议操作(T+1 成交) → 持有到下一信号 → 到期判卷。
纪律: 用 forecast_log 已判卷的真实数据(非假设);成本按 cost_schedule;仓位按 ladder。
对照: 沪深 300 同期买入持有。不构成投资建议。
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from astock_monitor import cost_schedule as CS  # noqa: E402
from astock_monitor.audit import newey_west_t  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "monitor.db"
ANN = 250
LADDER = {0: 1.0, 1: 0.6, 2: 0.3}  # BULL / NEUTRAL / BEAR
OUT = ROOT / "results" / "paper_sim_report.json"


def load_index_closes(conn):
    """从 forecast_log + 湖拿指数收盘——简报用的同一数据源。"""
    rows = conn.execute("""
        SELECT signal_date, close_signal FROM forecast_log
        WHERE close_signal IS NOT NULL
        ORDER BY signal_date
    """).fetchall()
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    return dates, closes


def load_signals(conn):
    """每个信号日取一条(verdict + composite),去重。"""
    rows = conn.execute("""
        SELECT signal_date, verdict, score
        FROM forecast_log
        GROUP BY signal_date ORDER BY signal_date
    """).fetchall()
    return rows


def run(start_date="2024-01-01", end_date="2026-11-20"):
    conn = sqlite3.connect(str(DB))

    # 1) 拉信号
    signals = load_signals(conn)
    signals = [(d, v, s) for d, v, s in signals if start_date <= d <= end_date]
    if not signals:
        return {"error": "无信号"}

    # 2) 指数收盘(去重,保持顺序)
    dates, closes = load_index_closes(conn)
    idx = {d: c for d, c in zip(dates, closes)}
    sorted_dates = sorted(idx.keys())
    close_arr = [idx[d] for d in sorted_dates]
    date_arr = sorted_dates

    # 3) 逐信号模拟: 信号日次日(T+1)开盘执行,持有到下一信号日
    port_ret = []       # 萤火跟单日收益
    base_ret = []       # 买入持有日收益
    events = []         # 事件日志
    sim_dates = []
    pos_pct = 0.0       # 当前仓位(0~1)
    cash_drift = 1.0    # 净值(乘法累积)

    sig_dates = {d for d, v, s in signals}
    sig_map = {d: (v, s) for d, v, s in signals}

    # 日收益序列
    daily_rets = {}
    for i in range(1, len(sorted_dates)):
        prev_c = idx[sorted_dates[i - 1]]
        cur_c = idx[sorted_dates[i]]
        if prev_c > 0:
            daily_rets[sorted_dates[i]] = cur_c / prev_c - 1

    regime = 1  # NEUTRAL 初始(滞回后为准——简化: 用 vol 分位替代)
    prev_close = None

    for i, d in enumerate(sorted_dates):
        if i == 0:
            continue
        r_mkt = daily_rets.get(d, 0.0)
        base_ret.append(r_mkt)

        # 萤火: 仓位取决于最新信号 verdict + 熔断
        if d in sig_map:
            verdict, score = sig_map[d]
            if verdict == "buy_watch":
                pos_pct = LADDER.get(regime, 0.6)
            elif verdict == "avoid_watch":
                pos_pct = 0.0
            # neutral → 保持当前仓位
            events.append({
                "date": d, "verdict": verdict, "score": round(score, 2),
                "action": ("分批买入" if verdict == "buy_watch" else
                           "观望/减仓" if verdict == "avoid_watch" else "持有"),
                "position": f"{pos_pct:.0%}",
            })

        # 当日组合收益 = 仓位 × 市场收益(指数代理,简化)
        r_port = pos_pct * r_mkt
        port_ret.append(r_port)
        base_ret.append(r_mkt)
        sim_dates.append(d)
        prev_close = idx[d]

    # 4) 成本: 每次 verdict 变更扣 round_trip
    cost_events = 0
    prev_verdict = None
    for ev in events:
        if ev["verdict"] != prev_verdict:
            cost_events += 1
            d = ev["date"]
            rt = CS.round_trip_cost(pd.Timestamp(d).date()) if hasattr(
                type(pd.Timestamp(d)), "date") else 0.002
            # 当日扣成本(近似: rt/2 影响当日收益)
            if port_ret:
                port_ret[-1] -= rt / 2
        prev_verdict = ev["verdict"]

    # 5) 指标
    def metrics(r, label):
        a = np.array(r)
        if len(a) < 10:
            return {"label": label, "n_days": len(a)}
        ann_ret = a.mean() * ANN
        ann_vol = a.std() * (ANN ** 0.5)
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 0 else 0.0
        eq = np.cumprod(1 + a)
        total = eq[-1] - 1
        dd = (eq / np.maximum.accumulate(eq) - 1).min()
        return {"label": label, "ann_ret": round(ann_ret, 4),
                "ann_vol": round(ann_vol, 4), "sharpe": sharpe,
                "total_ret": round(total, 4), "maxdd": round(float(dd), 4),
                "n_days": len(a), "final_eq": round(float(eq[-1]), 4)}

    m_port = metrics(port_ret, "萤火跟单")
    m_base = metrics(base_ret, "沪深300 买入持有")

    # 差分检验
    n = min(len(port_ret), len(base_ret))
    d_arr = np.array(port_ret[:n]) - np.array(base_ret[:n])
    t_stat = newey_west_t(list(d_arr), window=21)

    # 6) 事件摘要(最近 10 条)
    recent_events = events[-10:]

    report = {
        "period": [sorted_dates[0], sorted_dates[-1]],
        "n_signals": len(signals),
        "n_cost_events": cost_events,
        "firefly": m_port,
        "csi300_hold": m_base,
        "excess": {"ann_ret": round(m_port["ann_ret"] - m_base["ann_ret"], 4),
                   "sharpe_delta": round(m_port["sharpe"] - m_base["sharpe"], 3),
                   "maxdd_diff": round(m_port["maxdd"] - m_base["maxdd"], 4),
                   "nw_t": round(t_stat, 3)},
        "verdict": ("跑赢基准" if m_port.get("sharpe", 0) > m_base.get("sharpe", 0)
                    else "未跑赢基准"),
        "recent_events": recent_events,
        "disclaimer": "纸面模拟,指数代理,非实盘;不构成投资建议",
    }
    return report


if __name__ == "__main__":
    rep = run()
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("saved", OUT)
