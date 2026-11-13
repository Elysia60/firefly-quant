# 萤火计划 · 项目全书

> 版本 v0.2 · 2026-11-13 · 五天战记整合本
> csqaq-monitor 第四代 · 股市版 · 本文是全部项目资料的**唯一入口**,各文档为分卷
> 核心理念:**飞蛾扑火,向死而生**——结论必须可对账,负面结论原样入注册表

---

## 一、这是什么(一句话)

**A 股市场的"防自欺机器"**:一套把每个市场信念自动送进审判(对账→事件研究→regime 门控→显著性检验→meta-labeling)、无论生死都原样记账的量化研究系统。它不承诺赚钱——它承诺**你手里没有一个没被审过的信念**。

**定位声明**:风险监控与研究基座,不是盈利策略引擎;不构成投资建议,不公开荐股。

---

## 二、四天战记(时间线)

| 阶段 | 产出 |
|---|---|
| **D0 选型** | WorkBuddy PoC×4(AKQuant 涨跌停缺口源码级证实/akshare 限流实测/CNEquity 湖验证/节假日泄漏撮合级关闭)+ GitHub 深度筛查 275→14(0 命中:审计方法论无现成开源) |
| **D1 数据底座** | 生产仓 21 提交:store/calendar/limits(Decimal 舍入黄金测试)/collect(四项硬要求)/doctor;PoC-4 复跑 5/5;**东财限流防线实弹验证**;TDX 湖×新浪 244/244 天逐日一致;中证800 一年 22.4 万行 |
| **D2 对账记分牌** | signals 三分项 + forecast 自动判卷(T+5/T+20 交易日窗)+ 首份真实记分牌;**[S1] 发现**:avoid 反向线索 42.9% |
| **D3 审判深化** | n_eff 重叠修正(揭穿 buy n_eff=1)+ 成本进账本 + 指数 12 年回填(2917 天)+ 全历史回放 5792 信号;[S1] 三审定案(v1 反向→v2 regime→v3 相对弱势 p=0.001) |
| **D4 门控终审** | regime.py(年线滞回+宽度+波动三票二)+ 信号 v3 三分项全腿(两融贪婪度)+ **[S1] 终审(分庭:bull 无信息/neutral −1.33pp/bear −1.01pp,三重信号定义复现)**+ **[S2] 负面结论**(日频开关全变体被证伪,含显著性检验)+ **[S3] 候选**(月末效应,多重校正后边缘)+ 八轮侦察全归队 |
| **D5 元标签与风控** | [S1]反方①波动率匹配通过(收缩率 29.2%)+ audit strata 分层 + riskfactors 四因子(Beta/RSTR/DASTD/Amihud)+ **P8-V0 实弹:meta-labeling 无判别力→[S4] 负面注册** + 计划任务 astock-daily 上线 + 项目全书 |

---

## 三、系统架构(现状)

```
astock-monitor/(21 提交,98 测全绿)
├── astock_monitor/
│   ├── config/store.py      SQLite WAL+幂等账本+Parquet 原子写
│   ├── collect.py           四项硬要求(限速/退避/冷却持久化/新浪回退)+cne CLI 对齐
│   ├── calendar.py          CNEquity 湖日历+新浪对拍(2952 天零分歧)+交易日窗口加法
│   ├── limits.py            涨跌停校验层(Decimal 四舍五入到分,15 黄金测试)
│   ├── signals.py           三分项信号 v3(趋势+动量+情绪,防泄漏:决策只用截至昨日)
│   ├── forecast.py          对账记分牌(n_eff 重叠修正+成本进账本+三档敏感性)
│   ├── regime.py            门控引擎(年线滞回 1.01/0.96+宽度+波动,三票二+5日去抖)
│   ├── audit.py             审计三件套(NW HAC t/stationary bootstrap/事件研究置换)
│   ├── sentiment.py         涨停池每日抢救+两融回补+宽度历史回算
│   ├── regime.py            已并入上文;riskfactors.py Barra 纯价量四因子(Beta/RSTR/DASTD/Amihud)
│   ├── metamdl.py           meta-labeling 引擎(YZ 波动/triple-barrier/IRLS/purged 折)
│   └── doctor.py/cli.py     七项自检+九个子命令
├── scripts/verify/          poc4_rerun/crosscheck_sina/regime_audit/gated_strategy_sim/calendar_audit
├── results/                 四份判定书(JSON,全部可复现)
├── docs/                    week3-report/optimization-roadmap(P1-P7)
├── METHODS.md               方法论正本——**结论数字只在这里定义一次**
└── data/                    湖:196 万行/905 只/2014-11 起 + 两融 3426 行 + 宽度 1143 天
```

**技术栈纪律**:核心包纯标准库(csqaq 移植);ML/数据层独立 venv;静态 HTML 看板(零 CDN);bug 修复必须带测试。

---

## 四、结论注册表(完整,引用必须带编号)

