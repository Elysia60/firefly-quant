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

from .position import suggested_size

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


def compute_market_context(index_closes: list | None,
                           signal_date: str | None,
                           bars_last_date: str | None = None) -> dict | None:
    """市场语境:regime 三票二(官方 PIT 取用口) + 年化已实现波动。

    index_closes: [(date, close), ...](与 cli load_index_closes 同源);
    regime 走 R.daily_regime + R.asof(严格早于信号日,防泄漏)。
    """
    if not index_closes:
        return None
    from . import regime as R
    reg = R.daily_regime(index_closes)
    row = None
    if signal_date:
        try:
            row = R.asof(reg, date.fromisoformat(signal_date))
        except ValueError:
            row = None
    if row is None:
        row = R.asof(reg, date.max)
    closes = [float(c) for _, c in index_closes]
    vol_pct = None
    if len(closes) >= 21:
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - 20, len(closes))]
        mean = sum(rets) / len(rets)
        std = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
        vol_pct = round(std * (250 ** 0.5) * 100, 2)
    bars_age = None
    if bars_last_date:
        try:
            bars_age = (date.today() - date.fromisoformat(bars_last_date)).days
        except ValueError:
            bars_age = None
    return {"regime_state": (row or {}).get("regime"),
            "regime_detail": {k: row.get(k) for k in ("gate", "breadth250", "vol_pct")} if row else None,
            "realized_vol_pct": vol_pct,
            "bars_last_date": bars_last_date, "bars_age_days": bars_age}


def _judge_win_rate(judge: dict | None) -> float | None:
    """判卷区 → 总命中率(跨窗口平均,预注册口径);无数据 None(诚实降级)。"""
    if not judge:
        return None
    rates = [v["rate"] for v in judge.values() if v.get("judged")]
    return round(sum(rates) / len(rates), 3) if rates else None


def build_brief(latest: dict | None, judge: dict | None,
                acct: dict, breaker: dict,
                equity_curve: list[dict] | None = None,
                day: str | None = None,
                index_closes: list | None = None,
                candidates: dict | None = None,
                bars_last_date: str | None = None) -> dict:
    """纯融合:已有产物 dict(+可选指数收盘) → 简报 dict。不读盘不联网。"""
    paper = _paper_metrics(acct, equity_curve)
    action = decide_action(breaker.get("mode", "normal"),
                           bool(breaker.get("manual_reset_required")),
                           (latest or {}).get("verdict"), paper["drawdown"])
    ctx = compute_market_context(index_closes, (latest or {}).get("signal_date"),
                           bars_last_date=bars_last_date)
    win_rate = _judge_win_rate(judge)
    pos = suggested_size(ctx["realized_vol_pct"] if ctx else None,
                         win_rate, None,
                         ctx["regime_state"] if ctx else None,
                         breaker_mode=breaker.get("mode", "normal"),
                         manual_reset=bool(breaker.get("manual_reset_required")))
    return {
        "day": day or date.today().isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": latest,
        "judge": judge,
        "paper": paper,
        "breaker": {"mode": breaker.get("mode"),
                    "manual_reset_required": bool(breaker.get("manual_reset_required")),
                    "last_drawdown": breaker.get("last_drawdown")},
        "market_ctx": ctx,
        "position": pos,
        "candidates": candidates,
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
    ctx = brief.get("market_ctx")
    pos = brief.get("position") or {}
    lines.append("## 市场语境与仓位")
    if ctx:
        regime_names = {0: "BULL", 1: "NEUTRAL", 2: "BEAR"}
        # vol 危险区警示(2026-11-22 学习报告预注册,11-23 实施):
        # 实证=美股 11 月案例,vol 分位先行于价格危机约 5 周
        _vp = (ctx.get("regime_detail") or {}).get("vol_pct")
        if _vp is not None and _vp > 0.9:
            lines.append(f"- ⚠ 波动危险区: 20 日波动处于 500 日分位 {_vp:.0%}"
                         f"——该区域历史先行于价格危机,收紧一切新开仓")
        bars_age = ctx.get("bars_age_days")
        if bars_age is not None and bars_age > 3:
            lines.append(f"- ⚠ 个股数据截止 {ctx.get('bars_last_date')}"
                            f"（{bars_age} 天前——collect 断链/冷却中,候选名单已停更,按陈旧数据看待）")

        rs = ctx.get("regime_state")
        lines.append(f"- regime 三票二: **{regime_names.get(rs, '数据不足')}**"
                     f"（gate={ctx.get('regime_detail', {}).get('gate')} "
                     f"vol分位={ctx.get('regime_detail', {}).get('vol_pct')}）")
        lines.append(f"- 年化已实现波动: {ctx.get('realized_vol_pct')}%")
    else:
        lines.append("- 市场语境缺失（无指数收盘数据）")
    if pos.get("size") is not None:
        bounds = pos.get("bounds") or {}
        b_str = " ｜ ".join(f"{k}={v if v is not None else '缺数据'}" for k, v in bounds.items())
        lines.append(f"- **建议仓位: {pos['size']:.0%}**（约束源={pos.get('binding')};"
                     f"半Kelly{'已计' if pos.get('kelly_used') else '缺判卷数据未计'}）")
        lines.append(f"- 三项边界: {b_str}")
    else:
        lines.append(f"- 建议仓位: 不给出（{pos.get('note', '数据不足')}）")

    cand = brief.get("candidates") or {}
    if cand.get("candidates"):
        lines.append("## 候选名单([S7] 候选级,非荐股)")
        meta_d = cand.get("meta") or {}
        lines.append(f"> {meta_d.get('disclaimer', '')}")
        for c in cand["candidates"][:5]:
            lines.append(f"- {c['symbol']}: 预测分 {c['pred']} ｜ 权重 {c['weight']:.1%}")
        lines.append(f"(完整 {len(cand['candidates'])} 只见 candidates_latest.json;买入前过 limits.check_order)")
        lines.append("")
    lines.append("")
    lines.append("*失效即作废，不恋战。*")
    return "\n".join(lines) + "\n"
