"""统计审计地基(第 7 周加速项,公式正本 = METHODS.md §3e;纯标准库)。

三项能力(2026-11-13 调研定案,参考 arch 库口径与 Politis-Romano 1994):
1. **Newey-West HAC t 统计量**:T+n 滚动重叠前向收益的误差是 MA(n−1) 结构,
   朴素 t 检验会虚高显著性;NW 用 Bartlett 权重修正 L = n−1 的自相关。
2. **Stationary Bootstrap CI**(Politis & Romano 1994):块自助法给出均值 CI,
   块长 b ≥ 重叠窗径(n)否则切断相关性;与 n_eff 保守口径并行输出(保守/精确两档)。
3. **事件研究对照**(随机化推断):信号日 vs 同条件随机对照日,
   置换检验给 p 值——把"方向正确率 55%"与"牛市基线"区分开(csqaq [C1] 升级路线)。
"""

from __future__ import annotations

import math
import random
from datetime import timedelta


def _lag_len(n: int, window: int | None) -> int:
    """NW 截断:L = max(重叠窗径 n−1, floor(4·(T/100)^(2/9)))——后者是 NW 惯用上限。"""
    base = 0 if window is None else window - 1
    rule = int(4 * (n / 100) ** (2 / 9)) if n > 0 else 0
    return max(1, base, rule)


def newey_west_t(series: list[float], window: int | None = None) -> float:
    """重叠序列均值的 HAC t 统计量(近似 N(0,1))。

    Var(x̄) = (1/T)·[γ̂₀ + 2·Σ_{l=1..L}(1−l/(L+1))·γ̂_l](Bartlett 权重)。
    退化(方差为 0)返回 inf 符号位——调用方须视为"不可判"而非显著。
    """
    T = len(series)
    if T < 2:
        raise ValueError("样本不足")
    mean = sum(series) / T
    dev = [x - mean for x in series]
    L = _lag_len(T, window)
    gamma = []
    for l in range(L + 1):
        g = sum(dev[t] * dev[t - l] for t in range(l, T)) / T
        gamma.append(g)
    var = gamma[0] + 2.0 * sum((1.0 - l / (L + 1.0)) * gamma[l] for l in range(1, L + 1))
    if var <= 0:
        return math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
    return mean / math.sqrt(var / T)


def stationary_bootstrap_indices(T: int, avg_block: int, rng: random.Random) -> list[int]:
    """Politis-Romano 1994 索引生成:p=1/b,延续概率 1−p,越界回绕。"""
    if T < 1:
        raise ValueError("T<1")
    b = max(1, avg_block)
    p = 1.0 / b
    idx = [rng.randrange(T)]
    for _ in range(1, T):
        if rng.random() < p:
            idx.append(rng.randrange(T))
        else:
            nxt = idx[-1] + 1
            idx.append(nxt if nxt < T else 0)
    return idx


def bootstrap_mean_ci(series: list[float], avg_block: int, B: int = 1000,
                      alpha: float = 0.05, seed: int = 42) -> tuple[float, float]:
    """均值的 stationary bootstrap 百分位 CI;块长建议 ≥ 重叠窗径。"""
    if len(series) < 2:
        raise ValueError("样本不足")
    rng = random.Random(seed)
    T = len(series)
    means = []
    for _ in range(B):
        idx = stationary_bootstrap_indices(T, avg_block, rng)
        means.append(sum(series[i] for i in idx) / T)
    means.sort()
    lo = means[int((alpha / 2) * B)]
    hi = means[min(B - 1, int((1 - alpha / 2) * B))]
    return lo, hi


def event_study(signal_days: set, forward_returns: dict,
                all_days: list, K: int = 5, B: int = 1000,
                min_gap: int = 20, match_weekday: bool = True,
                seed: int = 42) -> dict:
    """信号日 vs 同条件随机对照日的置换检验(随机化推断)。

    - signals: 信号日集合;forward_returns: {date: T+n 前向收益};all_days: 全历史交易日。
    - 匹配条件(MVP):星期几相同;对照日与信号日距离 > min_gap(防污染窗)。
    - d_obs = mean(信号组前向) − mean(对照组前向);
      置换 p 值 = (1 + #{d_b ≥ d_obs}) / (B+1)(池化重排标签,无分布假设)。
    - 返回含 d_obs、p_perm、两组均值与样本量;条件不满足的信号日跳过并计数。
    """
    rng = random.Random(seed)
    day_set = set(all_days)
    used: set = set()
    treatment, skipped = [], 0
    for e in sorted(signal_days):
        if e not in forward_returns:
            skipped += 1
            continue
        used.add(e)
        treatment.append(forward_returns[e])
    if not treatment:
        return {"error": "no valid signal days"}
    # 对照池:与任一信号日距离 > min_gap 的交易日
    pool = []
    for d in all_days:
        if d not in forward_returns or d in used:
            continue
        if any(abs((d - e).days) <= min_gap for e in used):
            continue
        pool.append(d)
    if match_weekday:
        # 分星期几分桶,对照按信号日的星期构成抽样
        by_wd: dict[int, list] = {}
        for d in pool:
            by_wd.setdefault(d.weekday(), []).append(d)
        rng.shuffle(pool)
        control_days = []
        need_by_wd: dict[int, int] = {}
        for e in used:
            if e in forward_returns:
                need_by_wd[e.weekday()] = need_by_wd.get(e.weekday(), 0) + 1
        for wd, need in need_by_wd.items():
            cands = [d for d in pool if d.weekday() == wd]
            control_days.extend(cands[:need * K])  # 每信号 K 个对照,提升置换功效
        control = [forward_returns[d] for d in control_days if d in forward_returns]
    else:
        control = [forward_returns[d] for d in pool[: K * len(used)] if d in forward_returns]
    if len(control) < 10:
        # 置换检验允许不均衡(信号密度高时对照天然稀少),但 <10 则 p 值太粗糙
        return {"error": "insufficient control days", "control_n": len(control),
                "hint": "对照池被信号聚集+污染窗挤占;可减小 min_gap 或扩大历史"}
    d_obs = sum(treatment) / len(treatment) - sum(control) / len(control)
    pooled = treatment + control
    n_t = len(treatment)
    count_high = 0
    count_low = 0
    for _ in range(B):
        rng.shuffle(pooled)
        d_b = sum(pooled[:n_t]) / n_t - sum(pooled[n_t:]) / (len(pooled) - n_t)
        if d_b >= d_obs:
            count_high += 1
        if d_b <= d_obs:
            count_low += 1
    return {
        "signal_n": len(treatment), "control_n": len(control),
        "mean_signal": sum(treatment) / len(treatment),
        "mean_control": sum(control) / len(control),
        "d_obs": d_obs,
        "p_high": (1 + count_high) / (B + 1),   # H1: 信号组 ≥ 对照组
        "p_low": (1 + count_low) / (B + 1),     # H1: 信号组 ≤ 对照组(相对弱势)
        "skipped_missing_forward": skipped,
    }
