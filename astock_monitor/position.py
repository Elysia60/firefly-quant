# -*- coding: utf-8 -*-
"""position.py — 三选最小仓位引擎（2026-11-21 · 萤火决策化第二层）

来源: 2026-11-14 全机升级计划 P6 预注册项（此前未实施）。
理念: 三个独立的仓位约束各算各的,**取最小**——没有一个能单独放大仓位,
只做减法。与 circuit_breaker（只降不升）串联: 熔断非 normal → 仓位 0。

三条约束（全部可对账,数字来源写死）:
  1. 波动率缩放  = target_vol / realized_vol,夹 [0,1]
     （csqaq position.vol_scalar 同式,跨市场同构）
  2. 阶梯上限    = regime 风险阶梯 {BULL:1.0, NEUTRAL:0.6, BEAR:0.3}
     （预注册值;与 portfolio.REGIME_SCALE 是两回事——那是回测尺度,这是风险阶梯）
  3. 半 Kelly    = f*/2,f* = W − (1−W)/R_payoff,夹 [0,0.25]
     （W/R 来自判卷区 judge_accuracy——**无判卷数据时该项不参与 min**,
      而不是假装一个数;诚实降级,fail-open）

用法:
    from astock_monitor.position import suggested_size
    r = suggested_size(realized_vol=28.0, win_rate=0.62, payoff_ratio=1.4,
                       regime_state=1, breaker_mode="normal")
    # {"size": 0.28, "bounds": {"vol": 0.71, "ladder": 0.6, "kelly": None(或 x)},
    #  "binding": "ladder", "note": ...}
"""
from __future__ import annotations

# 阶梯上限（预注册 2026-11-21;改动记 docs/improvement-log.md）
LADDER = {0: 1.0, 1: 0.6, 2: 0.3}   # BULL / NEUTRAL / BEAR（regime.py 同值定义）
TARGET_VOL = 20.0                    # 年化目标波动(%,与 csqaq position 同默认)
KELLY_CAP = 0.25                     # 半 Kelly 上限(防过度下注)


def vol_scalar(realized_vol: float, target_vol: float = TARGET_VOL) -> float | None:
    """波动率缩放。realized_vol 缺失/非正 → None(不参与 min)。"""
    if realized_vol is None or realized_vol <= 0:
        return None
    return round(min(1.0, max(0.0, target_vol / realized_vol)), 4)


def kelly_half(win_rate: float | None, payoff_ratio: float | None) -> float | None:
    """半 Kelly。任一输入缺失 → None(诚实降级:该项不参与 min)。"""
    if win_rate is None or payoff_ratio is None or payoff_ratio <= 0:
        return None
    if not (0 <= win_rate <= 1):
        return None
    f = win_rate - (1 - win_rate) / payoff_ratio
    return round(min(KELLY_CAP, max(0.0, f / 2)), 4)


def ladder_cap(regime_state: int | None) -> float | None:
    if regime_state is None or regime_state not in LADDER:
        return None
    return LADDER[regime_state]


def suggested_size(realized_vol: float | None, win_rate: float | None,
                   payoff_ratio: float | None, regime_state: int | None,
                   breaker_mode: str = "normal",
                   manual_reset: bool = False,
                   target_vol: float = TARGET_VOL) -> dict:
    """三选最小 × 熔断闸门。纯函数。

    返回 {"size", "bounds", "binding", "kelly_used", "note"}。
    - 熔断非 normal 或 manual_reset → size=0(binding="breaker")
    - 三项全缺(理论上不可能,regime 缺仍给 ladder 缺失标记) → size=None+note
    """
    bounds = {"vol": vol_scalar(realized_vol, target_vol),
              "ladder": ladder_cap(regime_state),
              "kelly": kelly_half(win_rate, payoff_ratio)}
    if manual_reset or breaker_mode != "normal":
        return {"size": 0.0,
                "bounds": bounds, "binding": "breaker",
                "kelly_used": bounds["kelly"] is not None,
                "note": f"熔断状态 {breaker_mode}" + (";需人工复位" if manual_reset else "")}
    active = {k: v for k, v in bounds.items() if v is not None}
    if not active:
        return {"size": None, "bounds": bounds, "binding": None,
                "kelly_used": False,
                "note": "三项约束全部缺数据——不给出仓位建议(不造数)"}
    binding = min(active, key=active.get)
    size = active[binding]
    return {"size": size, "bounds": bounds, "binding": binding,
            "kelly_used": bounds["kelly"] is not None,
            "note": f"约束源={binding}(三选最小:波动率缩放/阶梯/半Kelly)"}
