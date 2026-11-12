#!/usr/bin/env python3
"""看板生成器:单文件静态 HTML,零 CDN 零依赖(理念 8)——数据内嵌,双击即开。

读取:data/state/doctor_report.json + monitor.db(forecast_log)+ 湖统计。
写出:data/dashboard.html;图表用内联 SVG(无外网也可渲染)。
"""
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from astock_monitor.config import load_config, resolve_path  # noqa: E402
from astock_monitor import forecast as F  # noqa: E402


def lake_stats(lake: Path) -> dict:
    import pandas as pd
    files = sorted(lake.glob("curated/daily_bars/trade_date=*/*.parquet"))
    if not files:
        return {"rows": 0, "symbols": 0, "range": ["-", "-"], "sources": {}}
    df = pd.concat((pd.read_parquet(f, columns=["symbol", "source"]) for f in files),
                   ignore_index=True)
    dates = [f.parent.name.replace("trade_date=", "") for f in files]
    return {"rows": int(len(df)), "symbols": int(df["symbol"].nunique()),
            "range": [dates[0], dates[-1]],
            "sources": {k: int(v) for k, v in df["source"].value_counts().items()}}


def latest_signal(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT signal_date, verdict, score, data_quality_json FROM forecast_log"
        " WHERE window_days=5 ORDER BY signal_date DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"date": row[0], "verdict": row[1], "score": row[2],
            "quality": json.loads(row[3])}


def year_split(conn: sqlite3.Connection) -> list[dict]:
    """avoid_watch 反向线索的反方陈述检验:分年度方向正确率是否一致。"""
    rows = conn.execute(
        "SELECT substr(signal_date,1,4) AS y, window_days, COUNT(*), SUM(correct), AVG(fwd_ret)"
        " FROM forecast_log WHERE verdict='avoid_watch' AND judged=1"
        " GROUP BY y, window_days ORDER BY y, window_days").fetchall()
    return [{"year": r[0], "window": r[1], "n": r[2], "correct": r[3] or 0,
             "correct_rate": round((r[3] or 0) / r[2], 4), "mean_fwd": round(r[4], 5)} for r in rows]


def bar_svg(pct: float, color: str, label: str) -> str:
    w = max(2, min(100, abs(pct) * 500))
    return (f'<div class="bar-row"><span class="bar-label">{label}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{w:.1f}%;background:{color}"></span></span>'
            f'<span class="bar-val">{pct * 100:.2f}%</span></div>')


