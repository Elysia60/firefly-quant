# -*- coding: utf-8 -*-
"""candidates.py — 日线候选层（2026-11-22 · [S7] LightGBM 基线的操作化接线）

定位（注册表纪律,写给未来的自己）:
  [S7] 是**候选·边缘**级结论(OOS Rank IC +0.058,NW t=+1.96 未过 2.0;
  2025 失效年 −0.014 如实在册)。本模块把那条研究管线操作化成每日候选名单——
  **候选级,不是荐股**;名单必须带 [S7] 的警示头(边缘/失效年),不许摘出来单独吹。

与 [S7] 同源(8 条清单逐条保持):
  1. 标签单一函数 alpha_lite.forward_label      2. y=每日截面 pct-rank
  3. 特征=9 因子逐日截面                          4. 训练=expanding(线上无 purge 需求,
     因为预测日 label 不存在,天然无泄漏)
  5. 早停=验证集 Rank IC                          6. 5 种子集成
  7. 可交易性过滤(0.95×板块限幅)                 8. 本 JSON 即记分牌

用法:
  python -m astock_monitor.cli candidates [--topk 10]   # 产出 data/state/candidates_latest.json
  决策简报自动消费(候选级名单 + [S7] 警示头)。
"""
from __future__ import annotations

import json
import sqlite3  # noqa: F401 (与 forecast 生态一致性占位)
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import alpha_lite as AL
from . import limits as LIM

REPO_ROOT = Path(__file__).resolve().parents[2]
FEAT = ["KMID", "KSFT", "ROC5", "ROC20", "STD20", "RSV20", "CORR20", "CNTP20", "VMA20"]
HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
PARAMS = {"objective": "regression", "metric": "l2", "learning_rate": 0.05,
          "num_leaves": 31, "max_depth": 5, "min_data_in_leaf": 500,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 1.0, "max_bin": 128, "verbose": -1}
S7_DISCLAIMER = ("[S7] 候选·边缘级:OOS Rank IC +0.058(NW t=+1.96 未过 2.0),"
                 "2025 失效年(−0.014)如实入册——候选名单非荐股,失效即弃")


def _panel_and_label(lake: Path, min_symbols: int = 700) -> tuple:
    """与 lgbm_baseline.main 同源:完整天 → 因子面板 → 前向标签。"""
    bars = AL.load_bars_complete(lake, min_symbols=min_symbols)
    panel = AL.compute_factor_panel(bars)
    closes = bars[["symbol", "trade_date", "close"]]
    panel = AL.forward_label(panel, closes, horizon=HORIZON)
    return panel, bars


