"""组合构建层(P5 终版):从 LightGBM 预测分 → 目标持仓权重。

三步:
  1. TopK 筛选:预测分最高的 K 只
  2. 逆波动率加权:波动越低权重越高(risk parity 简化版)
  3. 约束:单票 ≤35%(B 站实测惯例)+ regime 缩放(bear→全仓×0.3)

设计纪律:
  · 不用 cvxpy/优化器——东方证券研报实证:分层 TopK 拿到优化器大部分超额
  · 单票上限是硬约束(防黑天鹅集中)
  · regime 缩放是 [S1]+[S8] 的落地: bear 庭空仓/缩仓,neutral 正常
  · 输出 = {symbol: weight} 字典,可直接用于回测或模拟盘
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from . import limits as LIM
from . import regime as R

TOPK_DEFAULT = 50
SINGLE_CAP = 0.35
REGIME_SCALE = {R.BULL: 1.0, R.NEUTRAL: 1.0, R.BEAR: 0.3}
MIN_PRED_RANK = 0.5  # 预测分低于中位数的股票不入选


def select_portfolio(
    day_predictions: pd.DataFrame,
    regime_state: int = R.NEUTRAL,
    topk: int = TOPK_DEFAULT,
    single_cap: float = SINGLE_CAP,
    vol_window: int = 20,
) -> dict[str, float]:
    """从 LightGBM 逐日预测构建目标组合。

    day_predictions 需含列: symbol, pred(预测分), vol_20(20 日收益率标准差)
    regime_state: R.BULL(0) / R.NEUTRAL(1) / R.BEAR(2)
    返回: {symbol: weight} 字典(权重和 = regime_scale,而非强制 1.0)
    """
    if day_predictions.empty:
        return {}

    scale = REGIME_SCALE.get(regime_state, 1.0)
    df = day_predictions.copy()

    # 1) TopK 筛选:预测分最高的 K 只
    df = df.sort_values("pred", ascending=False)
    topk = df.head(topk)

    # 2) 逆波动率加权(波动越低权重越高)
    vol_col = f"vol_{vol_window}"
    if vol_col in topk.columns:
        topk = topk.copy()
        topk["inv_vol"] = 1.0 / topk[vol_col].where(topk[vol_col] > 0, 0.02)
    else:
        topk["inv_vol"] = 1.0

    total_inv_vol = topk["inv_vol"].sum()
    if total_inv_vol <= 0:
        return {}

    topk["raw_weight"] = topk["inv_vol"] / total_inv_vol

    # 3) 单票上限(迭代裁剪:超限的份额按比例分给未超限的)
    weights = dict(zip(topk["symbol"], topk["raw_weight"]))
    for _ in range(5):  # 最多裁 5 轮
        over = {s: w for s, w in weights.items() if w > single_cap}
        if not over:
            break
        excess = sum(w - single_cap for w in over.values())
        under = {s: w for s, w in weights.items() if w <= single_cap}
        under_total_inv = sum(1.0 for _ in under)  # 均分
        if not under or excess <= 0:
            for s in over:
                weights[s] = single_cap
            break
        for s in over:
            weights[s] = single_cap
        add_each = excess / max(1, len(under))
        for s in under:
            if weights[s] + add_each < single_cap:
                weights[s] += add_each

    # 4) regime 缩放
    scaled = {s: w * scale for s, w in weights.items()}
    return scaled


def portfolio_changes(
    old: dict[str, float], new: dict[str, float]
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """对比新旧持仓,返回 (新增, 减少, 调整)。"""
    added = {s: w for s, w in new.items() if s not in old}
    removed = {s: w for s, w in old.items() if s not in new}
    adjusted = {
        s: new[s] - old[s]
        for s in new.keys() & old.keys()
        if abs(new[s] - old[s]) > 0.005  # >0.5% 才算调整
    }
    return added, removed, adjusted


def portfolio_summary(positions: dict[str, float]) -> dict:
    """组合摘要:股票数/总仓位/前 5 大持仓。"""
    total = sum(positions.values())
    top5 = dict(sorted(positions.items(), key=lambda x: -x[1])[:5])
    return {
        "n_stocks": len(positions),
        "total_weight": round(total, 4),
        "top5": {s: round(w, 4) for s, w in top5.items()},
        "concentration": round(max(positions.values()) / total, 4) if total > 0 else 0,
    }
