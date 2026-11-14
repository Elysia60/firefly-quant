#!/usr/bin/env python3
"""[P5] LightGBM 基线(8 条检查清单逐条执行,2026-11-13 调研定案)。

1. 标签单一函数:label_raw = close[t+21]/close[t+1]−1(alpha_lite.forward_label,与 IC/回测同源)
2. 超额+截面 rank:y = 每日 label_raw 的 pct-rank(excess 的秩 = raw 的秩,Spearman 不变量)
3. 预处理:MVP 因子已逐日截面构造(无跨期统计量);RankNorm 免去极值(清单允许)
4. 切分:3 个 expanding 折,test 前 purge+embargo 25 个交易日(≥2×horizon)
5. 早停=验证集逐日 Rank IC(自定义 feval,向量化)
6. 保守参数+5 种子集成
7. 可交易性:剔除 t→t+1 触及涨跌停的样本(近似:|次日收益|≥0.95×板块限幅)
8. 模型记分牌:本 JSON 即记录(数据窗口/特征/超参/种子/各折 IC)

产出:results/lgbm_baseline.json。诚实预期:9 因子单 IC 全噪音级,组合 IC 能到
0.02-0.04 就算合格基线;到不了也如实登记。
"""
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import lightgbm as lgb  # noqa: E402

from astock_monitor import alpha_lite as AL  # noqa: E402
from astock_monitor import limits as LIM  # noqa: E402
from astock_monitor.audit import newey_west_t  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
FEAT = ["KMID", "KSFT", "ROC5", "ROC20", "STD20", "RSV20", "CORR20", "CNTP20", "VMA20"]
HORIZON = 20
SEEDS = [7, 42, 2024, 2025, 2026]
FOLDS = [("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31"),
         ("2026-01-01", "2026-11-12")]
PARAMS = {"objective": "regression", "metric": "l2", "learning_rate": 0.05,
          "num_leaves": 31, "max_depth": 5, "min_data_in_leaf": 500,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
          "lambda_l2": 1.0, "max_bin": 128, "verbose": -1}


def daily_rank_ic(preds: pd.Series, labels: pd.Series, dates: pd.Series) -> pd.Series:
    """向量化逐日截面 Rank IC(每期一组,组内秩相关)。"""
    df = pd.DataFrame({"p": preds, "y": labels, "d": dates})
    df = df.dropna()
    df["rp"] = df.groupby("d")["p"].rank()
    df["ry"] = df.groupby("d")["y"].rank()
    df["xy"] = df["rp"] * df["ry"]
    g = df.groupby("d")
    cov = g["xy"].mean() - g["rp"].mean() * g["ry"].mean()
    ic = cov / (g["rp"].std() * g["ry"].std())
    return ic.dropna()


def ic_feval_valid_factory(valid: pd.DataFrame):
    """早停 feval:验证集逐日 Rank IC 均值(清单 #5)。闭包捕获验证集日期。"""
    vd = valid["date"].values

    def feval(preds, dataset):
        ic = daily_rank_ic(pd.Series(preds), pd.Series(valid["y"].values),
                           pd.Series(vd))
        if len(ic) == 0:
            return "rank_ic", 0.0, True
        return "rank_ic", float(ic.mean()), True
    return feval


