"""信号引擎:三分项(情绪/趋势/动量)→ 综合分 → 三期判定(csqaq-monitor 公式平移,A 股输入)。

公式正本(csqaq v1.x,数字正本随 METHODS.md §2 演进):
- 趋势分 = 50 + clip((close/SMA20−1)×500, ±20) + clip((50−RSI14)×0.6, ±15)   [实装]
- 情绪分 = A 股情绪源(两融/北向/恐贪)未接入 → 缺数据,按缺口纪律降权标注       [待数据积累]
- 动量分 = breadth×70 + min(连涨,5)×6,breadth=涨跌家数比                       [待 L1 积累]

综合分 = 0.4×动量 + 0.3×情绪 + 0.3×趋势;缺数据分项按可得权重**再归一**,并带 data_quality 标注
(质量问题是标注给决策者,不静默修正分数——csqaq 防泄漏三件套之二)。

防泄漏纪律(csqaq 硬规则「决策只用截至昨日」):
- 第 T 日信号只用 ≤ T−1 收盘的数据;本模块全部函数按此口径实现并有测试钉死。
- 缺口不前向填充:输入序列带缺口时不补数,缺口信息进 data_quality。

三期判定(v1.0 规则的指数版):连涨≥3 → 买入关注;连跌≥2 → 回避关注;否则震荡。
**置信分层:全部 tier=观察级**——按 [C2] 教训(中性跟随扣成本净亏),没有对账样本前不给行动级。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date

# 逻辑正本:csqaq 情绪分锚点线性插值 [(0,100),(40,85),(60,55),(80,25),(100,5)]
SENTIMENT_ANCHORS = [(0, 100), (40, 85), (60, 55), (80, 25), (100, 5)]

COMPOSITE_WEIGHTS = {"momentum": 0.4, "sentiment": 0.3, "trend": 0.3}


@dataclass
class DataQuality:
    """数据质量标注(csqaq:信号携带质量字段,缺口≥5 天顶部横幅)。"""

    breadth: str = "missing"       # missing / ok
    sentiment: str = "missing"
    gap_days: int = 0              # 输入序列内最大相邻缺口(交易日)
    banner: str = ""               # 缺口≥5 天时给横幅

    def as_dict(self) -> dict:
        return {"breadth": self.breadth, "sentiment": self.sentiment,
                "gap_days": self.gap_days, "banner": self.banner}


@dataclass
class Signal:
    """单日信号:全部字段可对账、可回放。"""

    signal_date: date
    trend_score: float
    composite: float
    verdict: str                   # buy_watch / avoid_watch / neutral
    tier: str = "观察"             # 无对账样本前恒为观察级
    components: dict = field(default_factory=dict)
    data_quality: DataQuality = field(default_factory=DataQuality)

    def as_dict(self) -> dict:
        return {"signal_date": self.signal_date, "trend_score": self.trend_score,
                "composite": round(self.composite, 2), "verdict": self.verdict,
                "tier": self.tier, "components": self.components,
                "data_quality": self.data_quality.as_dict()}


# ---------------------------------------------------------------- 基础指标(O(n))

def sma(values: list[float], n: int) -> float | None:
    """末位 SMA(n);样本不足返回 None(O(n) 滚动窗,csqaq v1.8 教训)。"""
    if n <= 0 or len(values) < n:
        return None
    window = deque(values[:n], maxlen=n)
    total = sum(window)
    for v in values[n:]:
        left = window[0]
        window.append(v)
        total += v - left
    return total / n


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder RSI(与 csqaq RSI14 同口径);样本不足 n+1 返回 None。"""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        chg = closes[i] - closes[i - 1]
        gains += max(chg, 0.0)
        losses += max(-chg, 0.0)
    avg_gain, avg_loss = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        chg = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(chg, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-chg, 0.0)) / n
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def trend_score(close: float, sma20: float | None, rsi14: float | None) -> float | None:
    """csqaq 趋势分公式;任一输入缺失返回 None(不静默造分)。"""
    if sma20 is None or rsi14 is None or sma20 == 0:
        return None
    return 50.0 + clip((close / sma20 - 1.0) * 500.0, -20.0, 20.0) + clip((50.0 - rsi14) * 0.6, -15.0, 15.0)