def render(cfg: dict) -> str:
    COST_RT = float(cfg["backtest"].get("cost_round_trip", 0.0020))  # 回合成本正本在 config.json
    conn = sqlite3.connect(str(resolve_path(cfg, "paths.db")))
    F.init_db(conn)
    try:
        lake = lake_stats(resolve_path(cfg, "paths.cnequity_lake"))
        summary = F.summarize(conn, cost_rt=COST_RT)
        signal = latest_signal(conn)
        years = year_split(conn)
    finally:
        conn.close()
    doctor_path = resolve_path(cfg, "paths.state_dir") / "doctor_report.json"
    doctor = json.loads(doctor_path.read_text(encoding="utf-8")) if doctor_path.exists() else {"overall": "?", "checks": []}
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def verdict_cell(v: dict) -> str:
        rate = v["correct_rate"]
        rate_s = f"{rate * 100:.1f}%" if rate is not None else "—"
        cls = "bad" if (rate is not None and rate < 0.5) else ("good" if rate is not None and rate >= 0.6 else "mid")
        if v.get("mean_net_ret") is not None:
            net_s = v["mean_net_ret"] * 100
            net = f'<td class="{ "good" if net_s > 0 else "bad"}">{net_s:+.2f}%</td>'
        else:
            net = "<td>—</td>"
        small = ' <span class="pill p-mid">n_eff小</span>' if v["small_sample"] else ""
        return (f"<td>{v['judged']} <span class=\"small\">(n_eff≈{v['n_eff']})</span>{small}</td>"
                f"<td>{(v['mean_fwd_ret'] or 0) * 100:+.2f}%</td>{net}"
                f'<td class="{cls}">{rate_s}</td>')

    rows_html = ""
    for w, by_v in summary["windows"].items():
        for vname, v in by_v.items():
            rows_html += (f"<tr><td>T+{w}</td><td><b>{vname}</b></td>{verdict_cell(v)}</tr>")

    year_html = "".join(
        f"<tr><td>{y['year']}</td><td>T+{y['window']}</td><td>{y['n']}</td>"
        f'<td class="{"bad" if y["correct_rate"] < 0.5 else "good"}">{y["correct_rate"] * 100:.1f}%</td>'
        f"<td>{y['mean_fwd'] * 100:+.2f}%</td></tr>" for y in years)

    src_html = "".join(bar_svg(v / max(lake["sources"].values()), "#1d4ed8", k)
                       for k, v in lake["sources"].items()) if lake["sources"] else "<p>无数据</p>"
    doctor_html = "".join(
        f'<div class="chk"><span class="pill p-{"good" if c["status"] == "PASS" else ("mid" if c["status"] == "WARN" else "bad")}">{c["status"]}</span> '
        f'<b>{c["name"]}</b> — {c["detail"]}</div>' for c in doctor["checks"])

    sig_html = ""
    if signal:
        q = signal["quality"]
        sig_html = (f'<div class="sig"><div class="sig-score">{signal["score"]:.1f}</div>'
                    f'<div><b>{signal["verdict"]}</b> <span class="pill p-mid">{signal["date"]}</span><br>'
                    f'<span class="small">质量: 宽度={q["breadth"]} 情绪={q["sentiment"]} '
                    f'缺口={q["gap_days"]}天 {q["banner"]}</span><br>'
                    f'<span class="small">tier=观察级(无对账样本不给行动级,[C2] 纪律)</span></div></div>')
    else:
        sig_html = "<p>尚无信号——运行 <code>python -m astock_monitor.cli forecast-replay</code></p>"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>萤火 · astock-monitor 看板</title>