def main() -> int:
    bars = AL.load_bars_complete(lake, min_symbols=700)
    print(f"完整天: {len(bars)} 行 {bars['trade_date'].min()}~{bars['trade_date'].max()}")
    panel = AL.compute_factor_panel(bars)
    closes = bars[["symbol", "trade_date", "close"]]
    panel = AL.forward_label(panel, closes, horizon=HORIZON)

    # 清单 #7:可交易性过滤——t→t+1 触及涨跌停(近似:|次日收益|≥0.95×限幅)的样本剔除
    bars_sorted = bars.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    bars_sorted["trade_date"] = pd.to_datetime(bars_sorted["trade_date"])
    g = bars_sorted.groupby("symbol", sort=False)
    bars_sorted["next_ret"] = g["close"].shift(-1) / bars_sorted["close"] - 1
    lim = bars_sorted["symbol"].map(lambda c: LIM.limit_pct(c) * 0.95)
    bars_sorted["untradeable"] = bars_sorted["next_ret"].abs() >= lim
    ut = bars_sorted[["symbol", "trade_date", "untradeable"]]
    panel = panel.merge(ut, left_on=["symbol", "date"], right_on=["symbol", "trade_date"],
                        how="left")
    panel = panel[~panel["untradeable"].fillna(False)]

    # 清单 #2:y = 每日截面 pct-rank(excess 的秩 = raw 的秩)
    panel["y"] = panel.groupby("date")["label_raw"].rank(pct=True)
    df = panel.dropna(subset=FEAT + ["y"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    print(f"建模样本: {len(df)} 行,{df['date'].min().date()}~{df['date'].max().date()}")

    days = sorted(df["date"].unique())
    day_pos = {d: i for i, d in enumerate(days)}
    report = {"folds": [], "params": PARAMS, "seeds": SEEDS, "features": FEAT,
              "label": "close[t+21]/close[t+1]-1 的每日截面 pct-rank",
              "untradeable_filter": "0.95×板块限幅近似"}

    pooled_pred, pooled_true, pooled_date = [], [], []
    for t_start, t_end in FOLDS:
        ts = pd.Timestamp(t_start)
        te = pd.Timestamp(t_end)
        test_days = [d for d in days if ts <= d <= te]
        if len(test_days) < 60:
            continue
        # 清单 #4:purge+embargo 25 个交易日(≥2×horizon 20)
        first_test_idx = day_pos[test_days[0]]
        train_max = days[max(0, first_test_idx - 25)]
        train = df[df["date"] <= train_max]
        if len(train) < 50000:
            report["folds"].append({"fold": t_start, "skipped": "训练样本不足"})
            continue
        split_at = int(len(train) * 0.92)
        vtrain, valid = train.iloc[:split_at], train.iloc[split_at:]
        test = df[df["date"].isin(set(test_days))]

        dtr = lgb.Dataset(vtrain[FEAT], vtrain["y"])
        dva = lgb.Dataset(valid[FEAT], valid["y"], reference=dtr)
        feval = ic_feval_valid_factory(valid)
        preds_seeds = []
        best_iters = []
        for seed in SEEDS:
            params = dict(PARAMS)
            params.update({"seed": seed, "bagging_seed": seed,
                           "feature_fraction_seed": seed})
            booster = lgb.train(params, dtr, num_boost_round=400,
                                valid_sets=[dva], feval=feval,
                                callbacks=[lgb.early_stopping(30, verbose=False)])
            best_iters.append(booster.best_iteration or 400)
            preds_seeds.append(booster.predict(test[FEAT],
                                               num_iteration=booster.best_iteration))
        pred = np.mean(preds_seeds, axis=0)
        ic = daily_rank_ic(pd.Series(pred), pd.Series(test["y"].values),
                           pd.Series(test["date"].values))
        t_stat = newey_west_t(list(ic.values), window=HORIZON)
        # 十分位价差(净额注记:top−bottom 未扣费,回合成本 0.2%)
        tdf = pd.DataFrame({"d": test["date"].values, "p": pred,
                            "label": test["label_raw"].values})
        tdf["dec"] = tdf.groupby("d")["p"].transform(
            lambda s: pd.qcut(s.rank(method="first"), 10, labels=False))
        dec = tdf.groupby("dec")["label"].mean()
        spread = float(dec.iloc[9] - dec.iloc[0])
        report["folds"].append({
            "test": [t_start, t_end], "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "best_iters": best_iters,
            "oos_mean_rank_ic": round(float(ic.mean()), 5),
            "oos_ic_ir": round(float(ic.mean() / ic.std()), 3) if ic.std() > 0 else 0.0,
            "nw_t": round(t_stat, 3),
            "decile_spread": round(spread, 5),
            "decile_spread_net": round(spread - 0.002, 5),
        })
        pooled_pred += list(pred)
        pooled_true += list(test["y"].values)
        pooled_date += list(test["date"].values)
        print(f"折 {t_start}~{t_end}: OOS RankIC {ic.mean():+.4f} (t={t_stat:+.2f}), "
              f"十分位价差 {spread:+.4f}")

    pic = daily_rank_ic(pd.Series(pooled_pred), pd.Series(pooled_true),
                        pd.Series(pooled_date))
    pt = newey_west_t(list(pic.values), window=HORIZON)
    report["pooled"] = {"n_days": int(len(pic)),
                        "mean_rank_ic": round(float(pic.mean()), 5),
                        "nw_t": round(pt, 3),
                        "ic_gt_0_ratio": round(float((pic > 0).mean()), 3)}
    imp = []
    out_path = REPO_ROOT / "results" / "lgbm_baseline.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["pooled"], ensure_ascii=False))
    print("saved", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
