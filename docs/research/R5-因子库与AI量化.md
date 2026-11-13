# R5 · 因子库与 AI 量化侦察报告(ML 层 + AI 管线层预研)

> 侦察日期:2026-11-13 · 已落 roadmap P5/P8

## 一、因子库开源实现对比

### Alpha101
| Repo | Star | 状态 | 判词 |
|---|---|---|---|
| yli188/WorldQuant_alpha101_code | ~875 | 1 commit 归档 | 公式存档 |
| popbo/alphas | ~571 | 中文,A 股向 | alpha101+alpha191+alphalens+backtrader 全流程 |
| JoinQuant/jqdatasdk alpha191.py | 权威 | 聚宽官方维护 | **Alpha191 对拍基准** |
| DolphinDB WQ101Alpha 教程 | 活跃 | 文档 | "公式参考答案" |

**qlib 官方 contrib 只有 Alpha158/360 handler,没有 Alpha101**。原论文(arXiv 1601.00991)101 因子全部只用日频 OHLCV+vwap+returns——**PIT 坑不在因子公式,在复权口径/停牌填补/ST 剔除时点**。

### Alpha191(国泰君安短周期价量)
- yupoet/aurumq-rl:191 全覆盖+25 算子(算子层设计值得抄)
- **坑:WMA/DECAYLINEAR/SUMAC 开源复现错误率极高——任何实现先与聚宽版对拍**

### A 股实证短名单(华泰《单因子测试之海量技术因子》2019 对 101 因子全量回测)
**长期有效 7 个:Alpha#3、#13、#15、#16、#44、#50、#55**(短周期反转+量价相关最有效;#15 "神仙因子")——全部纯 pandas 可算。

### 萤火 lite 因子库定案
- 基座:Alpha158 五类(K线/动量/波动/极值位置/量价)× 4 窗口(5/10/20/60)≈ 40 个
- 外源首批 10 个:华泰 7 + Alpha#6/12 + Alpha191 纯价量 3-5(先对拍)
- **不借**:Alpha360(NN 用,LightGBM 浪费)、需市值/行业/基本面者(无 PIT 数据)、DolphinDB/yli188(仅公式答案)

## 二、组合构建(零 cvxpy)

- **行业分层 TopK**:先行业权重对齐基准(主动行业暴露=0)→ 行业内按因子分排序选股(东方证券《组合优化是与非》2017;光大 2018 实证:**分层拿到优化器大部分超额**)——名额按基准权重分配,±1 名额=±2% 偏离网格
- 组合内惯例:**逆波动率加权**(w_i=(1/σ_i)/Σ)+ 单票 35% 封顶 + 10% 现金 + 整手取整
- **vol targeting 是仓位层**:min(1, 目标波动/已实现波动),月频或触发式
- ERC 在选股组合性价比低(股票相关高);真要用:Spinu 凸形式+坐标下降(~50 行 numpy)
- 不借:cvxpy/scipy 优化链(TopK 分层已覆盖 80%)、完整优化器(无风险模型数据支撑=假精度)

## 三、AI agent × 量化 2026 现状

| 项目 | 2026 状态 | 判词 |
|---|---|---|
| **微软 RD-Agent(Q)**(MIT,活跃) | 因子+模型联合闭环(提出→实现→qlib 回测→反馈);第三方实测 CSI300 IC 0.0532(+26.7% vs Alpha360)、**<$10/周期**(o3-mini),DeepSeek 后端 1-2 美元 | 可用性最高;障碍=要转 qlib bin 格式绕开自家审计层 |
| **AlphaAgent**(KDD 2025,~400★) | A 股 CSI500+S&P500;三重正则:**AST 原创性(防重复因子)+假设-语义对齐+复杂度控制**;AlphaAgentEvo 进 ICLR 2026 | A 股适配最好,论文配套需自包工程壳 |
| TradingAgents v0.7(114k★) | 分档模型配置;HN 有效性质疑;TradingAgents-CN(通达信/DeepSeek) | 分析 agent 不可复现,只借架构 |
| ai-hedge-fund(64k★) | 新增真风控(回撤 10% 减半/20% 转现金)+live tracking | 借风控闸门思想 |
| Alphagen/FactorMiner(清华 2026) | RL/LLM 因子生成 | 了解 |

**闭环空位**:有"挖掘→回测→反馈"闭环,**没有一家把数据质量审计/PIT/双源对账嵌入 agent 反馈回路——萤火对账记分牌 MCP 化 = 差异化空位**。

## 四、萤火两层最短路径

**ML 层(2-4 周)**:40 Alpha158-lite + 10 华泰验证因子,自家湖纯 pandas;LightGBM+横截面 Rank IC;组合层行业分层 TopK+逆波动率+vol targeting,零 cvxpy。
**AI 管线层(1-2 周,ML 基线后)**:不自建框架——**把审计做成 agent 工具**(数据湖查询/IC 计算/记分牌/回测 → MCP 工具,DSH 现成体系);LLM 提假设写实现,记分牌打分回填;抄 AlphaAgent 两条正则(AST 相似度拒重复+复杂度上限,~100 行);半自动(agent 提案+人过审)是正确形态。

## 链接
RD-Agent: github.com/microsoft/RD-Agent · RD-Agent(Q): arXiv 2505.15155 · AlphaAgent: github.com/RndmVariableQ/AlphaAgent + arXiv 2502.16789 · TradingAgents: github.com/tauricresearch/tradingagents · ai-hedge-fund: github.com/virattt/ai-hedge-fund · Awesome-Agents-for-Investment: github.com/Sasha-Cui/Awesome-Applied-Agents-for-Investment · 华泰海量因子: crm.htsc.com.cn/doc/2019/10750101/dae9cd9e · aurumq-rl: github.com/yupoet/aurumq-rl · 东方证券组合优化: datayes.com/uqer/dongfang21.pdf
