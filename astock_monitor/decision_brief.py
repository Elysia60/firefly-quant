# -*- coding: utf-8 -*-
"""decision_brief.py — 每日决策简报（2026-11-19 · 萤火决策化第一层）

定位（不变，写给未来的自己）:
  本模块是**融合层**——把已有六个模块的产出拼成一份"今天该怎么做"的简报，
  不产生新信号、不做新预测、不构成投资建议。所有数字可溯源到各自模块。

输入（全部已有产物，零联网）:
  - forecast_log 最新信号: verdict(buy_watch/avoid_watch/neutral) + composite + 分项
  - 判卷汇总(summarize): 各窗口命中率——决策建议的"资历"数字
  - paper_account: 净值/持仓/高水位
  - circuit_breaker state: mode / manual_reset_required / last_drawdown

决策矩阵（保守纪律，方向来自已有结论，仓位纪律来自 portfolio 常数）:
  1. 熔断非 normal 或 manual_reset_required → **禁止新开仓**（熔断优先级最高）
  2. verdict=avoid_watch → **观望/规避**（[S1] 适用域=中性/熊庭）
  3. verdict=buy_watch → **可分批建仓**（单笔≤SINGLE_CAP=35%，bear 庭总仓位×0.3）
  4. verdict=neutral → **持有观察，不加不减**
  每条建议附失效条件（什么情况下这条作废）——不可对账的建议不进简报。

用法（CLI 接线后）:
  python -m astock_monitor.cli decision-brief [--date YYYY-MM-DD]
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

# 纪律常数（与 portfolio.py 同源，不另立数字）
SINGLE_CAP = 0.35
BEAR_SCALE = 0.3
DISCLAIMER = ("本简报为研究系统的自动产出，不构成投资建议；"
              "每条建议附失效条件，失效即作废，不恋战。")


def latest_signal_row(conn: sqlite3.Connection) -> dict | None:
    """读 forecast_log 最新信号日的一行（任一窗口即可，verdict/分项同源）。"""
    try:
        cur = conn.execute(
            "SELECT signal_date, verdict, score, components_json"
            " FROM forecast_log ORDER BY signal_date DESC LIMIT 1")
        row = cur.fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    comps = json.loads(row[3]) if row[3] else {}
    return {"signal_date": row[0], "verdict": row[1], "composite": row[2],
            "components": comps}


def judge_accuracy(conn: sqlite3.Connection) -> dict | None:
    """判卷汇总:各窗口命中/总数（forecast.judge_due 落盘后的统计）。"""
    try:
        cur = conn.execute(
            "SELECT window_days,"
            " SUM(CASE WHEN judged_outcome IS NOT NULL THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN judged_hit = 1 THEN 1 ELSE 0 END)"
            " FROM forecast_log GROUP BY window_days")
        rows = cur.fetchall()
    except sqlite3.Error:
        return None
    out = {}
    for w, total, hit in rows:
        if total:
            out[str(w)] = {"judged": int(total), "hit": int(hit or 0),
                           "rate": round((hit or 0) / total, 3)}
    return out or None


def _paper_metrics(acct: dict, equity_curve: list[dict] | None) -> dict:
    eq = equity_curve[-1]["equity"] if equity_curve else None
    hw = acct.get("high_water")
    dd = (eq / hw - 1.0) if (eq and hw) else None
    return {"cash": acct.get("cash"), "equity": eq, "high_water": hw,
            "drawdown": round(dd, 4) if dd is not None else None,
            "n_positions": len(acct.get("positions", {})),
            "last_day": acct.get("last_day")}


def decide_action(breaker_mode: str, manual_reset: bool,
                  verdict: str | None, drawdown: float | None) -> dict:
    """决策矩阵。纯函数——brief 的心脏，测试打这里。"""
    fail_cond_common = "熔断升级 / 信号 verdict 变更 / 判卷命中率跌破历史下沿"
    if manual_reset or breaker_mode != "normal":
        return {"action": "禁止新开仓",
                "reason": [f"熔断状态={breaker_mode}" + ("；需人工过审复位" if manual_reset else ""),
                           "熔断纪律：只降不升，fail-closed"],
                "invalidated_when": "人工过审 reset 完成且净值回到高水位附近"}
    if verdict == "avoid_watch":
        return {"action": "观望/规避",
                "reason": ["最新信号 avoid_watch（[S1] 适用域=中性/熊庭）",
                           "规避清单内标的不做逆势抄底"],
                "invalidated_when": fail_cond_common + "；或信号翻多且宽度修复"}
    if verdict == "buy_watch":
        return {"action": "可分批建仓",
                "reason": [f"最新信号 buy_watch（composite 见信号区）",
                           f"纪律:单笔≤{SINGLE_CAP:.0%}，买前过 limits.check_order 涨跌停校验"],
                "invalidated_when": fail_cond_common}
    if verdict == "neutral":
        return {"action": "持有观察，不加不减",
                "reason": ["最新信号 neutral——三票二未给出方向"],
                "invalidated_when": fail_cond_common}
    return {"action": "观望（信号缺失）",
            "reason": ["forecast_log 无可用信号——先跑 cli signal"],
            "invalidated_when": "信号生成后自动更新"}


def build_brief(latest: dict | None, judge: dict | None,
                acct: dict, breaker: dict,
                equity_curve: list[dict] | None = None,
                day: str | None = None) -> dict:
    """纯融合:五个已有产物的 dict → 简报 dict。不读盘不联网。"""
    paper = _paper_metrics(acct, equity_curve)
    action = decide_action(breaker.get("mode", "normal"),
                           bool(breaker.get("manual_reset_required")),
                           (latest or {}).get("verdict"), paper["drawdown"])
    return {
        "day": day or date.today().isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": latest,
        "judge": judge,
        "paper": paper,
        "breaker": {"mode": breaker.get("mode"),
                    "manual_reset_required": bool(breaker.get("manual_reset_required")),
                    "last_drawdown": breaker.get("last_drawdown")},
        "action": action,
        "disclaimer": DISCLAIMER,
    }


def render(brief: dict) -> str:
    """简报 dict → markdown（人类可读，主动消息同款朴素风）。"""
    s = brief.get("signal") or {}
    j = brief.get("judge") or {}
    p = brief.get("paper") or {}
    cb = brief.get("breaker") or {}
    a = brief.get("action") or {}
    lines: list[str] = []
    lines.append(f"# 萤火每日决策简报 {brief.get('day')}")
    lines.append(f"> 生成于 {brief.get('generated_at')} ｜ {brief.get('disclaimer')}")
    lines.append("")
    lines.append("## 今日动作")
    lines.append(f"**{a.get('action')}**")
    for r in a.get("reason", []):
        lines.append(f"- 依据: {r}")
    lines.append(f"- 失效条件: {a.get('invalidated_when')}")
    lines.append("")
    lines.append("## 信号区（最新）")
    if s:
        comp = s.get("composite")
        comp_s = f"{comp:.2f}" if isinstance(comp, (int, float)) else comp
        lines.append(f"- 信号日: {s.get('signal_date')} ｜ verdict: **{s.get('verdict')}** "
                     f"｜ composite: {comp_s}")
        comps = s.get("components") or {}
        if comps:
            lines.append(f"- 分项: breadth={comps.get('breadth')} "
                         f"sentiment={comps.get('sentiment')} gap_days={comps.get('gap_days')}")
    else:
        lines.append("- 无信号（先跑 `cli signal`）")
    lines.append("")
    lines.append("## 判卷区（资历）")
    if j:
        for w, v in sorted(j.items(), key=lambda kv: kv[0]):
            lines.append(f"- T+{w}: 命中 {v['hit']}/{v['judged']} = {v['rate']:.1%}")
    else:
        lines.append("- 尚无到期判卷记录")
    lines.append("")
    lines.append("## 账户与熔断")
    lines.append(f"- 纸面净值: {p.get('equity')}（现金 {p.get('cash')}，持仓 {p.get('n_positions')} 只）")
    lines.append(f"- 高水位回撤: {p.get('drawdown') if p.get('drawdown') is not None else '无数据'}"
                 f" ｜ 熔断 mode: **{cb.get('mode')}**"
                 + ("（需人工复位）" if cb.get("manual_reset_required") else ""))
    lines.append("")
    lines.append("*失效即作废，不恋战。*")
    return "\n".join(lines) + "\n"
