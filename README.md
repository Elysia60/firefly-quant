# 🔥 萤火 Firefly(firefly-quant)

> **A-share quant research system that grades its own conclusions.**
> 一套会给自己判卷的 A 股量化研究系统:2902 个信号日 / 结论注册表(含反方陈述+负面入册) / 跨市场共振 / 全链路 126 秒。

| | |
|---|---|
| License | CC BY-NC-SA 4.0(可用·须署名·禁商用·相同方式共享) |
| 出处 | [github.com/Elysia60/firefly-quant](https://github.com/Elysia60/firefly-quant)(唯一官方源,防伪见 [PROVENANCE.md](PROVENANCE.md)) |
| 测试 | **285 单测全绿**(零联网可复现) |
| 全链路 | **126.6 秒**(doctor→signal→judge→candidates→brief,实弹计时) |
| 数据 | CNEquity TDX 湖 + akshare(EM 解耦),全市场回填(2014~今) |
| 定位 | **风险监控与研究基座,不是盈利策略引擎**。不构成投资建议。 |

## 为什么不同：结论注册表

大多数回测只报告成功的策略。萤火**把失败的和成功的放在一起公开**——每条结论带编号、反方陈述、推翻观测和 DSR 试验计数。

```text
已证明(正)     ██░░░░░░░░  若干   avoid_watch 携带真实相对弱势信息(p=0.001,三重复现)
已证明(负)     ████░░░░░░  若干   日频开关不优于买入持有(鞭打成本支配)
候选(边缘)     ██░░░░░░░░  若干   LGBM 组合 IC +0.058(NW t=1.96)/月末效应(p=0.058)
反方陈述       ███░░░░░░░  若干   每条附最可能错因+推翻观测
DSR 记账       ██████████  累计   每次试错被真实统计
```

**查证：结论注册表在量化领域公开实践中不存在。** 这不是更好的回测——是一种不同的做研究的方式。

### 判卷升级(2026-11-23):从手工记账到概率

- **CSCV-PBO**(`astock_monitor/cscv_pbo.py`,零依赖):[S15]-[S17] 策略家族 **PBO=0.503**≈纯噪声基线
  ——"家族内挑最好看的"与随机无异,家族级负面结论获 12870 次精确枚举的概率确认([S22])
- **SOP 第⑨步**:判卷升级进单因子八步 SOP;预注册阈值 ≤0.2 稳健 / 0.2-0.5 保守读 / >0.5 负面结论可信度上升
- **最小 Gaussian HMM**(`astock_monitor/hmm_regime.py`,零依赖):[S21] 许可路径工具就绪
  (缩放前向-后向+Baum-Welch EM+Viterbi,两态恢复 99%),试验窗口待全量湖定型

## 12 年走前模拟(2014-2026)

| | 萤火跟单 | 沪深300 买入持有 |
|---|---|---|
| 年化收益 | -1.1% | +4.3% |
| **最大回撤** | **-28.8%** | **-71.6%** |

系统没有跑赢买入持有。但回撤差了 **42.8 个百分点**——每一次 avoid_watch 都提前发出了信号。这不是"帮你暴富"的系统，是"帮你活下来"的系统。

## 快速开始

```bash
python -m pytest tests/ -q                    # 270 测(零联网)
python -m astock_monitor.cli doctor           # 11 项自检(含 bars 新鲜度)
python -m astock_monitor.cli decision-brief   # 每日决策简报
python scripts/proof_run.py                   # 全链路证明(126s)
python scripts/paper_sim.py                   # 12 年走前模拟
python scripts/registry_html.py               # 结论注册表 HTML
```

## 决策链

```
collect-daily → signal(v3 防泄漏) → regime(三票二) → forecast-judge(到期判卷)
    → candidates(LGBM 5种子) → position(三选最小) → circuit-breaker(只降不升)
    → decision-brief(每日简报) → morning_screen(跨市场共振)
```

## 注册结论一览

| 编号 | 结论 | 状态 |
|---|---|---|
| [S1] | avoid_watch 携带真实相对弱势信息(p=0.001,三重复现,限 neutral/bear 庭) | 已证明 |
| [S2] | 日频开关不优于买入持有(鞭打成本支配) | 已证明(负面) |
| [S3] | 月末效应候选(Bonferroni 后 0.058) | 候选(边缘) |
| [S4] | meta-labeling V0 无判别力 | 已证明(负面) |
| [S7] | LightGBM 13 因子组合 IC +0.056(NW t=2.12 过线) | 候选(边缘) |
| [S8] | avoid = 崩溃检测器(2015 崩盘段 5/5 提前标记) | 方向性发现 |
| [S9] | ERP 分位决定 avoid 可靠性(ERP<50% 时信) | 已证明(交互) |
| [S12] | avoid 前导 regime 转 bear 23~30 天(5/5) | 方向性发现 |
| [S13] | 两融 30 日斜率是市场方向前导 | 已证明(描述性) |
| [S15] | TopK 全调仓不可收割(带内保留=守恒) | 已证明(负面,终审) |
| [S16] | regime 门控=保险(B≥A,保险读法) | 描述性 |
| [S17] | 波动叠加在 20 日粒度无效 | 已证明(负面) |
| [S18] | 两融斜率加速度(非重叠 t=2.398 过线) | 候选注册 |

完整注册表见 [METHODS.md](METHODS.md) §3d——**每条含反方陈述+推翻观测+DSR 计数**。

## 对标

| | 萤火 | [TradingAgents](https://github.com/TauricResearch/TradingAgents) | [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) |
|---|---|---|---|
| 结论注册表+负面入册 | ✅ | ❌ | ❌ |
| 判卷自动化(T+5/T+20) | ✅ | ❌ | ❌ |
| 防泄漏三件套 | ✅ | 未提 | 未提 |
| 熔断状态机 | ✅ | ❌ | ❌ |
| regime 门控 | ✅ | ❌ | ❌ |
| 仓位三选最小 | ✅ | ❌ | ❌ |
| 12 年回测 | ✅ | 短期 | ? |
| 零依赖单机 | ✅ | 需 OpenAI API | 较重 |

完整对标见 [对标报告](../对标报告-萤火vsTradingAgentsvsVibeTrading-2026-11-23.md)。

## 生态

萤火不是孤岛——它与以下系统协同:
- **cs(csqaq-monitor)**: CS2 饰品市场监控 + 周期状态向量 + 买点触发器
- **晨屏**: 跨生态单页总览(两市场动作+共振判断+守护链)
- **看门狗 v4.1**: 11 项健康检查(计划任务/账本锚/内存守门/磁盘/巩固新鲜度)
- **记忆防线 v2**: 账本外置+异地锚+audit 留痕(记忆投毒防线)
- **双层人格探针**: 行为+表征(Anthropic Persona Vectors 适配),分歧分辨假警
