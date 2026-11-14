# 🔥 萤火 Firefly(firefly-quant)

> **A-share quant research system that grades its own conclusions.**
> 一套会给自己判卷的 A 股量化研究系统:对账记分牌 / regime 门控 / 事件研究级审计 / 结论注册表(含反方陈述)。

| | |
|---|---|
| License | CC BY-NC-SA 4.0(可用·须署名·禁商用·相同方式共享) |
| 出处 | github.com/Elysia60/firefly-quant(唯一官方源,防伪见 [PROVENANCE.md](PROVENANCE.md)) |
| 测试 | 147 单测全绿(零联网可复现) |

> csqaq-monitor 第四代 · 股市版。核心理念:**飞蛾扑火,向死而生**——结论必须可对账,负面结论原样入注册表。
> 定位:**风险监控与研究基座,不是盈利策略引擎**。不构成投资建议,不公开荐股。

## 一句话

把 csqaq-monitor 的方法论(结论注册表 / 对账记分牌 / 七项统计审计 / 防泄漏三件套)平移到 A 股:akshare 主采集 + CNEquity TDX 回填 + 自研涨跌停校验层 + 撮合级防假日泄漏。**五天产出四条注册结论——两条负面、一条 p=0.001、一条候选边缘;每条带反方陈述与推翻观测。**

## 快速开始

```bash
python -m unittest discover -s tests -t .   # 单测(零联网)
python -m astock_monitor.cli doctor         # 自检
```

方法论正本见 [METHODS.md](METHODS.md)——**所有结论数字只在那里定义一次**。
PoC 证据链(第 1 周):`<本地沙箱>\astock_poc\POC_REPORT.md`(只读留证)。

## 路线(9 周 MVP)

数据底座(本周)→ 对账记分牌+防泄漏(第 5 周)→ 周期引擎+[H1] 判卷(第 6 周)→ 审计前三项+因子(第 7 周)→ Ridge+含费回测(第 8 周)→ 静态面板+全链路(第 9 周)。LightGBM/LSTM/生存者研究/出清压力测试在 MVP 过审计后排期。
