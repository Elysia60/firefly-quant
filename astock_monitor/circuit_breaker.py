"""回撤熔断(P6 实装)— 利弗莫尔 10% 规则的机器化。

来源:docs/reading/livermore-firefly.md §4 + docs/optimization-roadmap.md "P6-回撤熔断·公式级参数定案"
(2026-11-18)。核心命题:**知道全部正确规则的人依然毁灭(1940)——所以"认错"必须是机器动作,不是心理动作。**

三条硬参数(预注册,不随结果漂移;风控参数=DSR 中性,不产生交易信号):
  · 单笔持仓回撤 ≤ -10%  → 强制离场(利弗莫尔原版参数,不给"再等等"留口子)
  · 组合回撤     ≤ -15%  → 自动降仓至半(减仓单永远放行,风险guard 纪律)
  · 组合回撤     ≤ -25%  → 清仓 + 推送 + 冷却;重启需人工过审(半自动纪律)

设计纪律:
  · **fail-closed**:净值/持仓数据缺失时不许"假设正常"——block_new_entries=True,动作只降不升
  · **状态机**:normal → half → cleared;cleared 粘性(必须 reset() 人工过审),half 在回撤收敛后自动回 normal
  · **跌停只降不升**:跌停日卖不出 → 出场动作标 pending_limit_down,不假装执行,下一交易日继续挂
  · **高水位持久化**:回撤以历史净值高水位为锚,状态 JSON 落盘,进程重启不丢
  · **审计**:每次判定/复位追加 JSONL 事件(可重放对账)
  · 与 [S16] 门控分工:门控=灾前防御(事前),熔断=灾后止损(事后),两层独立触发
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# ── 预注册阈值(利弗莫尔参数机器化) ──
SINGLE_STOP = -0.10       # 单笔强制离场线
PORTFOLIO_HALF = -0.15    # 组合降半线
PORTFOLIO_CLEAR = -0.25   # 组合清仓线
HALF_RECOVER = -0.10      # half→normal 的滞回恢复线(避免在 -15% 附近抖动)

EPS = 1e-9  # 浮点边界容差:90/100-1=-0.0999999…,但预注册线是精确 -10% 必须触发

MODE_NORMAL = "normal"
MODE_HALF = "half"
MODE_CLEARED = "cleared"
VALID_MODES = (MODE_NORMAL, MODE_HALF, MODE_CLEARED)


def _now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def position_drawdown(entry_price: float, current_price: float) -> float:
    """单笔持仓回撤(相对成本,负数)。

    边界:entry_price 必须 > 0(fail loud);current_price 可为 0(极端,按 -100% 处理)。
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price 必须 > 0,收到 {entry_price}")
    if current_price < 0:
        raise ValueError(f"current_price 不能为负,收到 {current_price}")
    return current_price / entry_price - 1.0


def drawdowns(positions: dict) -> dict[str, float]:
    """positions = {symbol: {"entry_price": x, "current_price": y, "weight": w}} → {symbol: dd}。"""
    out = {}
    for sym, p in (positions or {}).items():
        out[sym] = position_drawdown(float(p["entry_price"]), float(p["current_price"]))
    return out


def _empty_state() -> dict:
    return {"mode": MODE_NORMAL, "high_water": None, "cleared_at": None,
            "cleared_reason": None, "manual_reset_required": False,
            "last_eval": None, "last_drawdown": None}


def load_state(path: str | Path) -> dict:
    """读状态;文件缺失/损坏 → 基线状态(fail-open 起步,不因坏文件卡死整条管线)。"""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_state()
    base = _empty_state()
    base.update({k: data.get(k, base[k]) for k in base})
    if base["mode"] not in VALID_MODES:
        base["mode"] = MODE_NORMAL
    return base


