#!/usr/bin/env python3
"""[P5] 首份单因子 IC 检验报告:Alpha158-lite 九因子 × 湖内全量横截面。

方法(METHODS §3c/§3e 口径):
- 因子面板:alpha_lite.compute_factor_panel(9 因子,防泄漏 shift 已钉死并有测试)
- 标签:label_raw = close[t+21]/close[t+1] − 1(T 收盘出信号,T+1 成交,T+21 出)
- IC:逐日截面 Spearman(对截面单调变换不变);有效日 = 成分数 ≥700
- 汇总:均值/ICIR/NW t(重叠窗=20)/正比例/分年表
- 纪律:多重检验——9 因子同批检验,Bonferroni×9 后 |t|>3.5 才谈"候选";先看方向与稳定性
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor import alpha_lite as AL  # noqa: E402
from astock_monitor.config import load_config, resolve_path  # noqa: E402

cfg = load_config()
lake = resolve_path(cfg, "paths.cnequity_lake")
bars = AL.load_bars_complete(lake, min_symbols=700)
print(f"完整天数据: {len(bars)} 行,{bars['symbol'].nunique()} 只,{bars['trade_date'].min()} ~ {bars['trade_date'].max()}")

panel = AL.compute_factor_panel(bars)
closes = bars[["symbol", "trade_date", "close"]]
panel = AL.forward_label(panel, closes, horizon=20)
valid = panel.dropna(subset=["label_raw"])
print(f"因子面板: {len(panel)} 行,带 20 日标签 {len(valid)} 行")

FACTORS = ["KMID", "KSFT", "ROC5", "ROC20", "STD20", "RSV20", "CORR20", "CNTP20", "VMA20"]
report = {"universe": "中证800成分(当期,有幸存者偏差)",
          "label": "close[t+21]/close[t+1]-1", "min_symbols": 700,
          "n_days": int(panel.dropna(subset=["label_raw"])["date"].nunique()),
          "factors": {}}
for f in FACTORS:
    ic = AL.daily_spearman_ic(panel, f, min_n=700)
    report["factors"][f] = AL.ic_summary(ic, nw_window=20)

out = REPO_ROOT / "results" / "alpha_ic_report.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n== 单因子 IC 检验(标签=20日前向,{report['n_days']} 个有效日, Bonferroni×9) ==")
print(f"{'因子':<8}{'n':<6}{'meanIC':<10}{'ICIR':<8}{'NW t':<8}{'IC>0':<7}{'判定'}")
for f, s in report["factors"].items():
    if s.get("small_sample"):
        print(f"{f:<8}{s['n']:<6} 样本不足")
        continue
    t = s["nw_t"]
    verdict = "候选" if abs(t) > 3.5 else ("观察" if abs(t) > 2.5 else "噪音级")
    print(f"{f:<8}{s['n']:<6}{s['mean_ic']:+.4f}  {s['icir']:+.3f}  {t:+.2f}  {s['ic_gt_0_ratio']:.2f}  {verdict}")
print("saved", out)
