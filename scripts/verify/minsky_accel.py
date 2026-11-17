#!/usr/bin/env python3
"""[S18] 候选实验:明斯基加速度——两融斜率的二阶导对 T+20 前向收益的预测力。

理论来源:《逃不开的经济周期》(特维德)——明斯基"稳定孕育不稳定":杠杆周期
    对冲融资→投机融资→庞氏融资,拐点(从加速到减速)=明斯基时刻。
    [S13] 已证:两融 30 日斜率是前导指标(降杠杆期后 20 日 −1.11% vs 加杠杆 +1.34%)。
    本实验升级一阶:斜率→加速度(二阶导),检验"杠杆拐点"是否有超越斜率本身的信息。

预注册判定(写死,跑完不改):
  · 四桶(斜率×加速度) T+20 前向收益,NW t(window=20) 修正重叠;
  · 若加速度在"斜率同号"的桶内有显著区分(|t|>2)且方向与明斯基假说一致
    (斜率+而减速=泡沫顶/斜率−而减速收窄=恐慌尾) → [S18] 候选注册;
  · 否则阴性入册,DSR+1。
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from astock_monitor.audit import newey_west_t
from astock_monitor.signals import load_index_closes

SLOPE_W = 30        # 斜率窗(交易日,与 [S13] 同口径)
ACCEL_W = 20        # 加速度窗(斜率的 20 日变化)
H = 20              # 前向收益窗
OUT = REPO_ROOT / "results" / "minsky_accel.json"

# ---- 数据 ----
mg = pd.read_parquet(REPO_ROOT / "data" / "lake" / "raw" / "akshare" / "margin" / "part.parquet")
dcol = next(c for c in mg.columns if "日期" in c)
bal = next(c for c in mg.columns if "融资余额" in c)
mg = mg[[dcol, bal]].copy()
mg.columns = ["date", "balance"]
mg["date"] = pd.to_datetime(mg["date"])
mg = mg.drop_duplicates("date").sort_values("date").reset_index(drop=True)
print(f"两融: {mg['date'].min().date()} -> {mg['date'].max().date()}, {len(mg)} 行")

idx = load_index_closes(REPO_ROOT / "data" / "cnequity-lake", "000300.SH")
idx_df = pd.DataFrame(idx, columns=["date", "close"])
idx_df["date"] = pd.to_datetime(idx_df["date"])
idx_df = idx_df.set_index("date")
print(f"指数: {idx_df.index.min().date()} -> {idx_df.index.max().date()}, {len(idx_df)} 天")

# ---- 对齐:以指数交易日为主轴,两融用 as-of(≤当日最近值,防未来函数) ----
mg = mg.set_index("date")
mg = mg.reindex(idx_df.index.union(mg.index)).ffill().reindex(idx_df.index)
print("对齐后缺失:", int(mg["balance"].isna().sum()))

df = idx_df.copy()
df["balance"] = mg["balance"]
# 一阶:30 日斜率(标准化为日变化率)
df["slope"] = df["balance"].pct_change(SLOPE_W)
# 二阶:斜率的 20 日变化(加速度)
df["accel"] = df["slope"].diff(ACCEL_W)
# T+20 前向收益
df["fwd20"] = df["close"].shift(-H) / df["close"] - 1.0
df = df.dropna(subset=["slope", "accel", "fwd20"])
print(f"有效样本: {len(df)} ({df.index.min().date()} -> {df.index.max().date()})")

# ---- 四桶分析(斜率 × 加速度) ----
df["slope_pos"] = df["slope"] > 0
df["accel_pos"] = df["accel"] > 0
buckets = {
    "加杠杆·加速": (True, True),    # 泡沫段(明斯基:投机→庞氏)
    "加杠杆·减速": (True, False),   # 加杠杆尾声(拐点前夜?)
    "降杠杆·加速": (False, True),   # 恐慌加速(明斯基时刻进行中)
    "降杠杆·减速": (False, False),  # 恐慌收尾(政策对冲段)
}
out = {"meta": {
    "slope_window": SLOPE_W, "accel_window": ACCEL_W, "horizon": H,
    "alignment": "两融 as-of 至指数交易日(ffill,防未来函数)",
    "hypothesis": "明斯基:斜率+而减速=泡沫顶前夜;斜率−而减速收窄=恐慌尾",
    "preregistered_rule": "加速度在斜率同号桶内 |t|>2 且方向符合假说 → [S18] 候选; 否则阴性",
}, "buckets": {}}
print("\n四桶 T+20 前向收益(NW t, window=%d):" % H)
for name, (sp, ap) in buckets.items():
    sub = df[(df["slope_pos"] == sp) & (df["accel_pos"] == ap)]
    if len(sub) < 60:
        out["buckets"][name] = {"n": len(sub), "note": "样本不足"}
        print(f"  {name}: n={len(sub)} 样本不足")
        continue
    vals = sub["fwd20"].values
    nw = newey_west_t(list(vals), window=H)
    out["buckets"][name] = {
        "n": int(len(sub)), "mean_fwd20": round(float(np.mean(vals)), 6),
        "nw_t": round(float(nw), 3),
        "span": [str(sub.index.min().date()), str(sub.index.max().date())],
    }
    print(f"  {name}: n={len(sub)}  mean={np.mean(vals):+.4f}  NW t={nw:+.3f}")

# ---- 加速度的边际信息:同斜率符号内,加速度正 vs 负 的收益差 ----
for sp, side in ((True, "加杠杆"), (False, "降杠杆")):
    a = df[(df["slope_pos"] == sp) & (df["accel_pos"])]["fwd20"]
    b = df[(df["slope_pos"] == sp) & (~df["accel_pos"])]["fwd20"]
    n = min(len(a), len(b))
    if n < 60:
        continue
    # 逐期均值差(两组独立,非配对;用两组 NW t 与均值差/合并标准误近似)
    diff = float(np.mean(a) - np.mean(b))
    se = float(np.sqrt(np.var(a, ddof=1) / len(a) + np.var(b, ddof=1) / len(b)))
    t = diff / se if se > 0 else float("nan")
    out.setdefault("marginal_tests", {})[side] = {
        "n_pos": int(len(a)), "n_neg": int(len(b)),
        "mean_diff_T20": round(diff, 6), "t": round(float(t), 3),
    }
    print(f"  [{side}] 加速 vs 减速 的 T+20 差: {diff:+.4f}  t={t:+.3f}")

OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("saved", OUT)
