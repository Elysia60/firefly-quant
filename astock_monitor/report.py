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

# 触发面板的周期理论身份(Tvede 精读 §6:领先→同步→滞后确认管线)
# 展示层重排依据——[S12] 的非玄学解释:领先灯本来就先于滞后灯
TRIGGER_ORDER = {"T-ERP": 0, "T-杠杆": 1, "T-波动": 2, "T-宽度": 3, "T-年线": 4}


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
    strategy_health: list[dict] | None = None,
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
            fired.sort(key=lambda k: (TRIGGER_ORDER.get(k, 99), k))
            lines.append(f"- 🔴 触发器激活(领先→滞后): {', '.join(fired)}")
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
    if strategy_health:
        for row in strategy_health:
            mark = {"healthy": "🟢", "watch": "🟡", "retired": "🔴",
                    "unknown": "⚪"}.get(row.get("state"), "⚪")
            lines.append(f"- {mark} 策略守护 {row.get('strategy','?')}: "
                         f"{row.get('state','?')}({row.get('reason','')})")
    lines.append("")

    # ⑥ 方法论自检(五层分析法, 2026-11-18 定案)
    # 每层一句核心追问 + 萤火已有资产的对应回答; 意义层只管"为什么建系统",
    # 永不进单日决策回路(单日决策只归纪律层——意义感是仓位失控的源头)。
    lines += ["## ⑥ 方法论自检(五层)", ""]
    if doctor_summary:
        lines.append(f"- 信息层问「我知道什么」: 见①数据面; 体检 红{doctor_summary.get('red', '?')}/黄{doctor_summary.get('yellow', '?')}")
    else:
        lines.append("- 信息层问「我知道什么」: 见①数据面; 体检未运行")
    verdict = (signals_today or {}).get("verdict", "neutral")
    logic_note = {
        "avoid_watch": "适用域=neutral/bear 庭([S1]), bull 庭无信息; 5/5 前导是必要方向非充分信号([S12])",
        "buy_watch": "[S2] 日频开关已证伪——观察级不构成行动依据",
        "neutral": "无方向主张; 反方陈述在册可查",
    }.get(verdict, "无方向主张; 反方陈述在册可查")
    lines.append(f"- 逻辑层问「关系是什么」: 今日 {verdict} → {logic_note}")
    fired = [k for k, v in (triggers or {}).items() if v.get("fired")]
    lines.append(f"- 系统层问「嵌在什么结构」: regime={regime_name}; 触发器 {len(fired)}/5 激活"
                 + (f"({', '.join(fired)})" if fired else "")
                 + "; 反馈回路=alpha→收割→成本→新鲜度([S15] 守恒)")
    greed_s = f"{margin_greed:.0%}" if margin_greed is not None else "缺"
    breadth_s = f"{breadth:.1%}" if breadth is not None else "缺"
    erp_s = f"{erp_pct:.0f} 分位" if erp_pct is not None else "缺"
    lines.append(f"- 人性层问「背后的人怎么想」: 杠杆贪婪={greed_s}, 宽度={breadth_s}, ERP={erp_s}")
    n_fired = len(fired)
    if regime_state == 2 or n_fired >= 2:
        phase = "防御(触发面板接管; 意义层不进决策回路)"
    elif n_fired == 1 or verdict == "avoid_watch":
        phase = "戒备(预注册剧本已就位)"
    else:
        phase = "观察(数据积累中)"
    lines.append(f"- 意义层问「对我意味着什么」: 2027 剧本阶段={phase}")
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
