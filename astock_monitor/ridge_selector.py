# -*- coding: utf-8 -*-
"""ridge_selector.py — Ridge 选股器（2026-11-23 · 路线图第8周 · 预注册纪律）

与 [S7] LightGBM 同数据/同宇宙/同标签/同成本——唯一差异=模型家族(Ridge vs LGBM)。
目的: 第二模型视角交叉验证——若 Ridge 与 LGBM 结论一致 → 加固;不一致 → 模型选择敏感。

预注册(写死):
  - 特征: 13 因子(9 价量 + Beta/RSTR/DASTD/Amihud,[S7]-Barra 确认)
  - 标签: close[t+21]/close[t+1]-1 的每日截面 pct-rank(同 [S7])
  - 模型: Ridge(alpha=1.0,正解无早停)——线性模型,系数可读
  - 可交易性: 0.95×限幅过滤(同 [S7])
  - 宇宙: hs800 当前成分(幸存者偏差注记)
  - 窗口: 2024-01-01~2026-11-20(同 [S7] 区间)
  - 成本: round_trip_cost(date)
  - 判定: OOS Rank IC NW t≥2 → 候选;否则负面入册
  - DSR: +1(Ridge) +1(Ridge vs LGBM 对比)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import alpha_lite as AL  # noqa: E402
from astock_monitor import cost_schedule as CS  # noqa: E402
from astock_monitor.audit import newey_west_t  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402

FEAT = ["KMID", "KSFT", "ROC5", "ROC20", "STD20", "RSV20", "CORR20",
        "CNTP20", "VMA20", "RSTR", "DASTD", "AMIHUD", "vol_pct"]
HORIZON = 20
ALPHA = 1.0


def daily_rank_ic(preds: pd.Series, labels: pd.Series, dates: pd.Series) -> pd.Series:
    df = pd.DataFrame({"p": preds, "y": labels, "d": dates}).dropna()
    df["rp"] = df.groupby("d")["p"].rank()
    df["ry"] = df.groupby("d")["y"].rank()
    g = df.groupby("d")
    cov = g["xy"].mean() if "xy" in df.columns else None
    df["xy"] = df["rp"] * df["ry"]
    g = df.groupby("d")
    cov = g["xy"].mean() - g["rp"].mean() * g["ry"].mean()
    ic = cov / (g["rp"].std() * g["ry"].std())
    return ic.dropna()


def run() -> dict:
    t0 = time.time()
    cfg = load_config()
    lake = resolve_path(cfg, "paths.cnequity_lake")
    bars = AL.load_bars_complete(Path(lake), min_symbols=700)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars = bars.sort_values(["symbol", "trade_date"])

    # 宇宙过滤(hs800)
    codes = [l.strip() for l in (REPO_ROOT / "data" / "state" / "hs800_codes.txt")
             .read_text(encoding="utf-8").splitlines() if l.strip()]

    def suffixed(c):
        return c + (".SH" if c.startswith("6") else ".SZ" if c[0] in "03" else ".BJ")

    bars = bars[bars["symbol"].isin({suffixed(c) for c in codes})]

    panel = AL.compute_factor_panel(bars)
    closes = bars[["symbol", "trade_date", "close"]]
    panel = AL.forward_label(panel, closes, horizon=HORIZON)

    # 可交易性过滤
    bars_sorted = bars.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    g = bars_sorted.groupby("symbol", sort=False)
    bars_sorted["next_ret"] = g["close"].shift(-1) / bars_sorted["close"] - 1
    lim = bars_sorted["symbol"].map(lambda c: 0.095)
    bars_sorted["untradeable"] = bars_sorted["next_ret"].abs() >= lim
    ut = bars_sorted[["symbol", "trade_date", "untradeable"]]
    panel = panel.merge(ut, left_on=["symbol", "date"], right_on=["symbol", "trade_date"],
                        how="left")
    panel = panel[~panel["untradeable"].fillna(False)]

    # 清单 #2: y = 每日截面 pct-rank
    panel["y"] = panel.groupby("date")["label_raw"].rank(pct=True)
    avail = [f for f in FEAT if f in panel.columns]
    df = panel.dropna(subset=avail + ["y"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    print(f"[ridge] 样本: {len(df)} 行 {df['date'].min().date()}~{df['date'].max().date()}")

    # expanding walk-forward: 每月重训,预测下月
    days = sorted(df["date"].unique())
    month_keys = sorted(set(d.strftime("%Y-%m") for d in days))
    test_months = [m for m in month_keys if m >= "2024-01"]

    all_preds, all_labels, all_dates = [], [], []
    for m_key in test_months:
        test_mask = df["date"].dt.strftime("%Y-%m") == m_key
        test = df[test_mask]
        train = df[~test_mask & (df["date"] < test["date"].min())]
        if len(train) < 5000 or len(test) < 10:
            continue
        model = Ridge(alpha=ALPHA)
        model.fit(train[avail], train["y"])
        preds = model.predict(test[avail])
        all_preds.extend(preds)
        all_labels.extend(test["y"].values)
        all_dates.extend(test["date"].values)

    if not all_preds:
        return {"error": "无预测产出"}

    preds_s = pd.Series(all_preds)
    labels_s = pd.Series(all_labels)
    dates_s = pd.Series(all_dates)
    ic = daily_rank_ic(preds_s, labels_s, dates_s)
    t_stat = newey_west_t(list(ic.values), window=HORIZON)

    # 系数(模型可解释性——Ridge 独有优势)
    model_full = Ridge(alpha=ALPHA)
    model_full.fit(df[avail], df["y"])
    coefs = dict(zip(avail, model_full.coef_.round(4)))

    elapsed = round(time.time() - t0, 1)
    mean_ic = round(float(ic.mean()), 5)
    verdict = ("候选" if abs(t_stat) >= 2 else "负面入册")

    return {
        "model": f"Ridge(alpha={ALPHA})",
        "features": avail,
        "n_train_total": len(df),
        "n_test_days": len(ic),
        "oos_mean_rank_ic": mean_ic,
        "nw_t": round(t_stat, 3),
        "ic_gt_0_ratio": round(float((ic > 0).mean()), 3),
        "top_coefs": dict(sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True)[:5]),
        "verdict": verdict,
        "elapsed_s": elapsed,
        "compare_S7": "[S7] LGBM: IC +0.058 t=1.96 → Ridge 对比见报告",
        "disclaimer": "预注册纪律:判定写死,负面入册,DSR+1"
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rep = run()
    out = REPO_ROOT / "results" / "ridge_selector_report.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("saved", out)