def save_state(path: str | Path, state: dict) -> None:
    """原子写(tmp + os.replace),崩溃不留半截 JSON。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def append_event(path: str | Path, event: dict) -> None:
    """审计事件追加(JSONL,一行一事件;可重放对账)。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def evaluate(
    positions: dict,
    portfolio_drawdown: float | None,
    state: dict | None = None,
    limit_down: tuple[str, ...] | frozenset[str] = (),
    now: datetime | None = None,
) -> dict:
    """纯函数判定:给定持仓/组合回撤/历史状态 → 动作清单 + 新状态(不写盘)。

    positions: {symbol: {"entry_price","current_price","weight"}}
    portfolio_drawdown: 相对高水位的回撤(负数);None = 数据缺失 → fail-closed
    limit_down: 今日跌停卖不出的 symbol 集合(出场延后,不假装执行)
    返回 dict:
      mode / prev_mode / actions / forced_exits / scale / block_new_entries /
      requires_manual_reset / reasons / drawdowns / portfolio_drawdown / as_of
    """
    st = dict(state or _empty_state())
    prev_mode = st.get("mode", MODE_NORMAL)
    ts = _now(now)
    actions: list[dict] = []
    reasons: list[str] = []

    # ── 1) fail-closed:净值数据缺失 → 只降不升 ──
    if portfolio_drawdown is None:
        st["last_eval"] = ts
        return {
            "mode": prev_mode, "prev_mode": prev_mode, "as_of": ts,
            "portfolio_drawdown": None,
            "drawdowns": drawdowns(positions) if positions else {},
            "forced_exits": [], "scale": 1.0,
            "block_new_entries": True, "requires_manual_reset": bool(st.get("manual_reset_required")),
            "actions": [{"action": "fail_closed", "reason": "组合净值/回撤数据缺失"}],
            "reasons": ["净值数据缺失 → fail-closed:禁止开新仓,动作只降不升"],
            "state": st,
        }

    pdd = float(portfolio_drawdown)
    if pdd > 0:
        raise ValueError(f"portfolio_drawdown 应为非正数(相对高水位),收到 {portfolio_drawdown}")

    # 高水位维护:首跑用 1.0 起步;回撤换算容错
    if st.get("high_water") is None:
        st["high_water"] = 1.0

    # ── 2) 单笔强制离场(与组合档位独立;清仓时自然被覆盖) ──
    dds = drawdowns(positions) if positions else {}
    forced = []
    for sym, dd in dds.items():
        if dd <= SINGLE_STOP + EPS:
            if sym in limit_down:
                forced.append({"symbol": sym, "action": "exit",
                               "status": "pending_limit_down",
                               "drawdown": round(dd, 4),
                               "reason": f"单笔回撤 {dd:.1%} ≤ {SINGLE_STOP:.0%},但今日跌停无法卖出,次日继续挂单"})
                reasons.append(f"{sym} 触发单笔止损但跌停 → 挂单待成交")
            else:
                forced.append({"symbol": sym, "action": "exit", "status": "ready",
                               "drawdown": round(dd, 4),
                               "reason": f"单笔回撤 {dd:.1%} ≤ {SINGLE_STOP:.0%} 强制离场(利弗莫尔原版参数)"})

    # ── 3) 组合档位(清仓 > 降半 > 滞回恢复) ──
    if pdd <= PORTFOLIO_CLEAR + EPS:
        mode = MODE_CLEARED
        scale = 0.0
        actions.append({"action": "clear_all",
                        "reason": f"组合回撤 {pdd:.1%} ≤ {PORTFOLIO_CLEAR:.0%}:清仓+推送+冷却"})
        reasons.append("组合回撤触发清仓线:全部离场,重启需人工过审")
        st["cleared_at"] = ts
        st["cleared_reason"] = f"portfolio_dd={pdd:.4f}"
        st["manual_reset_required"] = True
    elif pdd <= PORTFOLIO_HALF + EPS:
        mode = MODE_HALF
        scale = 0.5
        if prev_mode != MODE_HALF:
            reasons.append(f"组合回撤 {pdd:.1%} ≤ {PORTFOLIO_HALF:.0%}:自动降仓至半")
        actions.append({"action": "de_risk_half",
                        "reason": f"组合回撤 {pdd:.1%} ≤ {PORTFOLIO_HALF:.0%}:权重×0.5"})
    elif prev_mode == MODE_HALF and pdd > HALF_RECOVER + EPS:
        mode = MODE_NORMAL
        scale = 1.0
        reasons.append(f"回撤收敛至 {pdd:.1%} > {HALF_RECOVER:.0%}:解除半仓(滞回)")
        actions.append({"action": "recover_normal", "reason": "回撤收敛,恢复基线仓位"})
    elif prev_mode == MODE_CLEARED:
        # cleared 粘性:回撤收敛也不自动恢复,必须人工过审
        mode = MODE_CLEARED
        scale = 0.0
        reasons.append("仍处清仓冷却期:回撤收敛不自动复位,需人工过审(reset)")
    else:
        mode = prev_mode if prev_mode in VALID_MODES else MODE_NORMAL
        scale = 0.5 if mode == MODE_HALF else 1.0

    # cleared 的粘性高于一切档位恢复(上面已处理,这里兜底防御)
    if prev_mode == MODE_CLEARED and st.get("manual_reset_required"):
        mode = MODE_CLEARED
        scale = 0.0

    st["mode"] = mode
    st["last_eval"] = ts
    st["last_drawdown"] = round(pdd, 6)

    if mode == MODE_CLEARED:
        forced = [{"symbol": s, "action": "exit", "status": "ready",
                   "drawdown": round(d, 4), "reason": "清仓线:全部离场"}
                  for s, d in dds.items()]

    block_new = mode == MODE_CLEARED or prev_mode == MODE_CLEARED
    return {
        "mode": mode, "prev_mode": prev_mode, "as_of": ts,
        "portfolio_drawdown": round(pdd, 6),
        "thresholds": {"single_stop": SINGLE_STOP,
                       "portfolio_half": PORTFOLIO_HALF,
                       "portfolio_clear": PORTFOLIO_CLEAR,
                       "half_recover": HALF_RECOVER},
        "drawdowns": {s: round(d, 4) for s, d in dds.items()},
        "forced_exits": forced,
        "scale": scale,
        "block_new_entries": block_new,
        "requires_manual_reset": bool(st.get("manual_reset_required")),
        "actions": actions,
        "reasons": reasons or ["未触发任何熔断档位"],
        "state": st,
    }