<style>
:root{{--ink:#1f2937;--muted:#5f6b7a;--bg:#f6f7f9;--card:#fff;--line:#e5e7eb;--accent:#1d4ed8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.6}}
main{{max-width:1080px;margin:0 auto;padding:28px 18px 60px}}
h1{{font-size:26px;margin:0 0 4px}}h2{{font-size:19px;margin:30px 0 10px;border-left:4px solid var(--accent);padding-left:10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}}
.kpi{{font-size:26px;font-weight:700;color:var(--accent)}}
.kpi small{{font-size:13px;color:var(--muted);font-weight:400}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0}}
th,td{{border:1px solid var(--line);padding:7px 10px;text-align:left}}
th{{background:#f1f3f7}}
.good{{color:#15803d;font-weight:600}}.bad{{color:#b91c1c;font-weight:600}}.mid{{color:#b45309;font-weight:600}}
.pill{{display:inline-block;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:600}}
.p-good{{background:#dcfce7;color:#15803d}}.p-mid{{background:#fef3c7;color:#b45309}}.p-bad{{background:#fee2e2;color:#b91c1c}}
.bar-row{{display:flex;align-items:center;gap:8px;margin:5px 0}}
.bar-label{{width:110px;font-size:13px;color:var(--muted)}}
.bar-track{{flex:1;background:#eef1f6;border-radius:6px;height:14px;overflow:hidden}}
.bar-fill{{display:block;height:100%}}
.bar-val{{width:70px;font-size:13px;text-align:right}}
.chk{{margin:6px 0;font-size:14px}}
.sig{{display:flex;gap:16px;align-items:center}}
.sig-score{{font-size:44px;font-weight:800;color:var(--accent)}}
.small{{font-size:12.5px;color:var(--muted)}}
code{{background:#eef1f6;padding:1px 5px;border-radius:4px;font-size:13px}}
footer{{margin-top:36px;font-size:12px;color:var(--muted)}}
.warnbox{{background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:11px 15px;font-size:13.5px;margin:10px 0}}
</style></head><body><main>
<h1>🔥 萤火 · astock-monitor</h1>
<div class="small">核心理念:飞蛾扑火,向死而生 —— 结论必须可对账,负面结论原样入注册表 · 生成于 {gen_at}</div>

<h2>数据湖</h2>
<div class="grid">
  <div class="card"><div class="kpi">{lake['rows']:,}</div><small>daily_bars 行数</small></div>
  <div class="card"><div class="kpi">{lake['symbols']:,}</div><small>股票数</small></div>
  <div class="card"><div class="kpi">{lake['range'][0]}<br>{lake['range'][1]}</div><small>月分区范围</small></div>
  <div class="card"><div class="kpi">{sum(lake['sources'].values()) - lake['sources'].get('tdx_protocol', 0):,}</div><small>非东财来源行数(零 EM 依赖度)</small></div>
</div>
<div class="card"><b>行级来源分布</b>(行级溯源,L5 双源纪律){src_html}</div>

<h2>最新信号(观察级)</h2>
<div class="card">{sig_html}</div>

<h2>对账记分牌(csqaq 理念 1:结论必须可对账)</h2>
<div class="card">
<table><tr><th>窗口</th><th>verdict</th><th>已判卷</th><th>平均前向收益</th><th>扣成本净收益*</th><th>方向正确率</th></tr>
{rows_html}</table>
<div class="small">* 扣成本口径:回合成本 {COST_RT * 100:.2f}%(佣金万2.5×2+印花税0.05%卖出+过户+滑点);neutral 无方向主张只记收益。</div>
</div>

<h2>[S1] 注册结论 · avoid_watch 反向线索(csqaq [C6] 同款)</h2>
<div class="card">
<div class="warnbox"><b>[S1] 终审(regime 门控分层事件研究,2026-11-13)</b>:avoid_watch T+5 按事前三特征门控(年线滞回 1.01/0.96+年线宽度+波动否决)分庭——<b>bull 庭 d_obs=+0.19pp(p=0.69,无信息)</b>;<b>neutral 庭 −1.62pp(p=0.001)、bear 庭 −1.34pp(p=0.013)</b>。判决:<b>信号携带真实的相对弱势信息,适用域=中性+熊市庭;牛市庭按无信息处理。不是 regime 代理(反方陈述② 检验通过)</b>。教训链:v1 反向指标(被漂移骗)→ v2 regime 条件(切片伪影)→ v3 相对弱势(事件研究)→ v4 终审(门控圈定适用域)。</div>
<div class="warnbox"><b>反方陈述(仍开放)</b>:①对照仅匹配星期几+regime,未匹配波动率/估值状态——加配后 d_obs 收缩过半则降级为"波动率代理";②污染窗 ±6 天,信号簇外溢残留可能;③门控参数(1.01/0.96/0.6/0.4/0.9)为文献先验,未做敏感性扫描——扫描后结论不稳则降级。</div>
<table><tr><th>年度</th><th>窗口</th><th>n</th><th>方向正确率</th><th>平均前向</th></tr>{year_html}</table>
<div class="small">判读纪律(继承 csqaq):分年度同向 → 反向更硬;分年度不一致 → 撤销。</div>
</div>

<h2>系统状态(doctor 七项)</h2>
<div class="card"><b>overall = {doctor['overall']}</b>{doctor_html}</div>

<footer>萤火计划 · astock-monitor · 方法论正本 <code>METHODS.md</code> · 重新生成:<code>python scripts/build_dashboard.py</code><br>
数据仅供研究学习,不构成投资建议,不公开荐股。</footer>
</main></body></html>"""


def main() -> int:
    cfg = load_config()
    html = render(cfg)
    out = resolve_path(cfg, "paths.data_dir") / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"dashboard written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
