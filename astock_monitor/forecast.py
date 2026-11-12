"""对账记分牌:信号落盘 → 到期自动判卷(csqaq 理念 1:结论必须可对账)。

窗口语义正本 = METHODS.md §3:T+n = 严格晚于信号日的第 n 个**交易日**
(`add_trading_days`,长假不漂移);fwd_ret = close(T+n)/close(信号日) − 1。

correct 判定口径(数字正本):
- buy_watch:  T+n 收益 > 0 记 1,< 0 记 0
- avoid_watch:T+n 收益 < 0 记 1(躲跌),> 0 记 0
- neutral:    不做方向判(correct=NULL)——[C2] 教训:中性段没有方向主张
判卷只认**到期后的真实数据**;没到期/到期日无数据 → 留待下次判卷,绝不提前猜。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from .calendar import add_trading_days
from .signals import Signal

WINDOWS = (5, 20)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS forecast_log (
            signal_date       TEXT NOT NULL,
            verdict           TEXT NOT NULL,
            score             REAL,
            components_json   TEXT,
            data_quality_json TEXT,
            window_days       INTEGER NOT NULL,
            judged            INTEGER NOT NULL DEFAULT 0,
            judged_date       TEXT,
            close_signal      REAL,
            close_judged      REAL,
            fwd_ret           REAL,
            correct           INTEGER,
            PRIMARY KEY (signal_date, window_days)
        );
        """
    )
    conn.commit()


def record_signal(conn: sqlite3.Connection, signal: Signal,
                  windows: tuple[int, ...] = WINDOWS) -> int:
    """信号落盘:每个判卷窗一行(幂等 upsert,重跑不重复)。"""
    n = 0
    for w in windows:
        conn.execute(
            "INSERT INTO forecast_log"
            " (signal_date, verdict, score, components_json, data_quality_json, window_days)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(signal_date, window_days) DO UPDATE SET"
            " verdict=excluded.verdict, score=excluded.score,"
            " components_json=excluded.components_json, data_quality_json=excluded.data_quality_json",
            (signal.signal_date.isoformat(), signal.verdict, signal.composite,
             json.dumps(signal.components, ensure_ascii=False),
             json.dumps(signal.data_quality.as_dict(), ensure_ascii=False), w),
        )
        n += 1
    conn.commit()
    return n


def judge_due(conn: sqlite3.Connection, closes: dict[date, float],
              trading_days: list[date], today: date | None = None) -> int:
    """对所有未判卷且已到期的信号判卷;返回本次判卷条数。

    closes = {交易日: 收盘};到期日无数据 → 保持未判(不猜)。
    """
    today = today or date.today()
    rows = conn.execute(
        "SELECT signal_date, window_days, verdict FROM forecast_log WHERE judged = 0"
    ).fetchall()
    n = 0
    for ds, w, verdict in rows:
        sig_day = date.fromisoformat(ds)
        if sig_day not in closes:
            continue  # 信号日收盘缺失(数据缺口),判卷无基准,留待
        try:
            tgt = add_trading_days(sig_day, w, trading_days)
        except ValueError:
            continue  # 日历覆盖不足(未来窗),到期再判
        if tgt > today or tgt not in closes:
            continue  # 未到期或到期日无数据——绝不提前猜
        fwd = closes[tgt] / closes[sig_day] - 1.0
        correct: int | None
        if verdict == "buy_watch":
            correct = 1 if fwd > 0 else 0
        elif verdict == "avoid_watch":
            correct = 1 if fwd < 0 else 0
        else:
            correct = None  # neutral 无方向主张
        conn.execute(
            "UPDATE forecast_log SET judged=1, judged_date=?, close_signal=?,"
            " close_judged=?, fwd_ret=?, correct=? WHERE signal_date=? AND window_days=?",
            (today.isoformat(), closes[sig_day], closes[tgt], fwd, correct, ds, w),
        )
        n += 1
    conn.commit()
    return n


def summarize(conn: sqlite3.Connection, cost_rt: float = 0.0020,
              sens_tiers: tuple[float, ...] = (0.001, 0.002, 0.005)) -> dict:
    """按 verdict 汇总判卷结果(统计口径正本 = METHODS.md §3c)。

    - **n_eff(重叠修正)**:逐日滚动信号的 T+n 窗口彼此重叠,有效独立样本按
      保守口径 n_eff = judged // window_days(csqaq L6 同款);small_sample 判据 = n_eff < 30。
    - **成本进账本层**:mean_net = mean_fwd − cost_rt(口径=回测同款回合成本);
      另出三档敏感性(net 在 rt 0.1%/0.2%/0.5% 下是否变号——csqaq [C8] 纪律)。
    """
    out: dict = {"cost_rt": cost_rt, "sens_tiers": list(sens_tiers), "windows": {}}
    for w in WINDOWS:
        rows = conn.execute(
            "SELECT verdict, COUNT(*), SUM(judged), AVG(CASE WHEN judged=1 THEN fwd_ret END),"
            " SUM(correct) FROM forecast_log WHERE window_days=? GROUP BY verdict",
            (w,),
        ).fetchall()
        by_verdict = {}
        for verdict, total, judged, avg_ret, correct_sum in rows:
            judged = judged or 0
            correct_sum = correct_sum or 0
            n_eff = max(1, judged // w) if judged else 0
            mean_net = (avg_ret - cost_rt) if avg_ret is not None else None
            by_verdict[verdict] = {
                "total": total,
                "judged": judged,
                "n_eff": n_eff,
                "mean_fwd_ret": round(avg_ret, 6) if avg_ret is not None else None,
                "mean_net_ret": round(mean_net, 6) if mean_net is not None else None,
                "cost_sensitivity": {str(t): round(avg_ret - t, 6) for t in sens_tiers}
                if avg_ret is not None else None,
                "correct": correct_sum if verdict != "neutral" else None,
                "correct_rate": round(correct_sum / judged, 4) if judged and verdict != "neutral" else None,
                "small_sample": n_eff < 30,
            }
        out["windows"][w] = by_verdict
    return out


def replay(conn: sqlite3.Connection, index_rows: list[tuple[date, float]],
           trading_days: list[date], start: date, end: date,
           windows: tuple[int, ...] = WINDOWS,
           breadth_map: dict[date, float] | None = None) -> dict:
    """历史回放:对 start~end 每个交易日生成信号并判卷(同一条流水线,无特殊通道)。"""
    from .signals import generate_signal

    closes = dict(index_rows)
    days_in_range = [d for d in trading_days if start <= d <= end]
    recorded = 0
    skipped = 0
    for d in days_in_range:
        try:
            sig = generate_signal(index_rows, d, breadth_map=breadth_map)
        except ValueError:
            skipped += 1  # 历史起点不足 21 日窗——预期形态,跳过不中断
            continue
        recorded += record_signal(conn, sig, windows)
    judged = judge_due(conn, closes, trading_days)
    return {"recorded_signals": recorded, "skipped_days": skipped, "judged_rows": judged,
            "summary": summarize(conn)}
