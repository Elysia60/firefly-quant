"""Meta-labeling 引擎(P8,侦察定案 2026-11-13;公式正本 = roadmap P8 / AFML Ch.3)。

把 [S2] 证伪的"全仓开关"变成"条件仓位":
- 事件采样:只有 [S1] 触发日(avoid_watch)进训练——非触发日没有赌注
- 元标签:triple-barrier(横挡=1.0×σ_YZ,竖挡=5 日;空方赌注:先触下挡=1,先触上挡/双触=0)
- 特征:信号自身成分 + 波动率分位 + regime 态(全 point-in-time,缺失中性填充+标注)
- 模型:逻辑回归 IRLS(纯标准库 Newton-Raphson + L2)
- 验证:purged K-fold(训练事件与测试事件屏障窗/ embargo 分离)

A股特有:涨跌停日 H/L 被截断 → YZ 波动低估,样本标注降权(V0 记录,不做剔除)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

HORIZON = 5          # 竖挡:5 个交易日
BARRIER_H = 1.0      # 横挡:1.0 倍日度波动
EMBARGO_DAYS = 5


# ---------------------------------------------------------------- 波动率

def yang_zhang_vol(bars: list[tuple[float, float, float, float]],
                   window: int = 21) -> list[float | None]:
    """Yang-Zhang(2000) 日度波动率(唯一同时处理隔夜跳空与漂移)。

    bars = (open, high, low, close) 升序;第 i 个输出用 bars[i-window+1..i]。
    σ²_YZ = σ²_隔夜 + k·σ²_开收 + (1−k)·σ²_RS;k = 0.34/(1.34+(T+1)/(T−1))。
    涨跌停日 H/L 截断会低估(A股特有,调用方标注)。
    """
    out: list[float | None] = []
    for i in range(len(bars)):
        if i < window:
            out.append(None)
            continue
        seg = bars[i - window + 1:i + 1]
        T = len(seg)
        k = 0.34 / (1.34 + (T + 1) / (T - 1))
        on = oc = rs = 0.0
        for j in range(1, T):
            o_prev, _, _, c_prev = seg[j - 1]
            o, h, l, c = seg[j]
            if min(o, h, l, c, c_prev) <= 0:
                continue
            on += math.log(o / c_prev) ** 2
            oc += math.log(c / o) ** 2
            rs += math.log(h / c) * math.log(h / o) + math.log(l / c) * math.log(l / o)
        on /= T
        oc /= T
        rs /= T
        var = on + k * oc + (1 - k) * rs
        out.append(math.sqrt(max(var, 0.0)))
    return out


# ---------------------------------------------------------------- 元标签

def triple_barrier_label(entry: float, o_dir: list[tuple[float, float, float]],
                         sigma: float, h: float = BARRIER_H,
                         horizon: int = HORIZON) -> int | None:
    """空方赌注的三挡标签(avoid 信号=赌相对弱势)。

    o_dir = 竖挡期内逐日 (high, low, close)(信号日之后)。横挡 = entry×(1 ± h·σ)。
    先触下挡(entry×(1−h·σ))→ 1;先触上挡 → 0;同日双触 → 0(保守);竖挡到期未触 → 按末收方向。
    sigma/entry 异常返回 None。
    """
    if sigma is None or sigma <= 0 or entry <= 0:
        return None
    down = entry * (1 - h * sigma)
    up = entry * (1 + h * sigma)
    last_close = entry
    for j, (high, low, close) in enumerate(o_dir[:horizon]):
        hit_down = low <= down
        hit_up = high >= up
        if hit_down and not hit_up:
            return 1
        if hit_up:
            return 0  # 先触上挡或同日双触 → 保守 0
        last_close = close
    return 1 if last_close < entry else 0  # 到期:按方向


# ---------------------------------------------------------------- 逻辑回归(IRLS)

def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 60)))
    e = math.exp(max(z, -60))
    return e / (1.0 + e)


def irls_logistic(X: list[list[float]], y: list[int], l2: float = 1.0,
                  iters: int = 25) -> list[float]:
    """L2 正则逻辑回归,Newton-Raphson/IRLS(纯标准库)。

    X 已含截距列;返回系数。迭代不收敛(发散)时返回最后一次稳定解——
    调用方应以预测概率合理性而非收敛标志为准。
    """
    n, d = len(X), len(X[0])
    beta = [0.0] * d
    best = beta[:]
    for _ in range(iters):
        p = [_sigmoid(sum(b * x for b, x in zip(beta, row))) for row in X]
        w = [max(pi * (1 - pi), 1e-9) for pi in p]
        grad = [sum((y[i] - p[i]) * X[i][j] for i in range(n)) - l2 * beta[j] for j in range(d)]
        hess = [[sum(w[i] * X[i][a] * X[i][b] for i in range(n)) +
                 (l2 if a == b else 0.0) for b in range(d)] for a in range(d)]
        # 解 HESS·delta = grad(高斯消元,带主元)
        delta = _solve(hess, grad)
        if any(not math.isfinite(x) for x in delta):
            break
        beta = [b + g for b, g in zip(beta, delta)]
        if all(math.isfinite(b) and abs(b) < 1e6 for b in beta):
            best = beta[:]
    return best


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    """高斯消元求线性方程组(带部分主元)。"""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return [0.0] * n
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))) / M[r][r]
    return x


def predict_prob(X: list[list[float]], beta: list[float]) -> list[float]:
    return [_sigmoid(sum(b * x for b, x in zip(beta, row))) for row in X]


# ---------------------------------------------------------------- purged K-fold

def purged_folds(event_dates: list[date], k: int = 5,
                 purge_days: int = HORIZON + EMBARGO_DAYS) -> list[tuple[list[int], list[int]]]:
    """连续时间 K 折;训练事件与测试事件保持 purge_days 日历日间隔(屏障窗+embargo)。"""
    order = sorted(range(len(event_dates)), key=lambda i: event_dates[i])
    folds = []
    chunk = (len(order) + k - 1) // k
    for f in range(k):
        test_idx = order[f * chunk:(f + 1) * chunk]
        test_days = {event_dates[i] for i in test_idx}
        lo, hi = min(test_days), max(test_days)
        train_idx = [i for i in order
                     if event_dates[i] < lo - timedelta(days=purge_days)
                     or event_dates[i] > hi + timedelta(days=purge_days)]
        folds.append((train_idx, test_idx))
    return folds


# ---------------------------------------------------------------- 特征与事件集

@dataclass
class MetaEvent:
    """一个 [S1] 事件:标签 + point-in-time 特征。"""

    day: date
    label: int | None
    features: dict = field(default_factory=dict)

    def x(self, keys: tuple[str, ...]) -> list[float]:
        """特征向量(缺失中性填充)+ 截距。中性值=各分的无信息水平。"""
        neutral = {"trend": 50.0, "momentum": 50.0, "sentiment": 50.0,
                   "greed": 50.0, "vol_pct": 0.5, "regime": 1.0, "streak_up": 0.0}
        row = [1.0]  # 截距
        for kx in keys:
            v = self.features.get(kx)
            row.append(neutral.get(kx, 0.0) if v is None else float(v))
        return row


def build_events(signal_rows: list[dict], index_bars: list, volp: dict,
                 regime: dict) -> list[MetaEvent]:
    """组装事件集:avoid 信号日 + triple-barrier 标签 + 特征(全 point-in-time)。

    signal_rows = forecast_log 行(含 signal_date/components_json);
    index_bars = [(date, o, h, l, c)] 升序;volp/regime = 逐日字典(claim: as-of 语义)。
    """
    import json as _json

    bar_map = {d: (o, h, l, c) for d, o, h, l, c in index_bars}
    dates = [d for d, *_ in index_bars]
    events: list[MetaEvent] = []
    for row in signal_rows:
        d = date.fromisoformat(row["signal_date"]) if isinstance(row["signal_date"], str) else row["signal_date"]
        if d not in bar_map:
            continue
        comp = _json.loads(row["components_json"]) if row.get("components_json") else {}
        o, h, l, c = bar_map[d]
        sigma = _vol_at(bar_map, dates, d)
        # 竖挡期内逐日 (high, low, close)
        i0 = dates.index(d)
        o_dir = [(bar_map[dates[j]][1], bar_map[dates[j]][2], bar_map[dates[j]][3])
                 for j in range(i0 + 1, min(i0 + 1 + HORIZON, len(dates)))]
        y = triple_barrier_label(c, o_dir, sigma)
        st = regime.get(d) or {}
        ev = MetaEvent(day=d, label=y, features={
            "trend": comp.get("trend"), "momentum": comp.get("momentum"),
            "sentiment": comp.get("sentiment"), "greed": comp.get("greed"),
            "streak_up": comp.get("streak_up"),
            "vol_pct": (volp or {}).get(d), "regime": st.get("regime"),
        })
        events.append(ev)
    return events


def _vol_at(bar_map: dict, dates: list, d: date) -> float | None:
    """事件日的 YZ 波动(用截至当日 21 日窗)。"""
    i = dates.index(d) if d in dates else -1
    if i < 20:
        return None
    yz = yang_zhang_vol([bar_map[dates[j]] for j in range(max(0, i - 40), i + 1)], window=21)
    return yz[-1]