| # | 结论 | 状态 |
|---|---|---|
| [S1] | avoid_watch 携带真实相对弱势信息(p≤0.001),**适用域=中性/熊市庭;牛市庭无信息**。三重信号定义(v1/v2/v3)复现 | 已证明(限适用域) |
| [S1]-反方 | ①波动率匹配对照未做——若 d_obs 收缩过半则降级为波动率代理;②门控参数为文献先验未做敏感性 | 开放推翻观测 |
| [S2] | **avoid→空仓日频全变体不优于买入持有**(六组对照:B 0.13/E 0.56/F 1.095≈基准 1.144);F−A 显著性检验 NW t=0.257/CI 跨零 → F≈A。鞭打成本+漂移支配,csqaq 教训#2 复现 | 已证明(负面) |
| [S2]-反方 | ①多起点 bootstrap 未做;②半仓+走廊若翻正改写为条件式(半仓已测:不救) | 开放推翻观测 |
| [S3] | 月末效应候选:倒数第 2 交易日 T+5 +0.53pp;**p_raw=0.029,Bonferroni×2 后 0.058 边缘未过线**;n_eff≈28 | 候选(边缘) |
| 春节 | 方向与文献一致(节后 +0.84pp)但 n=13 分辨力不足 | 观察中,不构成依据 |
| [S4] | meta-labeling V0 无判别力(校准表平坦,OOS 无技能;策略改善=机械执行更少) | 已证明(负面,V0);V1 强特征开放 |
| [S1]-反方① | 波动率匹配对照:收缩率 29.2%<50% → 信息独立于波动状态 | 检验通过 ✅ |
| [S5] | **新闻情绪因子候选(PoC-0 登记,未实装)**: LLM 打分(文心闪电深度思考 API,成本 −30% 口径来自百度世界2026)对 PIT 新闻档案出日度情绪腿;**数据探针 2026-11-14**: ①新闻联播文字档案 ak.news_cctv **PIT 可回放 ✅**(日期参数化/含全文/14条/日,宏观政策情绪面); ②个股新闻 ak.stock_news_em 当前环境崩(pyarrow 正则 bug, akshare 1.18.96)不可用; ③index_news_sentiment_scope SSL 被阻断不可用。可行路径=新闻联播宏观情绪腿,个股腿 blocked on 数据源修复/换源 | 候选(PoC-0);**DSR 试验数记账: 本候选计入 1**;V1 落地前必须先过: 档案回放完整性审计+情绪腿 shift(1) 防泄漏+与现有两融腿的增量信息检验 |

**注册表精神**:负面结论占一半;每条带反方陈述与推翻观测;引用数字必须能追溯到 METHODS.md 或 results/ 原始行。

---

## 五、十轮侦察成果索引(GitHub+国内外)

> **全部报告已落盘:`docs/research/`(R1 选型 / R2+R9 审计与元标签 / R3+R8 数据面与日历 / R4 regime / R5 因子与AI / R6 ML工程 / R7 Barra与仓位)

| 轮 | 领域 | 关键发现 | 采纳/拒绝 |
|---|---|---|---|
| 1 | 架构选型 | qlib 重/akshare 限流实测/CNEquity PIT 唯一/AKQuant 涨跌停缺失 | CNEquity 试点+akshare 主+AKQuant 试点+qlib 只读定义 |
| 2 | 统计审计 | NW HAC/stationary bootstrap/事件研究 RI/DSR 四口径陷阱 | audit.py 纯标准库自研;arch 只对拍 |
| 3 | 情绪数据 | 涨停池仅留 3 周(**抢救**)/两融单次全量/北向已死/资金流不可回补 | 涨停池每日+两融回补 ✅;北向零投入 |
| 4 | regime 门控 | **规则法唯一天然因果**;年线滞回 1.01/0.96(A股实测);HMM 平滑后验=隐蔽泄漏 | regime.py 三票二;HMM 只许 walk-forward+手写前向滤波 |
| 5 | 因子库+AI | 华泰 101 因子 A 股幸存者 7 个;**全开源无"审计进反馈回路"** | Alpha158-lite 40+华泰 7;记分牌 MCP 化=差异化空位 |
| 6 | ML 工程 | 8 条动工检查清单(标签口径一票否决/超额+rank 标签/purge≥horizon/保守参数/模型记分牌) | skfolio CPCV 候选;mlfinlab 已闭源勿依赖 |
| 7 | Barra+仓位 | 纯价量 5 因子现在可算(**Size 必须等股本快照**);仓位=min(vol_target,ladder,半Kelly) | riskguard 熔断可借;pyfolio/fullKelly 不借 |
| 8 | 日历+TSFM | 春节效应学术最硬;交割日=伪影;**TSFM 方向预测=炼金术**(51.7% 天花板),波动率微调唯一正证据 | 春节+月末已审;TSFM 波动率实验排观察清单 |

---

## 六、方法论资产(可迁移到任何市场/项目)

