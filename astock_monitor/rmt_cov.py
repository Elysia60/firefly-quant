# -*- coding: utf-8 -*-
"""rmt_cov.py — P10 RMT 协方差降噪走前对照（2026-11-23 · 预注册实施）

预注册链: 路线图 P10(2026-11-22 登记) → 本实现(2026-11-23,判定补篇如下)。
对照 Laloux–Bouchaud–Potters 1999/2000 经典法;Q=T/N 适定性限定了宇宙规模
(实证文献同口径: N≈T 时 MP 带过宽,全部像噪声)。

预注册补篇(2026-11-23,看结果前写死):
  - 宇宙: hs800 中"前一年日均成交额"前 100 只(逐年 PIT 重选)
  - 相关窗 T=250 交易日 → Q=100/250=0.4(适定);调仓=21 交易日(月频)
  - 变体: minQ(带内本征值→信号均值替换) / clip(带内夹到带上沿)
  - 组合: 清洗后 Σ 的解析最小方差(负权截零重归一);对照=同式 RAW Σ
    ——同公式,只差滤波,隔离滤波效应
  - 成本: 调仓时 Σ|Δw| × round_trip(date)/2(单边);权重按符号字典跟踪
  - 评价: 2024-01-01..2026-11-20;日收益差分 NW t(窗 21),|t|≥2 → 升级注册结论;
    否则负面入册。幸存者偏差: 宇宙=现任成分,已注记。

产出: results/rmt_cov_report.json + 本文件可重放。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import alpha_lite as AL  # noqa: E402
from astock_monitor import cost_schedule as CS  # noqa: E402
from astock_monitor.audit import newey_west_t  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402

TOP_N = 100
CORR_WINDOW = 250
REB_FREQ = 21
START = "2024-01-01"
ANN = 250
VARIANTS = ("minQ", "clip", "base")


def mp_lambda_max(n: int, t: int) -> float:
    """Marchenko-Pastur 相关矩阵本征值上界(相关矩阵口径)。Q=n/t<1。"""
    q = n / max(t, 1)
    if q >= 1:
        return float("inf")
    return (1 + q ** 0.5) ** 2


def denoise_corr(c: np.ndarray, variant: str) -> np.ndarray:
    """Laloux–Bouchaud 去噪: minQ=带内本征值→信号均值替换; clip=夹到带上沿。"""
    w, v = np.linalg.eigh(c)  # 升序
    lam_max = mp_lambda_max(c.shape[0], CORR_WINDOW)
    if variant == "minQ":
        noise = w < lam_max
        replacement = w.mean() if noise.all() else w[~noise].mean()
        w2 = np.where(noise, replacement, w)
    elif variant == "clip":
        w2 = np.clip(w, None, lam_max)
    else:
        raise ValueError(variant)
    c2 = v @ np.diag(w2) @ v.T
    d = np.sqrt(np.diag(c2))
    return c2 / np.outer(d, d)


def minvar_weights(cov: np.ndarray) -> np.ndarray:
    """解析最小方差(无约束解,负权截零后重归一)。纯 numpy。"""
    inv = np.linalg.pinv(cov)
    ones = np.ones(cov.shape[0])
    w = inv @ ones
    s = w.sum()
    if s <= 0:
        return np.full(cov.shape[0], 1.0 / cov.shape[0])
    w = np.clip(w / s, 0, None)
    if w.sum() <= 0:
        return np.full(cov.shape[0], 1.0 / cov.shape[0])
    return w / w.sum()


def run() -> dict:
    cfg = load_config()
    lake = resolve_path(cfg, "paths.cnequity_lake")
    bars = AL.load_bars_complete(Path(lake), min_symbols=700)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars = bars.sort_values(["symbol", "trade_date"])

    # 宇宙: hs800(现任成分,幸存者偏差已注记);裸代码→湖内带后缀
    codes = [l.strip() for l in (REPO_ROOT / "data" / "state" / "hs800_codes.txt")
             .read_text(encoding="utf-8").splitlines() if l.strip()]

    def suffixed(c: str) -> str:
        return c + (".SH" if c.startswith("6") else ".SZ" if c[0] in "03" else ".BJ")

    universe_all = {suffixed(c) for c in codes}
    bars = bars[bars["symbol"].isin(universe_all)]

    close = bars.pivot(index="trade_date", columns="symbol", values="close")
    amount = bars.pivot(index="trade_date", columns="symbol", values="amount")
    close = close.sort_index()
    rets = close.pct_change()

    days = list(close.index)
    start_i = next((i for i, d in enumerate(days) if d >= pd.Timestamp(START)), None)
    if start_i is None:
        return {"error": f"START {START} 早于数据首日 {days[0].date()}"}
    rebal_points = list(range(start_i, len(days) - 1, REB_FREQ))

    port = {v: [] for v in VARIANTS}
    prev_w = {v: {} for v in VARIANTS}
    n_rebal = 0
    for ri, i in enumerate(rebal_points):
        win = rets.iloc[max(0, i - CORR_WINDOW):i]
        amt_win = amount.iloc[max(0, i - ANN):i]
        liq = amt_win.mean().dropna()
        universe = liq.sort_values(ascending=False).head(TOP_N).index
        win = win[list(universe)].dropna(axis=1, how="all").dropna(axis=0, how="any")
        N, T = win.shape[1], win.shape[0]
        if N < 30 or T < 200:
            continue
        c_raw = win.corr().to_numpy()
        vols = win.std().to_numpy() * (ANN ** 0.5)
        cov_raw = vols[:, None] * c_raw * vols[None, :]

        syms = list(win.columns)
        exec_i = i + 1
        if exec_i >= len(days):
            break
        seg_end = rebal_points[ri + 1] if ri + 1 < len(rebal_points) else len(days)
        rt = CS.round_trip_cost(days[exec_i].date())

        for variant in VARIANTS:
            if variant == "base":
                cov_v = cov_raw
            else:
                c_dn = denoise_corr(c_raw, variant)
                cov_v = vols[:, None] * c_dn * vols[None, :]
            w_arr = minvar_weights(cov_v)
            wd = dict(zip(syms, w_arr))
            # 成本: 与上期权重的 L1 差 × 单边成本
            union = set(wd) | set(prev_w[variant])
            turnover = sum(abs(wd.get(s, 0.0) - prev_w[variant].get(s, 0.0))
                           for s in union)
            port[variant].append(-turnover * rt / 2)
            # 持仓期日收益(缺失日 0)
            seg = rets.iloc[exec_i:seg_end][syms].fillna(0.0).to_numpy()
            for dr in seg:
                port[variant].append(float(w_arr @ dr))
            prev_w[variant] = wd
        n_rebal += 1

    def metrics(r: list) -> dict:
        a = np.array(r)
        if len(a) < 10:
            return {"n_days": len(a)}
        ann_ret = a.mean() * ANN
        ann_vol = a.std() * (ANN ** 0.5)
        sharpe = round(ann_ret / ann_vol, 3) if ann_vol > 0 else 0.0
        eq = np.cumprod(1 + a)
        dd = (eq / np.maximum.accumulate(eq) - 1).min()
        return {"ann_ret": round(ann_ret, 4), "ann_vol": round(ann_vol, 4),
                "sharpe": sharpe, "maxdd": round(float(dd), 4), "n_days": len(a)}

    m = {k: metrics(v) for k, v in port.items()}
    n_days = min(len(port[v]) for v in VARIANTS)
    t_tests = {}
    for variant in ("minQ", "clip"):
        d = np.array(port[variant][:n_days]) - np.array(port["base"][:n_days])
        t_tests[f"{variant}_vs_base"] = {"nw_t": round(newey_west_t(list(d), window=21), 3),
                                         "n_days": n_days}
    verdict = ("升级候选" if max(abs(t["nw_t"]) for t in t_tests.values()) >= 2
               else "负面入册(未过 2.0)")
    return {"prereg": {"universe": "hs800 流动性前100(PIT 年选)",
                       "T": CORR_WINDOW, "Q": round(TOP_N / CORR_WINDOW, 2),
                       "rebal_freq": REB_FREQ, "start": START,
                       "end": str(days[-1].date()), "n_rebal": n_rebal,
                       "variants": ["minQ", "clip"],
                       "baseline": "RAW minvar 同式(隔离滤波效应)"},
            "metrics": m, "diff_tests": t_tests, "verdict": verdict,
            "survivor_bias": "宇宙=现任 hs800 成分,已注记"}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rep = run()
    out = REPO_ROOT / "results" / "rmt_cov_report.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("saved", out)
