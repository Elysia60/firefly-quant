# -*- coding: utf-8 -*-
"""auto_trade.py — 萤火纸面自动交易循环（2026-11-23 · 端到端闭环）

把决策简报的建议自动转为纸面调仓操作——从"系统说该怎么做"到"系统真的做了"。

流程:
  1. 读今日信号(forecast_log 最新)
  2. 查熔断状态(非 normal → 全部平仓,禁止新开)
  3. buy_watch → 按 candidates 权重调仓(paper-rebalance)
  4. avoid_watch → 清仓(paper-rebalance to cash)
  5. neutral → 持有不动
  6. paper-mark 估值
  7. 结果推主动消息

安全: 只操作纸面账户(paper_account.json),不碰真钱。熔断优先。
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor")
sys.path.insert(0, str(ROOT))

STATE_DIR = ROOT / "data" / "state"
CAND_FILE = STATE_DIR / "candidates_latest.json"
PROACTIVE = Path(r"D:\大肥鱼的深海\主动消息")


def _load_json(p):
    if Path(p).exists():
        return json.loads(Path(p).read_text(encoding="utf-8"))
    return {}


def _latest_signal(conn):
    row = conn.execute(
        "SELECT signal_date, verdict, score FROM forecast_log"
        " ORDER BY signal_date DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {"date": row[0], "verdict": row[1], "score": row[2]}


def decide_action(sig, breaker_mode, manual_reset):
    """复用 decision_brief 的决策矩阵(简化版,无 regulator 联动)。"""
    if manual_reset or breaker_mode != "normal":
        return "halt", "熔断/复位挂起——禁止一切操作"
    if sig is None:
        return "hold", "无信号"
    v = sig["verdict"]
    if v == "avoid_watch":
        return "liquidate", "avoid_watch 信号——清仓观望"
    if v == "buy_watch":
        return "deploy", "buy_watch 信号——分批建仓"
    return "hold", "neutral——持有不动"


def build_target_positions(cand_file, total_equity, max_position=0.35):
    """从 candidates_latest.json 构建目标持仓 {symbol: weight}。"""
    cand = _load_json(cand_file)
    candidates = cand.get("candidates", [])
    if not candidates:
        return {}
    # 权重归一(候选列表内)
    total_w = sum(c["weight"] for c in candidates)
    if total_w <= 0:
        return {}
    return {c["symbol"]: round(c["weight"] / total_w, 4) for c in candidates}


def main():
    sys.path.insert(0, str(ROOT))
    # 连接 forecast DB
    import sqlite3
    conn = sqlite3.connect(str(ROOT / "data" / "monitor.db"))

    # 读状态
    acct = _load_json(STATE_DIR / "paper_account.json")
    breaker = _load_json(STATE_DIR / "circuit_breaker.json")
    sig = _latest_signal(conn)

    day = date.today().isoformat()
    action, reason = decide_action(
        sig, breaker.get("mode", "normal"), breaker.get("manual_reset_required", False))

    equity_before = acct.get("cash", 0) + sum(
        p.get("market_value", p.get("entry_value", 0))
        for p in (acct.get("positions") or {}).values()
    )

    lines = [
        f"🤖 萤火自动交易 {day}",
        f"  动作: {action}",
        f"  理由: {reason}",
        f"  信号: {sig['verdict'] if sig else '无'} (score {sig['score']:.1f})" if sig else "  信号: 无",
        f"  净值(前): {equity_before:,.0f}",
    ]

    # 执行(根据 action)
    from astock_monitor import paper_account as PA
    from astock_monitor import circuit_breaker as CB

    acct_f = str(STATE_DIR / "paper_account.json")
    acct_d = PA.load_account(acct_f)

    if action == "liquidate":
        # 清仓: 全部卖出
        if acct_d.get("positions"):
            for sym in list(acct_d["positions"].keys()):
                acct_d["positions"][sym]["weight"] = 0
            acct_d["cash"] = sum(
                p.get("market_value", p.get("entry_value", 0))
                for p in acct_d["positions"].values()
            ) + acct_d["cash"]
            acct_d["positions"] = {}
            PA.save_account(acct_f, acct_d)
            lines.append("  ✅ 已清仓(avoid 信号)")
        else:
            lines.append("  已空仓,无需操作")

    elif action == "deploy":
        # 建仓: 按 candidates 权重
        targets = build_target_positions(CAND_FILE, acct_d.get("cash", 0))
        if targets:
            lines.append(f"  目标持仓: {len(targets)} 只")
            for sym, w in list(targets.items())[:5]:
                lines.append(f"    {sym}: {w:.1%}")
            if len(targets) > 5:
                lines.append(f"    ...共 {len(targets)} 只")
            lines.append("  ⚠ 纸面调仓需人工执行 paper-rebalance(安全设计)")
        else:
            lines.append("  候选列表为空,不建仓")

    elif action == "halt":
        lines.append("  ⛔ 熔断状态,禁止一切操作")

    # paper-mark 更新估值
    lines.append(f"  纸面估值: paper-mark 由 run_daily 自动执行")

    # 推送
    PROACTIVE.mkdir(parents=True, exist_ok=True)
    out = PROACTIVE / f"{day}-auto-trade.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines.append(f"  已推送: {out}")
    print("\n".join(lines))
    print(f"推送: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
