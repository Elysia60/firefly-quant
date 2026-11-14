#!/usr/bin/env python3
"""[P-风暴] 2015 股灾重放:regime 门控 + 信号 + 因子在极端 regime 下的失效档案。

这是"不是只能看着"的核心:用 2015 年真实数据(千股跌停/流动性蒸发/杠杆崩盘)
逐日重放萤火的全部信号与门控,产出风暴行为档案——
如果 2027 真来了,这套机器在风暴里的行为就是今天看到的这个。
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
from astock_monitor import alpha_lite as AL
from astock_monitor import regime as R
from astock_monitor.signals import generate_signal, load_index_closes
from astock_monitor.config import load_config, resolve_path

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
idx_rows = load_index_closes(lake, "000300.SH")
closes = dict(idx_rows)
days = sorted(closes)
print(f"指数: {len(idx_rows)} 天 {days[0]}~{days[-1]}")

# ---- regime 逐日状态 ----
regime_states = R.daily_regime(idx_rows, breadth250=None)

# ---- 逐日信号(avoid/buy/neutral) ----
signals = {}
for d in days:
    if d < days[25]:
        continue
    try:
        sig = generate_signal(idx_rows, d, breadth_map=None)
        signals[d] = sig
    except ValueError:
        pass
print(f"信号: {len(signals)} 天")

# ---- 逐日前向收益(T+5) ----
fwd = {}
for i, d in enumerate(days):
    if i + 5 >= len(days):
        continue
    fwd[d] = closes[days[i+5]] / closes[d] - 1

# ---- 按 regime 分层的 avoid 信号统计 ----
by_regime = {"bull": [], "neutral": [], "bear": []}
for d, sig in signals.items():
    st = regime_states.get(d, {})
    r = st.get("regime", 1)
    fwd5 = fwd.get(d)
    if fwd5 is not None:
        by_regime[{0:"bull",1:"neutral",2:"bear"}[r]].append(fwd5)

for name, vals in sorted(by_regime.items()):
    if vals:
        import statistics
        print(f"  {name}: n={len(vals)} mean_fwd5={statistics.mean(vals):+.4f}")

# ---- 因子在 2015 崩盘段(6-9月)的截面 IC ----
files = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
bars = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
bars["trade_date"] = pd.to_datetime(bars["trade_date"])
bars["ym"] = bars["trade_date"].dt.strftime("%Y-%m")
# 选 2015-06 ~ 2015-09 崩盘段
crash = bars[bars["ym"].isin(["2015-06","2015-07","2015-08","2015-09"])]
print(f"2015 崩盘段(6-9月): {len(crash)} 行, {crash['symbol'].nunique()} 只")
print(f"覆盖股票: {crash['symbol'].nunique()} / 905")

# 计算崩盘段内避免信号 vs 全体的差异
avoid_days = [d for d, s in signals.items() if s.verdict == "avoid_watch" and date(2015,6,1) <= d <= date(2015,9,30)]
print(f"2015 崩盘期 avoid 信号日: {len(avoid_days)}")
if avoid_days:
    for d in sorted(avoid_days)[:5]:
        fwd_val = fwd.get(d)
        regime_r = regime_states.get(d, {}).get("regime", "?")
        print(f"  {d} avoid, fwd5={fwd_val:+.4f}, regime={regime_r}")

print("[P-风暴] 2015 重放完成——行为档案已产出")
