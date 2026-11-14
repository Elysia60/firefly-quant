#!/usr/bin/env python3
"""PoC-4 独立复跑背书(萤火计划动工第 0 步)。

与 本地沙箱 沙箱 astock_poc/poc4_calendar_alignment.py 同源(只读留证,不改沙箱):
- 探针判据 = orders_df 实际成交时间戳(撮合级),非 bar 时间戳
- 不预设 2026-10-08 是假日,让 CNEquity 与新浪两源对拍说话
差异:输出落本仓库 results/;湖路径读生产仓 config.json(单一正本)。

运行环境:需 akquant(本地沙箱 venv):
  "<本机>/.workbuddy/binaries/python/envs/default/Scripts/python.exe" scripts/verify/poc4_rerun.py
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor.config import load_config, resolve_path  # noqa: E402

OUT = REPO_ROOT / "results"
OUT.mkdir(exist_ok=True)

import pandas as pd  # noqa: E402
from akquant import Bar, CurrentClose, Strategy, SessionResolver, run_backtest  # noqa: E402

_cfg = load_config()
DEMO_LAKE = Path(resolve_path(_cfg, "paths.cnequity_lake"))

report = {}

# ---------- A: CNEquity 日历(生产仓 calendar.py 复用) ----------
from astock_monitor import calendar as astock_cal  # noqa: E402

trading_days = astock_cal.read_cnequity_calendar(DEMO_LAKE)
report["A"] = {"rows": len(trading_days), "trading_days": len(trading_days),
               "range": [str(trading_days[0]), str(trading_days[-1])],
               "type": type(trading_days[0]).__name__}

# ---------- A2: 新浪日历交叉验证 ----------
try:
    sina_days = astock_cal.fetch_sina_calendar()
    report["A2_sina_crosscheck"] = astock_cal.crosscheck(trading_days, sina_days)
except Exception as e:  # noqa: BLE001
    report["A2_sina_crosscheck"] = {"status": "error", "detail": f"{type(e).__name__}: {str(e)[:200]}"}

# ---------- B: AKQuant 默认日历行为 ----------
resolver_default = SessionResolver()
report["B"] = {
    "uses_fallback_calendar": bool(getattr(resolver_default, "uses_fallback_calendar", None)),
    "is_session_day_2026_10_01(Thu,holiday)": bool(resolver_default.is_session_day(date(2026, 10, 1))),
    "is_session_day_2026_10_03(Sat)": bool(resolver_default.is_session_day(date(2026, 10, 3))),
}

# ---------- C: 端到端撮合级对齐 ----------
WINDOW_DATES = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05",
                "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]


class SellNextStrategy(Strategy):
    def __init__(self):
        self.day_idx = 0

    def on_bar(self, bar):
        if self.day_idx == 0:
            self.buy(symbol=bar.symbol, quantity=100)
        else:
            pos = self.get_position(bar.symbol)
            if pos > 0:
                self.sell(symbol=bar.symbol, quantity=pos)
        self.day_idx += 1


def make_bars():
    days = pd.to_datetime(WINDOW_DATES).tz_localize("Asia/Shanghai")
    closes = [10.0 + i * 0.1 for i in range(len(WINDOW_DATES))]
    return [Bar(timestamp=d.value, open=c, high=c, low=c, close=c,
                volume=10000.0, symbol="POC")
            for d, c in zip(days, closes)]


def fills_of(df):
    if df is None or df.empty:
        return []
    out = []
    for _, row in df.iterrows():
        st = str(row.get("status", "")).lower()
        if "fill" in st:
            ts = row.get("updated_at") or row.get("created_at")
            if ts is None or str(ts) in ("NaT", "nan", ""):
                continue
            out.append(str(pd.Timestamp(str(ts)).date()))
    return out


common = dict(data=make_bars(), strategy=SellNextStrategy, symbols="POC", freq="1d",
              fill_policy=CurrentClose(), broker_profile="cn_stock_t1_low_fee",
              show_progress=False)
res_none = run_backtest(**common)
fills_none = fills_of(res_none.orders_df)
res_cne = run_backtest(**common, trading_calendar=trading_days)
fills_cne = fills_of(res_cne.orders_df)

holidays_cne = {"2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"}
report["C_fill_level"] = {
    "fills_without_calendar": fills_none,
    "fills_with_cne_calendar": fills_cne,
    "leak_without_calendar": [d for d in fills_none if d in holidays_cne],
    "leak_with_calendar": [d for d in fills_cne if d in holidays_cne],
}

report["VERDICT"] = {
    "cnequity_calendar_readable_as_list_date": report["A"]["type"] == "date",
    "cnequity_vs_sina_identical": report["A2_sina_crosscheck"].get("identical"),
    "akquant_default_treats_holiday_thu_as_session": report["B"]["is_session_day_2026_10_01(Thu,holiday)"],
    "akquant_fills_on_holiday_without_calendar": bool(report["C_fill_level"]["leak_without_calendar"]),
    "akquant_no_holiday_fill_with_cne_calendar": not report["C_fill_level"]["leak_with_calendar"],
}

print("=" * 70)
ok = True
for k, v in report["VERDICT"].items():
    print(f"{'PASS' if v else 'FAIL':<6}  {k}")
    ok = ok and bool(v)
print("=" * 70)
print(json.dumps(report["A2_sina_crosscheck"], ensure_ascii=False, indent=2)[:600])
print(json.dumps(report["C_fill_level"], ensure_ascii=False, indent=2))
(OUT / "poc4_rerun_verdict.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("saved", OUT / "poc4_rerun_verdict.json")
sys.exit(0 if ok else 1)
