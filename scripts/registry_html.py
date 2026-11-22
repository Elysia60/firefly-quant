# -*- coding: utf-8 -*-
"""registry_html.py — 结论注册表 HTML 化（2026-11-23 · 首个对外可视化）"""
import re
from pathlib import Path

METHODS = Path(r"C:\Users\14676\Documents\02-项目开发\股市量化\astock-monitor\METHODS.md")
OUT = Path(r"D:\大肥鱼的深海\结论注册表.html")

src = METHODS.read_text(encoding="utf-8", errors="replace")

# 提取结论注册表 3d 段
m = re.search(r"## 3d\..*?(?=## 3f)", src, re.S)
registry_md = m.group(0) if m else ""
lines = registry_md.split("\n")

# 解析表格行
entries = []
for line in lines:
    if line.startswith("| [S") and "---" not in line:
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 5:
            sid = cols[1]  # [S1] or [S1]-反方
            conclusion = cols[2]
            evidence = cols[3]
            status = cols[4]
            entries.append({"id": sid, "conclusion": conclusion,
                            "evidence": evidence, "status": status})

def classify(status):
    s = status.lower()
    if "已证明" and "负面" in status: return "neg"
    if "已证明" in status or "关闭" in status or "通过" in status: return "pos"
    if "候选" in status or "边缘" in status: return "cand"
    if "反方" in sid.lower() or "反方" in status: return "counter"
    if "观察" in status or "样本" in status: return "obs"
    return "desc"

def status_color(status):
    if "负面" in status: return ("#f85149", "负")
    if "已证明" in status and "负面" not in status: return ("#3fb950", "正")
    if "候选" in status: return ("#d29922", "候选")
    if "反方" in status or "推翻" in status: return ("#58a6ff", "反方")
    if "观察" in status or "描述" in status: return ("#8b949e", "描述")
    return ("#8b949e", "—")

cards = []
for e in entries:
    sid = e["id"]
    color, tag = status_color(e["status"])
    # 提取结论核心(截取前 120 字)
    conc = e["conclusion"][:200]
    conc = re.sub(r"\*\*(.+?)\*\*", r'<b>\1</b>', conc)
    ev = e["evidence"][:100] if e["evidence"] else "—"
    st = e["status"][:80]
    cards.append(f"""
<div class="card {'neg' if '负面' in e['status'] else 'pos' if '已证明' in e['status'] and '负面' not in e['status'] else 'other'}">
<div class="head"><span class="badge" style="background:{color}22;color:{color}">{tag}</span>
<b>{sid}</b></div>
<p class="conc">{conc}</p>
<p class="dim">证据: {ev}</p>
<p class="dim">状态: {st}</p>
</div>""")

neg_count = sum(1 for e in entries if "负面" in e["status"])
pos_count = sum(1 for e in entries if "已证明" in e["status"] and "负面" not in e["status"])
cand_count = sum(1 for e in entries if "候选" in e["status"])
counter_count = sum(1 for e in entries if "反方" in e["id"])
total = len(entries)

html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>萤火结论注册表 · {total} 条</title><style>
body{{background:#0a0e14;color:#c9d1d9;font-family:"Microsoft YaHei",sans-serif;margin:0;padding:24px;max-width:1000px;margin:auto}}
h1{{font-size:24px;color:#f0f6fc;border-bottom:2px solid #58a6ff;padding-bottom:8px}}
.sub{{color:#8b949e;font-size:13px;margin-bottom:16px}}
.stats{{display:flex;gap:12px;margin:16px 0}}
.stat{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 16px;text-align:center}}
.stat .n{{font-size:24px;font-weight:bold}}.stat .l{{font-size:11px;color:#8b949e}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px;margin:8px 0}}
.card.neg{{border-left:3px solid #f85149}}
.card.pos{{border-left:3px solid #3fb950}}
.card.other{{border-left:3px solid #58a6ff}}
.head{{margin-bottom:6px}}.badge{{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold}}
b{{color:#f0f6fc}}.conc{{font-size:13px;line-height:1.6;margin:4px 0}}
.dim{{color:#484f58;font-size:11px;margin:2px 0}}
.filter{{display:flex;gap:8px;margin:12px 0}}
.filter button{{padding:4px 12px;border-radius:6px;border:1px solid #30363d;background:#161b22;
color:#c9d1d9;cursor:pointer;font-size:12px}}
.filter button.active{{background:#1a3a5c;color:#58a6ff;border-color:#58a6ff}}
</style></head><body>
<h1>🔬 萤火结论注册表</h1>
<div class="sub">来源: astock-monitor/METHODS.md §3d ｜
纪律: 引用任何因子结论必须带编号，没有编号的结论不存在 ｜
含反方陈述+推翻观测+DSR 计数 ｜ 不构成投资建议</div>

<div class="stats">
<div class="stat"><div class="n" style="color:#3fb950">{pos_count}</div><div class="l">已证明(正)</div></div>
<div class="stat"><div class="n" style="color:#f85149">{neg_count}</div><div class="l">已证明(负)</div></div>
<div class="stat"><div class="n" style="color:#d29922">{cand_count}</div><div class="l">候选(边缘)</div></div>
<div class="stat"><div class="n" style="color:#58a6ff">{counter_count}</div><div class="l">反方陈述</div></div>
<div class="stat"><div class="n">{total}</div><div class="l">总计</div></div>
</div>

<div class="filter">
<button class="active" onclick="f('all')">全部</button>
<button onclick="f('pos')">已证明</button>
<button onclick="f('neg')">负面</button>
<button onclick="f('other')">候选/反方</button>
</div>

<div id="list">{"".join(cards)}</div>

<div class="sub" style="margin-top:16px">
DSR 记账纪律: 每次假设检验/变体尝试计入 Deflated Sharpe Ratio 试验总数——
试错次数被真实统计，防止未来自己骗自己。<br>
八步 SOP: 取数→复权→算因子→打分→IC→分组→回测→下结论——跳过任何一步不许进注册表。
</div>

<script>
function f(cls){{
  document.querySelectorAll('.card').forEach(c => {{
    c.style.display = (cls === 'all' || c.classList.contains(cls)) ? '' : 'none';
  }});
}}
</script>
</body></html>"""

OUT.write_text(html, encoding="utf-8")
print(f"结论注册表 HTML 已生成: {OUT} ({len(html)} bytes, {total} 条)")