def sentiment_score(greed_index: float | None) -> float | None:
    """贪婪指数 → 情绪分(反向:贪婪=高分危险)。锚点线性插值,csqaq v1.0 正本。"""
    if greed_index is None:
        return None
    pts = SENTIMENT_ANCHORS
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= greed_index <= x1:
            return y0 + (y1 - y0) * (greed_index - x0) / (x1 - x0)
    return pts[-1][1] if greed_index > pts[-1][0] else pts[0][1]


def momentum_score(breadth_ratio: float | None, streak_up: int) -> float | None:
    """csqaq 动量分公式;breadth 缺失时返回 None(streak 单独可用也不造分)。"""
    if breadth_ratio is None:
        return None
    return clip(breadth_ratio * 70.0 + min(streak_up, 5) * 6.0, 0.0, 100.0)


# ---------------------------------------------------------------- 三分项合成

def composite_score(parts: dict[str, float | None],
                    weights: dict[str, float] = COMPOSITE_WEIGHTS) -> tuple[float, dict]:
    """缺数据分项按可得权重再归一;全部缺失返回 50(中性)并标注。"""
    got = {k: v for k, v in parts.items() if v is not None}
    if not got:
        return 50.0, {"renormalized": False, "missing": list(weights)}
    w_total = sum(weights[k] for k in got)
    score = sum(parts[k] * weights[k] for k in got) / w_total
    return score, {"renormalized": len(got) < len(weights),
                   "missing": [k for k in weights if k not in got]}


def verdict_of(closes: list[float], composite: float) -> str:
    """三期判定(指数版 v1.0 规则):连涨≥3→buy_watch;连跌≥2→avoid_watch;否则 neutral。"""
    if len(closes) < 3:
        return "neutral"
    def streak(sign: int) -> int:
        k = 0
        for i in range(len(closes) - 1, 0, -1):
            chg = closes[i] - closes[i - 1]
            if (chg > 0) == (sign > 0) and chg != 0:
                k += 1
            else:
                break
        return k
    if streak(+1) >= 3 and composite >= 55:
        return "buy_watch"
    if streak(-1) >= 2 or composite <= 35:
        return "avoid_watch"
    return "neutral"


def max_gap_days(dates: list[date]) -> int:
    """相邻信号日的最大缺口(按日历日计,仅用于质量横幅,不参与计算)。"""
    if len(dates) < 2:
        return 0
    return max((b - a).days for a, b in zip(dates, dates[1:]))


# ---------------------------------------------------------------- 主入口

def generate_signal(index_rows: list[tuple[date, float]], signal_date: date) -> Signal:
    """生成 signal_date 的指数信号。

    防泄漏:**只用 trade_date < signal_date 的收盘**(决策只用截至昨日)。
    index_rows = [(date, close)] 升序,允许有缺口(缺口进质量标注,不填充)。
    """
    hist = [(d, c) for d, c in index_rows if d < signal_date]
    dates = [d for d, _ in hist]
    closes = [c for _, c in hist]
    if len(closes) < 21:
        raise ValueError(f"截至 {signal_date} 的历史不足 21 个交易日({len(closes)}),拒绝出信号")
    sma20 = sma(closes, 20)
    rsi14 = rsi(closes, 14)
    ts = trend_score(closes[-1], sma20, rsi14)
    comp, meta = composite_score({"trend": ts})
    q = DataQuality(gap_days=max_gap_days(dates[-60:]))
    if q.gap_days >= 5:
        q.banner = f"数据缺口 {q.gap_days} 天,趋势分可信度降级(csqaq 缺口纪律)"
    verdict = verdict_of(closes, comp)
    return Signal(signal_date=signal_date, trend_score=round(ts, 2), composite=comp,
                  verdict=verdict,
                  components={"trend": round(ts, 2), "renormalized": meta["renormalized"],
                              "missing": meta["missing"]},
                  data_quality=q)


def load_index_closes(lake_dir: str | Path, symbol: str = "000300.SH") -> list[tuple[date, float]]:
    """从湖读指数收盘(升序);惰性导入 pandas。"""
    import pandas as pd  # noqa: PLC0415
    from pathlib import Path as _P

    files = sorted(_P(lake_dir).glob("curated/index_bars/**/*.parquet"))
    if not files:
        raise FileNotFoundError(f"湖内无 index_bars: {lake_dir}")
    df = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date", "close"]) for f in files),
                   ignore_index=True)
    df = df[df["symbol"] == symbol].drop_duplicates("trade_date").sort_values("trade_date")
    return [(d.date() if hasattr(d, "date") else d, float(c))
            for d, c in zip(df["trade_date"], df["close"])]