1. **结论必须可对账**:信号落盘→到期自动判卷→注册表(含反方陈述+推翻观测)
2. **诚实统计**:n_eff 修正/小样本标注/多重校正/负面结论占一半
3. **成本先于策略**:成本进账本层+敏感性三档(变号即警报)
4. **防泄漏三件套**:决策只用截至昨日/缺口不前向填充/质量标注不静默修正
5. **基准必须是对照日**:裸正确率 vs 50% 会被漂移欺骗([S1] v1→v3 的教训)
6. **先搜本机→再查 GitHub→三行分析才动手**(五规则筛查,借公式不借代码)
7. **数字正本规则**:结论数字只在 METHODS.md 定义一次
8. **真实生活优先**:GBK/合盖/限流/断网都要成立;可靠=不需要人记得
9. **数据工程的边际价值 = 历史深度 × 信噪比 × 可持续性**(三项全占才接)
10. **半自动是个人开发者的正确形态**:agent 提案+人过审,审计不能外包

---

## 七、验证与复现

```bash
python -m unittest discover -s tests -t .     # 115 测,零联网
python -m astock_monitor.cli doctor           # 七项自检
python -m astock_monitor.cli signal / forecast-summary
python -m astock_monitor.cli audit-signal --verdict avoid_watch --window 5
python -m astock_monitor.cli collect-daily / collect-sentiment
python scripts/verify/regime_audit.py         # [S1] 终审复现
python scripts/verify/gated_strategy_sim.py   # [S2] 六组对照复现
python scripts/verify/calendar_audit.py       # [S3] 复现
python scripts/build_dashboard.py             # 看板(零 CDN 单文件)
```

证据文件:`results/poc4_rerun_verdict.json`(5/5)· `regime_audit_verdict.json`(分庭)· `gated_strategy_sim.json`(六组)· `calendar_audit_verdict.json`(日历)

---

## 八、路线图(P1-P7 定案,详见 optimization-roadmap.md)

P1 情绪分深化(两融斜率已接/龙虎榜 2005 起回补/大宗)→ P2 审计升级(DSR 对拍/SPA)→ P3 regime 门控复验(个股 12 年全量后)→ P4 自动化闭环(schtasks ✅ astock-daily 已上线/备份/DSH MCP 插件/NapCatQQ)→ P5 ML 层(8 条检查清单+40 因子+行业分层 TopK)→ P6 风险模型(纯价量 5 因子+%var 列+仓位三选最小)→ P7 日历清单扩展(两会 placebo/缴税日/制度断点分期)

**数据接口优先级**(边际价值=深度×信噪比×可持续性):股本快照(补 Size,最高)> 龙虎榜 > 大宗 > 资金流(只攒数)> 北向(零)

---

## 九、已知局限(全量)

L1 宽度历史自回算起(口径=800 只成分) / L2 退市股股本换手缺失 / L3 EM 限流未独立复验(~5min 级冷却已实测) / L4 CNEquity 单贡献者(原始层可 akshare 重建) / L5 历史 ST 无 PIT / L6 幸存者偏差(成分口径) / L7 regime 特征随数据完整度漂移([S2]-F 教训) / L8 个股湖 196 万行(12 年全量 ~280 万,续传可补) / L9 龙虎榜 EM 源暂不可用(result=None,待冷却或换交易所官网源)

---

## 十、对外一页(求职/展示用)

**项目**:萤火——A 股机器学习选股研究系统(csqaq-monitor 第四代)
**一句话**:一套把市场信念自动送进审判的量化研究系统——四天里它推翻自己两次、验证一个 p=0.001 的结论、证伪一条"人人都信"的择时路。
**亮点故事**(面试可直接讲):
1. 引擎在国庆假日真实成交了卖单——我在撮合级(成交时间戳而非 bar 时间戳)把泄漏关掉,两源日历 1697 天零分歧背书
2. 银行家舍入会把涨停价算错一分钱(10.45×1.1→11.49,正确 11.50)——Decimal ROUND_HALF_UP + 黄金测试钉死
3. 信号"回避期"看起来是反向指标(44%)——n_eff 修正→事件研究→regime 门控三审后:信息真实(p=0.001)但只在中性/熊市庭,基准必须是同条件对照日而非抛硬币
4. 把 p=0.001 的结论翻译成策略后**全军覆没**(六组对照)——相对弱势信息≠日频择时收益;这条负面结论比任何"实盘截图"都值钱
**工程**:98 单测/零联网可复现/双源对账/零依赖核心包/结论注册表制度
**技术栈**:Python(标准库+LightGBM 规划)/SQLite WAL/Parquet/Rust 引擎对接/静态 HTML/MCP 插件规划

---

*本文由四天战记整合;更新时在 git 历史里,别在正文里抹历史。*
*务必要疯狂地怀抱雄心,且还要疯狂地真诚。——特吕弗(幻方 2023 公告引用)*