"""Regime 门控引擎(侦察定案,roadmap P3;规则法=唯一天然因果的一类)。

三特征(全部只用 ≤T-1;本模块产出的"as-of 日期"语义=该状态在当日收盘后可知,
供次日使用——asof() 保证取严格早于信号日的最后状态):
1. **年线滞回**(主):close vs MA250,进多区 ×1.01 / 退多区 ×0.96(A 股实测参数,
   davidwang0116 回测:比美股 1.03/0.83 窄,A 股牛熊转换更陡);状态机防年线附近反复
2. **年线宽度** breadth250:站上 MA250 个股占比 >0.6 多头 / <0.4 空头(湖内回算)
3. **波动否决** vol_veto:20 日已实现波动率的 500 日滚动分位 >0.9

状态合成:**三票二 + 5 日持续确认去抖**;三态 0=bull / 1=neutral / 2=bear——
neutral 不覆盖信号,bear 才否决(与 [S1] 兼容:门控在修复年的作用是缩短而非替代)。
"""

from __future__ import annotations

import math
from datetime import date

BULL, NEUTRAL, BEAR = 0, 1, 2
MA250_ENTER = 1.01
MA250_EXIT = 0.96
BREADTH_BULL = 0.6
BREADTH_BEAR = 0.4
VOL_VETO_PCT = 0.9
DEBOUNCE_DAYS = 5


def ma250_series(closes: list[float]) -> list[float | None]:
    """逐日 MA250(第 i 个值用 closes[0..i],天然因果);不足 250 日为 None。"""
    out: list[float | None] = []
    total = 0.0
    for i, c in enumerate(closes):
        total += c
        if i >= 250:
            total -= closes[i - 250]
        out.append(total / 250 if i >= 249 else None)
    return out


def hysteresis_gate(closes: list[float], enter: float = MA250_ENTER,
                    exit_mult: float = MA250_EXIT) -> list[int | None]:
    """年线滞回状态机:1=多头区,0=空头区,None=历史不足。

    close > MA250×enter → 转多;close < MA250×exit_mult → 转空;区间内保持原状态。
    第 i 个输出只用 closes[0..i]。
    """
    mas = ma250_series(closes)
    states: list[int | None] = []
    state: int | None = None
    for c, ma in zip(closes, mas):
        if ma is None:
            states.append(None)
            continue
        if state is None:
            state = 1 if c > ma * enter else 0
            states.append(state)
            continue
        if c > ma * enter:
            state = 1
        elif c < ma * exit_mult:
            state = 0
        states.append(state)
    return states


def realized_vol_percentile(closes: list[float], window: int = 20,
                            rank_window: int = 500) -> list[float | None]:
    """20 日已实现波动率的 500 日滚动分位(分位池不含当日——防泄漏)。

    第 i 个输出 = vol[i] 在 vol[i-rank_window..i-1] 中的分位;池不足 60 个为 None。
    """
    rets = [None] + [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    vols: list[float | None] = []
    for i in range(len(closes)):
        if i < window:
            vols.append(None)
            continue
        seg = rets[i - window + 1:i + 1]
        if any(r is None for r in seg):
            vols.append(None)
            continue
        mean = sum(seg) / window
        vols.append(math.sqrt(sum((r - mean) ** 2 for r in seg) / (window - 1)))
    out: list[float | None] = []
    for i, v in enumerate(vols):
        if v is None:
            out.append(None)
            continue
        pool = [x for x in vols[max(0, i - rank_window):i] if x is not None]
        if len(pool) < 60:
            out.append(None)
            continue
        out.append(sum(1 for x in pool if x <= v) / len(pool))
    return out


def classify_day(gate: int | None, breadth250: float | None,
                 vol_pct: float | None) -> int:
    """三票二:bear 票 = 年线空区 + 宽度<0.4 + 波动分位>0.9;bull 票 = 年线多区 + 宽度>0.6。"""
    if gate is None:
        return NEUTRAL
    bear_votes = (1 if gate == 0 else 0) + (1 if breadth250 is not None and breadth250 < BREADTH_BEAR else 0) \
        + (1 if vol_pct is not None and vol_pct > VOL_VETO_PCT else 0)
    bull_votes = (1 if gate == 1 else 0) + (1 if breadth250 is not None and breadth250 > BREADTH_BULL else 0)
    if bear_votes >= 2:
        return BEAR
    if bull_votes >= 2:
        return BULL
    return NEUTRAL


def debounce(raw: list[int], k: int = DEBOUNCE_DAYS) -> list[int]:
    """持续确认:状态切换需连续 k 日同 raw;初始态 = raw[0]。O(n)。"""
    out = [raw[0]] if raw else []
    pending = raw[0] if raw else NEUTRAL
    run = 1
    for x in raw[1:]:
        if x == out[-1]:
            pending, run = out[-1], 0
        elif x == pending:
            run += 1
        else:
            pending, run = x, 1
        out.append(out[-1] if run < k else pending)
    return out


def daily_regime(index_closes: list[tuple[date, float]],
                 breadth250: dict[date, float] | None = None) -> dict[date, dict]:
    """逐日 regime 状态(纯标准库)。

    返回 {date_i: {...}},其中状态字段由 closes[0..i] 算出——
    **供 T=i+1 日使用**;取用一律走 asof(),它强制"严格早于信号日"。
    """
    dates = [d for d, _ in index_closes]
    closes = [c for _, c in index_closes]
    gates = hysteresis_gate(closes)
    volp = realized_vol_percentile(closes)
    raw, detail = [], []
    for i, d in enumerate(dates):
        b250 = None
        if breadth250:
            prior = [x for x in breadth250 if x <= d]  # 宽度按"当日收盘后可知"对齐
            if prior:
                b250 = breadth250[max(prior)]
        st = classify_day(gates[i], b250, volp[i])
        raw.append(st)
        detail.append({"gate": gates[i], "breadth250": b250, "vol_pct": volp[i], "raw": st})
    deb = debounce(raw)
    out: dict[date, dict] = {}
    for i, d in enumerate(dates):
        row = dict(detail[i])
        row["regime"] = deb[i]
        out[d] = row
    return out


def asof(regime: dict[date, dict], d: date) -> dict | None:
    """取严格早于 d 的最后一条 regime 状态(防泄漏的唯一合法取用口)。"""
    prior = [x for x in regime if x < d]
    return regime[max(prior)] if prior else None
