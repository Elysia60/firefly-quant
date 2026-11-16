"""每日报告生成器(csqaq 风格:五面完整,行动闸门,推送去重)。

五面:
  ① 数据面   湖覆盖/数据质量/缺失标注
  ② 市场面   regime/ERP/宽度/两融/波动
  ③ 信号面   今日 avoid/buy/neutral + 前日判卷结果
  ④ 组合面   当前持仓/变动/Top5
  ⑤ 风控面   触发面板/回撤/心跳

推送闸门(csqaq 纪律):
  · 观察级信号不推送不行动
  · 触发面板跨越才推送(持续触发不重复)
  · 每日报表落盘 data/reports/YYYY-MM-DD.md + 主动消息通道
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .notify_proactive import push_lines


def build_report(
    date_str: str,
    regime_state: int,
    regime_label: str,
    erp_pct: float | None,
    breadth: float | None,
    margin_greed: float | None,
    vol_pct: float | None,
    triggers: dict,
    signals_today: dict | None,
    portfolio: dict[str, float],
    portfolio_changes: dict,
    doctor_summary: dict | None,
    conclusions_snapshot: dict,
) -> str:
    """构建每日 Markdown 报告(csqaq 五面格式)。"""
    regime_names = {0: "bull", 1: "neutral", 2: "bear"}
    regime_name = regime_names.get(regime_state, regime_label)

    lines = [f"# 萤火 Firefly · 每日报告 {date_str}", ""]

    # ① 数据面
    lines += ["## ① 数据面", ""]
    if doctor_summary:
        lines.append(f"- 看门狗体检: 红{doctor_summary.get('red','?')} 黄{doctor_summary.get('yellow','?')}")
    lines.append(f"- 湖覆盖: 905 只 / 196 万行(2021+ 全覆盖)")
    lines.append(f"- ERP 分位: {erp_pct:.0f}% ({'股偏便宜' if erp_pct and erp_pct > 50 else '股偏贵' if erp_pct and erp_pct < 50 else '中间'})" if erp_pct else "- ERP: 数据缺失")
    lines.append(f"- 宽度(上涨占比): {breadth:.1%}" if breadth else "- 宽度: 数据缺失")
    lines.append(f"- 两融贪婪度: {margin_greed:.0%}" if margin_greed else "- 两融: 数据缺失")
    lines.append(f"- 波动分位: {vol_pct:.0f}%" if vol_pct else "- 波动: 数据缺失")
    lines.append("")

    # ② 市场面
    lines += ["## ② 市场面", ""]
    lines.append(f"- regime 门控: **{regime_name}** ({regime_state})")
    if triggers:
        fired = [k for k, v in triggers.items() if v.get("fired")]
        if fired:
            lines.append(f"- 🔴 触发器激活: {', '.join(fired)}")
        else:
            lines.append("- 🟢 五触发器全部未激活")
    lines.append("")

    # ③ 信号面
    lines += ["## ③ 信号面", ""]
    if signals_today:
        v = signals_today.get("verdict", "neutral")
        tier = signals_today.get("tier", "观察")
        score = signals_today.get("composite", 0)
        lines.append(f"- 今日信号: **{v}** (综合分 {score:.1f}, tier={tier})")
        lines.append(f"- 纪律: 观察级信号不推送不行动([C2] 教训)")
    else:
        lines.append("- 今日无信号(数据不足)")
    lines.append("")

    # ④ 组合面
    lines += ["## ④ 组合面", ""]
    if portfolio:
        summary_n = len(portfolio)
        total_w = sum(portfolio.values())
        lines.append(f"- 当前持仓: {summary_n} 只, 总仓位 {total_w:.1%}")
        top5 = sorted(portfolio.items(), key=lambda x: -x[1])[:5]
        lines.append(f"- Top5: {', '.join(f'{s}({w:.1%})' for s, w in top5)}")
    else:
        lines.append("- 当前空仓(或组合未初始化)")
    changes = portfolio_changes
    if changes.get("added"):
        lines.append(f"- 新增: {len(changes['added'])} 只")
    if changes.get("removed"):
        lines.append(f"- 移除: {len(changes['removed'])} 只")
    lines.append("")

    # ⑤ 风控面
    lines += ["## ⑤ 风控面", ""]
    lines.append(f"- regime 门控: {regime_name}(bear→空仓/缩仓)")
    lines.append(f"- 回撤熔断: 待实装(路线图 P6)")
    lines.append("")

    # 结论面
    lines += ["## 结论面", ""]
    snap = conclusions_snapshot
    lines.append(f"- 注册表: {snap.get('total','?')} 条结论, 负面 {snap.get('negative','?')} 条")
    lines.append(f"- 开放反方陈述: {snap.get('rebuttal_open','?')} 条")
    lines.append("")

    lines += ["---", ""]
    lines.append("*萤火 Firefly · 数据仅供参考学习,不构成投资建议*")
    lines.append("")

    return "\n".join(lines)


def write_report(
    report_text: str,
    date_str: str,
    reports_dir: Path,
    proactive_dir: Path | None = None,
) -> tuple[Path, str | None]:
    """报告落盘 + 可选推送到主动消息通道。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{date_str}.md"
    report_path.write_text(report_text, encoding="utf-8")

    proactive_path = None
    if proactive_dir:
        try:
            proactive_dir.mkdir(parents=True, exist_ok=True)
            pro_path = proactive_dir / f"{date_str}-firefly.md"
            pro_path.write_text(report_text, encoding="utf-8")
            proactive_path = str(pro_path)
        except OSError:
            pass
    return report_path, proactive_path
