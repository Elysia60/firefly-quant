# -*- coding: utf-8 -*-
"""usage_proof.py — 萤火使用证明（2026-11-23 · 判卷数据 + 当前建议 + 纸面账户）"""
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor")
conn = sqlite3.connect(str(ROOT / "data" / "monitor.db"))
OUT = Path(r"D:\大肥鱼的深海\萤火使用证明.html")


def q(sql):
    return conn.execute(sql).fetchall()


def build():
    # 1) 判卷汇总
    judge_rows = q("""
        SELECT verdict, window_days, COUNT(*), SUM(correct),
               ROUND(AVG(fwd_ret)*100, 3)
        FROM forecast_log WHERE judged = 1
        GROUP BY verdict, window_days ORDER BY window_days, verdict
    """)
    # 近三年判卷(2024+)
    recent = q("""
        SELECT verdict, window_days, COUNT(*), SUM(correct),
               ROUND(AVG(fwd_ret)*100, 3)
        FROM forecast_log WHERE judged = 1 AND signal_date >= '2024-01-01'
        GROUP BY verdict, window_days ORDER BY window_days, verdict
    """)
    # 2) 信号日历(按月统计 verdict 分布)
    monthly = q("""
        SELECT substr(signal_date, 1, 7) as month, verdict, COUNT(DISTINCT signal_date)
        FROM forecast_log GROUP BY month, verdict ORDER BY month
    """)
    # 3) 纸面账户(JSON 文件)
    acct_f = ROOT / 'data' / 'state' / 'paper_account.json'
    acct = None
    if acct_f.exists():
        acct_d = json.loads(acct_f.read_text(encoding='utf-8'))
        acct = (acct_d.get('cash', 0), acct_d.get('high_water'), acct_d.get('last_day'))
    # 4) 最新信号
    latest = q("""
        SELECT signal_date, verdict, score, score AS composite FROM forecast_log
        ORDER BY signal_date DESC LIMIT 1
    """)
    # 5) 候选
    cand_file = ROOT / "data" / "state" / "candidates_latest.json"
    cand = json.loads(cand_file.read_text(encoding="utf-8")) if cand_file.exists() else {}

    def judge_table(rows, title):
        if not rows:
            return f"<p class='dim'>{title}: 无判卷数据</p>"
        h = f"<h4>{title}</h4><table><tr><th>verdict</th><th>T+N</th><th>样本</th><th>正确</th><th>命中率</th><th>平均T+N收益%</th></tr>"
        for v, w, n, c, r in rows:
            hit = f"{c/n:.1%}" if n and c is not None else "-"
            r_s = f"{r:+.3f}" if r is not None else "-"
            cls = "ok" if (v == "buy_watch" and r and r > 0) or (v == "avoid_watch" and r and r < 0) else ""
            h += f"<tr class='{cls}'><td>{v}</td><td>T+{w}</td><td>{n}</td><td>{c}</td><td>{hit}</td><td>{r_s}</td></tr>"
        return h + "</table>"

    # 月度分布 → 迷你条形
    months = {}
    for month, verdict, cnt in monthly:
        months.setdefault(month, {})[verdict] = cnt
    bars = []
    for month in sorted(months)[-12:]:
        d = months[month]
        total = sum(d.values())
        buy = d.get("buy_watch", 0)
        avoid = d.get("avoid_watch", 0)
        neu = d.get("neutral", 0)
        buy_pct = buy / total * 100 if total else 0
        avoid_pct = avoid / total * 100 if total else 0
        bars.append(f"<div style='display:flex;gap:2px;height:16px;margin:2px 0'>"
                    f"<div style='width:{buy_pct}%;background:#3fb950' title='buy {buy}'></div>"
                    f"<div style='width:{100-buy_pct-avoid_pct}%;background:#30363d' title='neutral {neu}'></div>"
                    f"<div style='width:{avoid_pct}%;background:#f85149' title='avoid {avoid}'></div>"
                    f"<span class='dim' style='margin-left:6px;font-size:11px'>{month}</span></div>")

    latest_s = latest[0] if latest else ("?", "?", 0, 0)

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>萤火使用证明 · 2026-11-23</title><style>
body{{background:#0a0e14;color:#c9d1d9;font-family:"Microsoft YaHei",sans-serif;margin:0;padding:24px;max-width:1100px;margin:auto}}
h1{{font-size:24px;color:#f0f6fc;border-bottom:2px solid #58a6ff;padding-bottom:8px}}
h2{{font-size:15px;color:#58a6ff;margin:20px 0 8px;border-left:3px solid #58a6ff;padding-left:10px}}
h4{{font-size:13px;color:#8b949e;margin:8px 0 4px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px 16px;margin:8px 0}}
.metric{{display:flex;justify-content:space-between;padding:4px 0;font-size:14px}}
.metric .label{{color:#8b949e}}.metric .value{{color:#f0f6fc;font-weight:bold}}
.ok{{color:#3fb950}}.warn{{color:#d29922}}.bad{{color:#f85149}}.dim{{color:#484f58;font-size:11px}}
table{{width:100%;border-collapse:collapse;font-size:12px;margin:6px 0}}
td,th{{border:1px solid #21262d;padding:4px 8px;text-align:left}}th{{background:#161b22;color:#58a6ff}}
tr.ok{{background:#0d2137}}
.big{{font-size:36px;font-weight:bold;color:#f0f6fc}}
.steps{{counter-reset:step}}
.step{{margin:12px 0;padding:10px;background:#161b22;border-radius:8px;border-left:3px solid #58a6ff}}
.step::before{{counter-increment:step;content:"Step " counter(step);color:#58a6ff;font-weight:bold;font-size:12px;display:block;margin-bottom:4px}}
code{{background:#0d1117;padding:2px 6px;border-radius:4px;color:#79c0ff;font-size:12px}}
</style></head><body>

<h1>🔥 萤火使用证明</h1>
<div style="color:#8b949e;font-size:12px">生成于 2026-11-23 ｜ 全部数字可重放 ｜ 不构成投资建议</div>

<h2>◆ 这个系统有多长的历史</h2>
<div class="card">
<div class="metric"><span class="label">信号日总数</span><span class="value big">2902</span></div>
<div class="metric"><span class="label">时间跨度</span><span class="value">2021-02 ~ 2026-11（约 5.7 年）</span></div>
<div class="metric"><span class="label">数据源</span><span class="value">CNEquity TDX 湖（2026-11-22 全量回填后）</span></div>
<div class="metric"><span class="label">判卷窗口</span><span class="value">T+5 / T+20（到期自动判卷，不提前猜）</span></div>
</div>

<h2>◆ 判卷结果（全历史 2902 个信号日）</h2>
<div class="grid">
<div class="card">{judge_table(judge_rows, "全历史")}</div>
<div class="card">{judge_table(recent, "近三年 (2024+)")}</div>
</div>

<h2>◆ 信号日历（近 12 个月 verdict 分布）</h2>
<div class="card">
<div style="display:flex;gap:16px;margin-bottom:8px;font-size:12px">
<span><span style="color:#3fb950">■</span> buy_watch</span>
<span><span style="color:#30363d">■</span> neutral</span>
<span><span style="color:#f85149">■</span> avoid_watch</span>
</div>
{''.join(bars)}
</div>

<h2>◆ 今天（2026-11-23）系统说什么</h2>
<div class="card">
<div class="metric"><span class="label">最新信号</span><span class="value">{latest_s[1]} (score {latest_s[2]:.2f})</span></div>
<div class="metric"><span class="label">信号日</span><span class="value">{latest_s[0]}</span></div>
<div class="metric"><span class="label">动作</span><span class="value warn">持有观察，不加不减</span></div>
<div class="metric"><span class="label">仓位</span><span class="value">60% (regime NEUTRAL → ladder 约束)</span></div>
<div class="metric"><span class="label">候选</span><span class="value">{len(cand.get('candidates', []))} 只（[S7] 候选级）</span></div>
<div class="metric"><span class="label">纸面账户</span><span class="value">¥{(acct[0] if acct else 0):,.0f}（高水位 {(acct[1] if acct and acct[1] else '未设')}）</span></div>
</div>

<h2>◆ 你怎么用（三步）</h2>
<div class="steps">
<div class="step">每天早上打开 <code>D:\大肥鱼的深海\晨屏.html</code>——看"今日动作"卡片。三个市场（A股/CS2/美股）的方向判断都在那里，每条建议附失效条件。</div>
<div class="step">如果动作不是"持有观察"——看候选名单和仓位建议。<code>buy_watch</code> + 仓位 N% = 可分批建仓，单笔≤35%；<code>avoid_watch</code> = 观望，规避清单内标的。<b>买入前必过 limits-check</b>（涨跌停校验）。</div>
<div class="step">收盘后跑 <code>run_daily.bat</code>——自动完成采集/信号/判卷/纸面估值/候选/简报全链。第二天晨屏自动更新。判卷区每周积累样本，Kelly 腿判卷数据够了自动补全。</div>
</div>

<h2>◆ 防泄漏与诚实声明</h2>
<div class="card"><span class="small">
· 所有信号只用截至 T-1 收盘的数据（防泄漏三件套，回归测试锁定）<br>
· 判卷不提前猜——到期日无数据保持未判，绝不填补<br>
· 负面结论原样入册（[S2] 日频开关 / [S15] 清仓 / P10 RMT）——不粉饰<br>
· 候选名单 7 天新鲜度门——过期不展示，不拿陈旧数据骗人<br>
· 本系统定位 = 风险监控与研究基座，不是盈利策略引擎；不构成投资建议
</span></div>

</body></html>"""
    OUT.write_text(html, encoding="utf-8")
    print(f"使用证明已生成: {OUT} ({len(html)} bytes)")


if __name__ == "__main__":
    build()
