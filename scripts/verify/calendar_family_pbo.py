# -*- coding: utf-8 -*-
"""calendar_family_pbo.py — [S22] 第三枪: 日历规则家族 CSCV(2026-11-23)

家族构成(纯指数数据,零重算):
  A hold                基线持有
  B avoid_month_end     规避每月最后 3 个交易日(月末效应, [S3] 边缘 p=0.058)
  C avoid_month_start   规避每月前 2 个交易日(月初波动)
  D avoid_monday        规避周一(周内效应 folklore)

口径(同前两枪): 非重叠 T+20 调仓点,规避日=现金(0)。判定写死:
  PBO ≤ 0.2 → 家族选择有效(日历家族有真信号)
  0.2-0.5   → 中度,维持判读
  >0.5      → 家族选择无效 → [S3] 边缘结论降级警示
产物: results/calendar_family_pbo.json
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

OUT = REPO_ROOT / "results" / "calendar_family_pbo.json"
H, STEP = 20, 20


def month_pos(idx: pd.DatetimeIndex) -> np.ndarray:
    """每月内交易日序号(0 起)。"""
    grp = pd.Series(1, index=idx).groupby(idx.to_period("M")).cumsum()
    return (grp - 1).values


def main() -> int:
    idx = load_index_closes(REPO_ROOT / "data" / "cnequity-lake", "000300.SH")
    df = pd.DataFrame(idx, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["fwd20"] = df["close"].shift(-H) / df["close"] - 1.0
    df = df.dropna(subset=["fwd20"])

    grid = df.iloc[::STEP]
    fr = grid["fwd20"].values
    mpos = month_pos(grid.index)
    n_days = pd.Series(grid.index).groupby(grid.index.to_period("M")).transform("count").values
    is_last3 = mpos >= (n_days - 3)
    is_first2 = mpos < 2
    is_monday = grid.index.dayofweek == 0

    rules = {
        "A_hold": np.ones(len(fr), dtype=bool),
        "B_avoid_month_end": ~is_last3,
        "C_avoid_month_start": ~is_first2,
        "D_avoid_monday": ~is_monday,
    }
    names = sorted(rules.keys())
    T_use = (len(fr) // 16) * 16
    M = np.column_stack([np.where(rules[n], fr, 0.0) for n in names])[-T_use:]
    rep = cscv_pbo(M, n_blocks=16)
    rep["strategies"] = names
    rep["T"] = int(T_use)
    rep["T_trimmed"] = {"from": int(len(fr)), "to": int(T_use)}
    rep["grid_span"] = [str(grid.index[0].date()), str(grid.index[-1].date())]
    rep["rule_defs"] = {"A_hold": "基线持有", "B_avoid_month_end": "规避月末 3 日([S3] 边缘)",
                        "C_avoid_month_start": "规避月初 2 日", "D_avoid_monday": "规避周一"}
    rep["criteria"] = "<=0.2 家族有效 / 0.2-0.5 中度 / >0.5 无效([S3]降级警示)"
    rep["note"] = "[S22] 第三枪(日历家族);口径同前两枪"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("pbo", "band", "n_overfit", "n_combos",
                                          "T", "grid_span")}, ensure_ascii=False, indent=1))
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