def reset(state: dict, approved_by: str, reason: str = "", now: datetime | None = None) -> dict:
    """人工过审复位:只允许从 cleared 复位(normal/half 无需人工)。返回新状态。"""
    if not approved_by:
        raise ValueError("manual reset 必须记录 approved_by(半自动纪律:谁批的)" )
    st = dict(state or _empty_state())
    if st.get("mode") != MODE_CLEARED:
        return st  # 非 cleared 无需复位(幂等)
    st["mode"] = MODE_NORMAL
    st["manual_reset_required"] = False
    st["high_water"] = st.get("high_water") or 1.0
    st["last_eval"] = _now(now)
    st["cleared_at"] = None
    st["cleared_reason"] = None
    st["reset_by"] = approved_by
    st["reset_reason"] = reason
    return st


def render_line(report: dict) -> str:
    """给日报 ⑤ 风控面的一行(或两行)人类可读文本。"""
    mode = report.get("mode", "?")
    mark = {"normal": "🟢", "half": "🟡", "cleared": "🔴"}.get(mode, "⚪")
    dd = report.get("portfolio_drawdown")
    dd_s = f"{dd:.1%}" if isinstance(dd, (int, float)) else "缺"
    parts = [f"- {mark} 回撤熔断(P6): 组合回撤 {dd_s} → {mode}"
             f"(单笔≤-10% 离场 / 组合≤-15% 降半 / ≤-25% 清仓冷却)"]
    for a in report.get("actions", []):
        parts.append(f"  · {a.get('action')}: {a.get('reason')}")
    if report.get("requires_manual_reset"):
        parts.append("  · ⚠ 清仓冷却中:重启需人工过审(`circuit-reset --approved-by <人>`)")
    if report.get("block_new_entries"):
        parts.append("  · ⛔ 禁止开新仓(fail-closed/清仓期)")
    return "\n".join(parts)