def _tradability_mask(panel: pd.DataFrame, bars_raw: pd.DataFrame) -> pd.DataFrame:
    """清单 #7:剔除 t→t+1 触及涨跌停样本(0.95×限幅近似)。与基线同实现。"""
    bars = bars_raw[["symbol", "trade_date", "close"]].copy()
    bars = bars.rename(columns={"trade_date": "date"})
    bars["date"] = pd.to_datetime(bars["date"])
    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = bars.groupby("symbol", sort=False)
    bars["next_ret"] = g["close"].shift(-1) / bars["close"] - 1
    lim = bars["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
    bars["untradeable"] = bars["next_ret"].abs() >= lim
    return panel.merge(bars[["symbol", "date", "untradeable"]],
                       left_on=["symbol", "date"], right_on=["symbol", "date"],
                       how="left")


def daily_candidates(lake: Path, topk: int = 10,
                     min_train_days: int = 500,
                     asof: str | None = None) -> dict:
    """训练(全部 <asof 的历史) → 预测最新日 → TopK 候选(逆波动率加权)。

    返回 {as_of, n_train, candidates: [{symbol, pred, weight}], meta}。
    fail 语义:数据不足 → {"error": ...},不造数。
    """
    t0 = time.time()
    print("[candidates] 1/4 加载 bars+面板...", flush=True)
    panel, bars_raw = _panel_and_label(lake)
    print(f"[candidates] 2/4 面板就绪 {len(panel)} 行 {round(time.time()-t0,1)}s", flush=True)
    panel = _tradability_mask(panel, bars_raw)
    panel = panel[~panel["untradeable"].fillna(False)]
    panel["y"] = panel.groupby("date")["label_raw"].rank(pct=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel[FEAT] = panel[FEAT].astype("float32")

    days = sorted(panel["date"].unique())
    pred_day = pd.Timestamp(asof) if asof else days[-1]
    train = panel[panel["date"] < pred_day].dropna(subset=FEAT + ["y"])
    predict_df = panel[panel["date"] == pred_day].dropna(subset=FEAT)
    n_train_days = train["date"].nunique()
    if n_train_days < min_train_days or predict_df.empty:
        return {"error": f"训练日 {n_train_days}(<{min_train_days}) 或预测日无样本"}

    # 92/8 内部切分做早停(与基线同构)
    split_at = int(len(train) * 0.92)
    vtrain, valid = train.iloc[:split_at], train.iloc[split_at:]

    import lightgbm as lgb  # noqa: PLC0415
    dtr = lgb.Dataset(vtrain[FEAT], vtrain["y"])
    dva = lgb.Dataset(valid[FEAT], valid["y"], reference=dtr)

    def feval(preds, dataset):
        dd = valid["date"].values
        df = pd.DataFrame({"p": preds, "y": valid["y"].values, "d": dd}).dropna()
        if df.empty:
            return "rank_ic", 0.0, True
        df["rp"] = df.groupby("d")["p"].rank()
        df["ry"] = df.groupby("d")["y"].rank()
        g = df.groupby("d")
        cov = g.apply(lambda x: ((x["rp"] - x["rp"].mean()) * (x["ry"] - x["ry"].mean())).mean())
        ic = (cov / (g["rp"].std() * g["ry"].std())).dropna()
        return "rank_ic", (float(ic.mean()) if len(ic) else 0.0), True

    print(f"[candidates] 3/4 训练集 {len(train)} 行/{n_train_days} 日,开始 5 种子 LGBM...", flush=True)
    preds_seeds = []
    for seed in SEEDS:
        params = dict(PARAMS)
        params.update({"seed": seed, "bagging_seed": seed,
                       "feature_fraction_seed": seed})
        booster = lgb.train(params, dtr, num_boost_round=400,
                            valid_sets=[dva], feval=feval,
                            callbacks=[lgb.early_stopping(30, verbose=False)])
        preds_seeds.append(booster.predict(predict_df[FEAT],
                                           num_iteration=booster.best_iteration or 400))
    predict_df = predict_df.copy()
    predict_df["pred"] = np.mean(preds_seeds, axis=0)

    # TopK + 逆波动率权重(STD20 是日收益标准差——越低权重越高;为 0/缺失 → 等权)
    top = predict_df.sort_values("pred", ascending=False).head(topk * 2).copy()
    top = top[top["STD20"] > 0].head(topk)
    if top.empty:
        return {"error": "过滤后无候选"}
    inv = 1.0 / top["STD20"]
    top["weight"] = (inv / inv.sum()).round(4)

    t1 = time.time()
    print(f"[candidates] 4/4 完成 {round(t1-t0,1)}s", flush=True)
    return {
        "as_of": pred_day.date().isoformat(),
        "n_train_rows": int(len(train)), "n_train_days": int(n_train_days),
        "candidates": [{"symbol": r.symbol, "pred": round(float(r.pred), 5),
                        "weight": float(r.weight), "std20": round(float(r.STD20), 5)}
                       for r in top.itertuples()],
        "meta": {"seeds": SEEDS, "horizon": HORIZON, "elapsed_s": round(t1 - t0, 1),
                 "grade": "候选·边缘([S7])", "disclaimer": S7_DISCLAIMER},
    }
