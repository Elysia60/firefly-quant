# GitHub 开源项目深度筛查报告 · 「扑火」A 股量化监控系统

- 核查时间：2026-11-12
- 数据来源：GitHub REST API 实时拉取（gh cli 2.95.0）
- 结论先行：**没有项目能整体替代 csqaq-monitor 的方法论**；最优路线是"数据层试点 CNEquity + akshare 兜底，回测层试点 AKQuant，因子层只读 qlib，周期/判卷/注册表自研"。

---

## 一、筛选漏斗

| 阶段 | 数量 | 说明 |
|---|---:|---|
| 批量检索（12 组关键词） | 275 | akshare / A 股量化 / qlib / rqalpha / vnpy / regime / walk-forward / 监控看板 / 周期研究 |
| 去重后候选 | 265 | 领域词加权 + 维护活跃度粗排 |
| 深度核验 | 14 | 元数据、README、依赖、根目录、贡献者、近 90 天提交 |
| 完全匹配审计优先方法论 | 0 | 结论注册表 / 对账记分牌 / 七项审计无现成开源实现 |

### 补遗（外审后修订）：265 → 14 的排除方法

如实说明：这是**两级筛查**，不是 265 个逐仓库人工核验。

- **第一级（API 深核，14 个）**：按领域词加权分（fit：akshare/qlib/rqalpha/a-share/alpha158/backtest/regime 等强词）排序后，人工审阅前 90 名的名称/描述/主题标签，选出 14 个做 API 级深核（README 全文、依赖文件、根目录、贡献者数、近 90 天提交数）。
- **第二级（文本级排除，251 个）**：依据检索结果自带的 description/topics 字段排除——纯教程/课程（如 hands-on-qlib）、加密货币专用（qlib-crypto-*）、美股专用（S&P500/US）、无 License 的 1-2 星个人实验、形态不符的大型平台。
- **边界声明**：第二级没有逐仓打开 README 或运行代码，存在漏检可能；"0 命中"的可信度建立在 14 个深核样本覆盖了全部主流方向之上，而非 265 个全量核验。

### 补遗：akfamily 同源风险（AKQuant + AKShare 同组织）

akfamily 组织同时维护 akshare 和 akquant。好处是数据和回测语义天然衔接；坏处是**风险同源**——akshare 的上游站点大改版时，同一批维护者大概率同时受影响，数据和回测两条腿可能一起瘸。缓解：双源对账纪律（新浪/腾讯备源）不依赖 akfamily；AKQuant 只承担回测语义，数据层接口与回测引擎保持解耦。

## 二、核心结论与决策

| 层 | 采用 | 理由 |
|---|---|---|
| 数据底座 | **CNEquity 试点**；akshare 主适配；free-stockdb 仅末位备选 | CNEquity 自带退市/PIT/复权/历史成分，恰好覆盖 P0-1 最痛处；但仅 1 位贡献者，不能当永久基础设施 |
| 回测引擎 | **AKQuant 试点**；失败则沿用 csqaq-monitor 自有回测 | README 明确 `cn_stock_t1_low_fee`：T+1 / 涨跌停 / 印花税 / 整手，且有黄金测试；但项目不足一年、3 位贡献者 |
| 因子层 | **只读 qlib 的 Alpha158 定义**，不引入运行时 | qlib 依赖过重且 90 天仅 4 次提交；因子必须过自己的审计 |
| 对账 / 注册表 / 审计 | **全自研（csqaq-monitor 平移）** | 筛查 0 命中，这是项目差异化资产 |
| 周期 / [H1] | **全自研** | 借 hmm-regime-detection 的防泄漏方法、stockbee 的宽度设计 |
| 监控面板 | 静态 HTML 自研 | 借 stockbee 单文件 HTML 与 PanWatch 告警模式，不引入常驻服务 |

## 三、重点候选明细

### rootSunc/CNEquity（数据层首选试点）
- 1,016 Stars / 1 贡献者 / 近 90 天 100 提交 / Apache-2.0 / Python 3.10+ / v0.23.0
- 技术：DuckDB + Polars + Parquet + FastAPI(可选) + MCP
- 卖点：86 数据集、保留退市股、财报按公告日 PIT、复权因子、历史股票池、行级溯源
- 风险：0.x、单贡献者；README 声明的能力未实测
- 用法：500 只 PoC 通过才作为底座；不通过降级为 akshare 自建 Parquet 层

