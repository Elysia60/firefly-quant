"""税制成本表 — 印花税分段历史(曼昆精读 9.2 行动项5:成本模型应带生效日期)。

背景:A 股印花税不是常数——
  · 2008-09-19 起:由双边征收改为**卖出单边 1‰**(此前 1998 起双边 4‰,2008-04-24 降 3‰)
  · 2023-08-28 起:减半至**卖出单边 0.5‰**
萤火现行 cost_round_trip=0.002 是"佣金(双边~0.25‰×2)+印花税(卖出)+缓冲"的总口径,
且**未分段**——2014 起的回测样本横跨 2023-08-28 税制变更点,同一路径用了两个税制
下的同一成本。本模块提供分段查询,供回测在跨税制点时切换(诚实修复,方向上只会
让 2023-08-28 前样本的成本更高 → [S15] 类负面结论方向性加固)。

口径(与注册表 [S15] 总成本对齐):
  round_trip(date) = base(佣金双边+滑点缓冲,默认 0.0015) + stamp(date)
  stamp: <2008-09-19 → 0.002(双边 1‰);2008-09-19~2023-08-27 → 0.001(卖出 1‰);
         ≥2023-08-28 → 0.0005(卖出 0.5‰)
  → 2023-08-28 后 = 0.002(与注册表现值一致);之前 = 0.0025 / 0.0035
"""
from __future__ import annotations

import datetime as dt
from datetime import date

STAMP_HISTORY = (
    (date(2008, 9, 19), 0.001),   # 2008-09-19 起:双边 1‰ → 卖出单边 1‰(往返 0.002→0.001)
    (date(2023, 8, 28), 0.0005),  # 2023-08-28 起:减半至卖出单边 0.5‰
)
STAMP_BEFORE = 0.002              # 2008-09-19 前:双边 1‰ → 往返 0.002
BASE = 0.0015                     # 佣金(双边 0.25‰×2)+滑点缓冲,非税部分


def stamp_rate(on_date: date) -> float:
    """印花税往返成分(往返口径)。取生效日 ≤ 当日的最近一档。"""
    d = on_date
    if not isinstance(d, dt.date):
        raise TypeError(f"需要 date,得到 {type(d).__name__}")
    eff = STAMP_BEFORE
    for since, rate in STAMP_HISTORY:
        if d >= since:
            eff = rate
        else:
            break
    return eff


def round_trip_cost(on_date: date, base: float = BASE) -> float:
    """分段往返成本 = base(佣金+滑点) + 印花税成分。"""
    return round(base + stamp_rate(on_date), 6)
