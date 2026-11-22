# -*- coding: utf-8 -*-
"""minsky_family_pbo.py — [S22] 第二枪: margin 规避规则家族 CSCV(2026-11-23)

[S22]-反方推翻观测: "[S18]/[S7] 家族 PBO 显著 <0.5 → 家族级选择有效,本条降级"。
本枪测 [S18] 所在的 margin 规则家族——四条配置,同一指数/同一前向窗:

  A hold            基线: 永远持有(指数 T+20)
  B avoid_lever_decel  规避[加杠杆·减速]段([S18] 拐点前夜 −1.25% 桶)——其余持有
  C avoid_delever_accel 规避[降杠杆·加速]段(明斯基时刻)——其余持有
  D avoid_slope_neg    规避[斜率<0]段(一阶 [S13] 规则)——其余持有

口径(预注册): 每 20 个交易日取 1 个调仓点(非重叠 T+20,同 [S15]/第一枪口径);
规避日收益=0(现金),其余=指数 T+20。判定写死:
  PBO ≤ 0.2  → 家族级选择有效 → [S22] 降级为"[S15]-[S17] 局部结论"(反方部分撤销)
  0.2 < PBO ≤ 0.5 → 中度,维持 [S22] 原判读
  PBO > 0.5 → margin 规则家族选择无效 → [S22] 维持,且 [S18] 候选地位降级警示
产物: results/minsky_family_pbo.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from astock_monitor.cscv_pbo import cscv_pbo  # noqa: E402
from astock_monitor.signals import load_index_closes  # noqa: E402

OUT = REPO_ROOT / "results" / "minsky_family_pbo.json"
H = 20
STEP = 20  # 非重叠调仓步长


def main() -> int:
    mg = pd.read_parquet(REPO_ROOT / "data" / "lake" / "raw" / "akshare" / "margin" / "part.parquet")
    dcol = next(c for c in mg.columns if "日期" in c)
    bal = next(c for c in mg.columns if "融资余额" in c)
    mg = mg[[dcol, bal]].copy()
    mg.columns = ["date", "balance"]
    mg["date"] = pd.to_datetime(mg["date"])
    mg = mg.drop_duplicates("date").sort_values("date").reset_index(drop=True)

    idx = load_index_closes(REPO_ROOT / "data" / "cnequity-lake", "000300.SH")
    idx_df = pd.DataFrame(idx, columns=["date", "close"])
    idx_df["date"] = pd.to_datetime(idx_df["date"])
    idx_df = idx_df.set_index("date")

    mg = mg.set_index("date")
    mg = mg.reindex(idx_df.index.union(mg.index)).ffill().reindex(idx_df.index)
    df = idx_df.copy()
    df["balance"] = mg["balance"]
    df["slope"] = df["balance"].pct_change(30)
    df["accel"] = df["slope"].diff(20)
    df["fwd20"] = df["close"].shift(-H) / df["close"] - 1.0
    df = df.dropna(subset=["slope", "accel", "fwd20"])
    df["slope_pos"] = df["slope"] > 0
    df["accel_pos"] = df["accel"] > 0

    # 非重叠调仓点: 每 STEP 个交易日取 1 个(末尾对齐)
    grid = df.iloc[::STEP]
    fr = grid["fwd20"].values
    avoid_B = (~(grid["slope_pos"] & grid["accel_pos"])).values * 0  # 占位
    rules = {
        "A_hold": np.ones(len(fr)),
        "B_avoid_lever_decel": (~grid["slope_pos"]).values | grid["accel_pos"].values,
        "C_avoid_delever_accel": grid["slope_pos"].values | (~grid["accel_pos"]).values,
        "D_avoid_slope_neg": grid["slope_pos"].values,
    }
    # 修正: B=规避[加杠杆·减速]=slope_pos & ~accel_pos → 持仓=~(slope_pos & ~accel_pos)
    rules["B_avoid_lever_decel"] = ~(grid["slope_pos"].values & ~grid["accel_pos"].values)
    rules["C_avoid_delever_accel"] = ~(~grid["slope_pos"].values & grid["accel_pos"].values)
    rules["D_avoid_slope_neg"] = grid["slope_pos"].values

    names = sorted(rules.keys())
    T_use = (len(fr) // 16) * 16  # 截到 16 的倍数——取最近(同第一枪口径)
    M = np.column_stack([
        np.where(rules[n], fr, 0.0) for n in names  # 规避日=现金(0),其余=指数 T+20
    ])[-T_use:]
    rep = cscv_pbo(M, n_blocks=16)
    rep["strategies"] = names
    rep["T"] = int(T_use)
    rep["T_trimmed"] = {"from": int(len(fr)), "to": int(T_use), "rule": "取最近 16 的倍数期"}
    rep["grid_span"] = [str(grid.index[0].date()), str(grid.index[-1].date())]
    rep["rule_defs"] = {
        "A_hold": "永远持有",
        "B_avoid_lever_decel": "规避[加杠杆·减速]([S18] 拐点前夜桶)",
        "C_avoid_delever_accel": "规避[降杠杆·加速](明斯基时刻桶)",
        "D_avoid_slope_neg": "规避[斜率<0](一阶 [S13])"}
    rep["criteria"] = ("<=0.2 家族选择有效([S22]降级) / 0.2-0.5 中度(维持) "
                       "/ >0.5 家族选择无效([S18]降级警示)")
    rep["note"] = "[S22] 第二枪;口径=非重叠 T+20 调仓点,规避日收益=现金"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("pbo", "band", "n_overfit", "n_combos",
                                          "T", "grid_span")}, ensure_ascii=False, indent=1))
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