### akfamily/akshare（主数据适配器，直接采用）
- 23,303 Stars / 25 贡献者 / 近 90 天 100 提交 / MIT / Python≥3.11
- 只当"活接口"，不当数据底座；限流与上游改版风险由我们的原始层承担
- 原计划书"每日 8000 次限额 / 按日循环 1300 次"是社区经验说法，未实测，PoC 必做

### akfamily/akquant（回测引擎试点）
- 2,591 Stars / 3 贡献者 / 近 90 天 100 提交 / MIT / Rust+Python
- 卖点：`broker_profile="cn_stock_t1_low_fee"`、Walk-forward Validation、Polars 因子引擎、104 指标、MCP、黄金测试
- 风险：新项目 + Rust 内核调试成本；必须用构造数据逐日对账兜底

### microsoft/qlib（只借定义）
- 50,221 Stars / 140 贡献者 / 近 90 天 4 提交 / MIT
- 只把 Alpha158 当"公式字典"；不引入 mlflow/redis/gym 等重依赖

### ricequant/rqalpha（排除）
- 回测与风控成熟，但 setup.py 写明商业使用需授权、License 元数据 NOASSERTION、数据绑定 Ricequant 生态

### 其他
- **hello245m/free-stockdb**：3,160 Stars / 2 贡献者，触发社区信号异常阈值，仅末位备选
- **TNT-Likely/PanWatch**：2,460 Stars / 76 提交，监控+TradingAgents 很完整，但 FastAPI+React+115 包依赖树与静态 HTML 纪律冲突；借告警/日报模式
- **vnpy / OpenBB / zvt / QUANTAXIS**：方向不符或生态老化，排除
- **dcimring/stockbee-dashboard**：美股宽度看板，单文件 HTML+SQLite，与理念 8 同频；借 Market Monitor 设计
- **mehmetoaltekin/hmm-regime-detection**：小而精的 Walk-forward HMM（因果滤波/AIC-BIC/whipsaw 过滤）；借方法论不引代码

## 四、最简 MVP（外审修订版：9 周）

| 周 | 动作 | 产出 |
|---|---|---|
| 1 | **三个 PoC 并行**：① AKQuant 四个交易约束黄金测试（涨停买入失败/跌停卖出失败/T+1 阻止当日卖出/印花税只算卖出端）——最优先；② akshare 双维度采集 PoC；③ CNEquity 500 只数据质量 PoC | 三份 PoC 报告 |
| 2 | PoC 复盘 + 选型决定写入 METHODS.md（任一 PoC 失败则重新选型，此周即缓冲） | 数据层 + 回测层选型定案 |
| 3–4 | 数据底座：raw→normalized Parquet、日历/停牌/退市/复权、doctor | 可增量数据层 + 测试 |
| 5 | 对账记分牌（T+5/T+20）+ 防泄漏三件套（核心三项） | 方法论核心层 + 单测 |
| 6 | 最小周期引擎 + H1a/b/c 判卷卡 + 美股→A股传导实验 | cycle-report + 首期定位卡 |
| 7 | 七项审计移植前三项（DSR/块自助法/参数邻域）+ 单因子检验启动 | 审计层第一批 + 因子检验 |
| 8 | Ridge 基线 + 三档含费回测 + 七项审计剩余项 | 实验 JSONL + 审判章节 |
| 9 | 静态面板 + run_daily.bat + doctor + git 自动提交 + 全链路验收 | 一条命令全链路 |

## 五、风险与驳回记录

- **单贡献者风险**：CNEquity(1 人) / AKQuant(3 人)——PoC 通过才引入，原始层永远可由 akshare 独立重建
- **社区信号异常**：free-stockdb 3,160 Stars / 2 贡献者，触发刷号嫌疑阈值
- **License 风险**：rqalpha 非商业条款、OpenBB NOASSERTION——均排除
- **宣传≠事实**：所有候选能力以第 1–2 周 PoC 实测为准
- **只读核查**：未克隆、未安装、未修改任何第三方项目；后续装带 hook 的工具先走 P0/P1/P2 审计
- 所有 Stars / 贡献者 / 提交数为 2026-11-12 GitHub API 实时值；近 90 天按 2026-08-14 起算

---

原始数据存档（同目录）：`repos.jsonl`（275 行检索）、`ranked.json`（265 去重）、`verified.json`（14 仓库核验）、`docs/`（各仓 README 存档）。
