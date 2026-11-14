"""2027 波动窗口·触发面板(roadmap P3/P7;纪律:只记录+推送,**不 front-run**)。

五监视器(阈值在 config.triggers,并行会话可把 T1-T7 语义对齐进来而不改代码):
  T-ERP    股债利差 2500 日分位 < erp_low_pct(股贵=风险积累)     慢变量
  T-宽度   breadth_ratio < breadth_bear(宽度坍塌)                事故前兆
  T-杠杆   两融贪婪度 > margin_greed_high(杠杆拥挤)              风险积累
  T-波动   vol20 的 500 日分位 > vol_pct_high(极端波动)          风暴本体临近
  T-年线   regime == BEAR(三票二门控确认)                        状态确认

状态机:**跨越触发**——上一次未触发→本次触发才告警推送;持续触发不重复;
解除时发解除通知。全部指标 point-in-time(分位池不含当日,shift 纪律)。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

TRIGGERS = ("T-ERP", "T-宽度", "T-杠杆", "T-波动", "T-年线")


def rolling_pctile_exclude_today(values: list, window: int = 2500) -> dict:
    """逐日分位,分位池=过去 window 日(不含当日)。输入 [(date, value)],输出 {date: pct}。

    池不足 60 个 → None(不造分位)。
    """
    out = {}
    for i, (d, v) in enumerate(values):
        if v is None:
            out[d] = None
            continue
        pool = [x for _, x in values[max(0, i - window):i] if x is not None]
        out[d] = (sum(1 for x in pool if x <= v) / len(pool)) if len(pool) >= 60 else None
    return out


def _cmp(value, op: str, threshold) -> bool:
    if value is None:
        return False
    ops = {"<": value < threshold, "<=": value <= threshold,
           ">": value > threshold, ">=": value >= threshold,
           "==": value == threshold}
    return ops[op]


def eval_triggers(metrics: dict, thresholds: dict, prev_state: dict) -> dict:
    """计算五触发器的当日状态与跨越事件。

    metrics: {name: 当日值(None=缺数据)};prev_state: {name: {"fired": bool, "since": date}}
    返回 {name: {"fired", "changed", "value", "since"}}——fired=当前是否触发,
    changed=相对上一状态**新跨越**(只有 changed 才推送)。
    """
    defs = {
        "T-ERP":  ("erp_pct", "<", thresholds.get("erp_low_pct", 0.05)),
        "T-宽度": ("breadth", "<", thresholds.get("breadth_bear", 0.4)),
        "T-杠杆": ("greed", ">", thresholds.get("margin_greed_high", 0.9)),
        "T-波动": ("vol_pct", ">", thresholds.get("vol_pct_high", 0.9)),
        "T-年线": ("regime", "==", 2),   # BEAR
    }
    out = {}
    for name, (metric, op, thr) in defs.items():
        value = metrics.get(metric)
        fired = _cmp(value, op, thr)
        prev = (prev_state or {}).get(name, {})
        was = bool(prev.get("fired"))
        changed = fired and not was
        out[name] = {"fired": fired, "changed": changed, "value": value,
                     "since": prev.get("since") if (fired and was) else
                              (str(date.today()) if fired else None)}
    return out


def load_metric_series(cfg: dict) -> dict:
    """装配五监视器的逐日序列(全部 point-in-time 口径)。惰性 pandas。"""
    import pandas as pd  # noqa: PLC0415
    from .config import resolve_path as _rp
    from .regime import daily_regime, realized_vol_percentile
    from .sentiment import load_margin_greed
    from .signals import load_index_closes

    lake = _rp(cfg, "paths.cnequity_lake")

    # 1) ERP 分位(2005 起,2500 日池,分位池不含当日)
    erp_pct = {}
    erp_file = _rp(cfg, "paths.lake_raw") / "akshare" / "erp" / "part.parquet"
    if erp_file.exists():
        df = pd.read_parquet(erp_file)
        dc = next(c for c in df.columns if "日期" in c or c.lower() == "date")
        vc = next(c for c in df.columns if "利差" in c)
        df = df.rename(columns={dc: "date", vc: "spread"})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.drop_duplicates("date").sort_values("date")
        pairs = list(zip(df["date"], df["spread"].astype(float)))
        pcts = rolling_pctile_exclude_today(
            pairs, int(cfg.get("triggers", {}).get("erp_window", 2500)))
        erp_pct = {d: p for d, p in pcts.items() if p is not None}

    # 2) 宽度(湖内回算,2021 起完整)
    breadth = {}
    bh = _rp(cfg, "paths.lake_norm") / "breadth_history" / "part.parquet"
    if bh.exists():
        bdf = pd.read_parquet(bh)
        breadth = {d: float(v) for d, v in
                   zip(pd.to_datetime(bdf["date"]).dt.date, bdf["up_ratio"])}

    # 3) 两融贪婪度(2012-09 起)
    greed = load_margin_greed(_rp(cfg, "paths.lake_raw"))

    # 4) 波动分位 + 5) regime(沪深300)
    idx_rows = load_index_closes(lake, "000300.SH")
    volp_list = realized_vol_percentile([c for _, c in idx_rows])
    volp = {d: p for (d, _), p in zip(idx_rows, volp_list) if p is not None}
    regime = daily_regime(idx_rows, breadth250=None)

    return {"erp_pct": erp_pct, "breadth": breadth, "greed": greed,
            "vol_pct": volp, "regime": regime, "index_rows": idx_rows}


def resolve_erp(cfg: dict):
    from .config import resolve_path
    from .store import has_task  # noqa: F401
    p = resolve_path(cfg, "paths.lake_raw") / "akshare" / "erp" / "part.parquet"
    return p if p.exists() else None


