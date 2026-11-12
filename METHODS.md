# METHODS — astock-monitor 方法论正本(骨架 v0.1)

> 本文档是项目的方法论正本:**结论数字只在这里定义一次**,其余文档为快照+回指(数字正本规则,继承 csqaq-monitor)。
> 项目定位:A 股风险监控与研究基座,**不是盈利策略引擎**;不承诺 alpha,结论必须可对账。

## 0. 选型定案(第 1 周 PoC 闭环,证据见 WorkBuddy 沙箱 POC_REPORT.md)

| 层 | 定案 | 依据 |
|---|---|---|
| 数据采集 | akshare 主适配(限速+退避+新浪回退+落盘缓存) | PoC-2 实测:EM 滑窗限流 ~16 次触发;退市股新浪源可用(000003,317 行) |
| 历史回填 | **CNEquity TDX 试点(先中证 800)**,akshare 只做交叉验证 | PoC-3 用户沙箱外实测 exit=0;EM 按股回填 5400 只在限流面前不可行 |
| 交易日历 | **CNEquity 湖内 trading_calendar 表**(新浪对拍兜底) | PoC-4:两源 1697 天零分歧;AKQuant 不传日历会在假日成交(撮合级证据) |
| 回测引擎 | AKQuant 试点(`cn_stock_t1_low_fee`),**必显式传 trading_calendar** | PoC-1:T+1/印花税方向 PASS;涨跌停两项 FAIL(源码三重证据) |
| 涨跌停 | **自研前置校验层(limits.py)** | PoC-1 硬需求;黄金测试钉死舍入边界 |
| 因子层 | Alpha158 只读 qlib 定义,自实现精简版 | 依赖树纪律(qlib 90 天仅 4 提交,mlflow/redis 过重) |
| 对账/审计/周期 | 全自研(csqaq-monitor 平移) | GitHub 深度筛查 275→14:**0 命中**,差异化资产 |
| 面板 | 静态 HTML + Chart.js | 理念 8:静态 HTML 优于常驻服务 |

## 1. 数据治理

- 存储:SQLite(WAL+幂等 upsert)做账本;Parquet 湖两层 `raw`(原样落盘)→ `normalized`(统一 schema)。
- **原始层永远可由 akshare 独立重建**(CNEquity 单贡献者退路,GitHub 筛查定案)。
- 缺口处理:缺口不前向填充(防泄漏三件套之一);数据质量标注给决策者,不静默修正。
- 限流纪律:全进程单并发、请求间隔 ≥1s;触发 `Push2RateLimitError` 记冷却截止时间并持久化,冷却期内直接拒绝,**绝不立即重试**(PoC-2:反复触发封禁 40 分钟+)。

## 2. 涨跌停规则(数字正本,limits.py 实现)

- **涨跌停价 = round_half_up(昨收 × (1±pct), 2)**——精确到分,四舍五入。
  禁止用 float `round()`:银行家舍入会把 10.45×1.1=11.495 舍成 11.49(正确 11.50)。
- 幅度表(config.json `limits.board_pct` 为准):

| 板块 | 代码前缀 | 幅度 |
|---|---|---|
| 主板 | 60xxxx / 00xxxx | ±10% |
| 创业板 | 300xxx / 301xxx | 2020-08-24 起 ±20%,此前 ±10% |
| 科创板 | 688xxx | ±20% |
| 北交所 | 43/83/87/88/92xxxx | ±30% |
| 主板 ST | 主板代码 + 名称含 ST | ±5%(创业/科创 ST 仍 ±20%) |

- 规则:涨停价禁买、跌停价禁卖;拒绝原因与 AKQuant `reject_reason` 同构(`Risk: ...`,可读可归因)。
- 已知限制:ST 名称按采集快照传入,历史 ST 状态变更未做 PIT(局限 L5);新股上市初期无涨跌停由上层以 `no_limit` 标注。

## 3. 判卷窗口语义(数字正本)

- `add_trading_days(d, n)`:n≥1 返回**严格晚于 d 的第 n 个交易日**;n=0 返回 d 当天(若为交易日)否则下一交易日。
- T+5/T+20 前向收益 = close(add_trading_days(信号日, n)) / close(信号日) − 1,窗口全按交易日数,长假不漂移(例:2026-09-30 + 5 交易日 = 2026-10-14,国庆 10-01~10-07 跳过)。

## 4. 已知局限(诚实声明,继承编号风格)

| # | 局限 | 处理 |
|---|---|---|
| L1 | 宽度(涨跌家数)自 collect-daily 上线日起才有历史 | 日更快照顺手产出,历史不可回放,只声明 |
| L2 | 退市股新浪源股本/换手列为空 | 接受缺失;流动性因子对退市股降权 |
| L3 | akshare 限流阈值 ~16 次为单次实测,**未独立复验** | 采集层按此保守设计;复验列入待办 |
| L4 | CNEquity 单贡献者(1 人,859 提交) | 只当交叉验证与加速,原始层可独立重建 |
| L5 | 历史 ST 状态无 PIT,涨跌停层用传入名称判定 | 上层传入当日名称;标记数据质量 |
| L6 | 幸存者偏差:akshare 在市列表回测历史偏乐观 | 与 csqaq L3 同源,方向上加固负面结论 |

## 5. 复现命令链

```bash
python -m unittest discover -s tests -t .        # 全部单测(零联网)
python -m astock_monitor.cli doctor              # 自检
python -m astock_monitor.cli calendar-check      # 日历:湖读取+新浪对拍+新鲜度
python -m astock_monitor.cli collect-daily       # 日更:按日期全市场快照(1 请求)
python -m astock_monitor.cli backfill --universe hs800 --start 2024-01-01 --end 2025-01-01
python -m astock_monitor.cli limits-check --code 600519 --prev-close 10.45 --price 11.50 --side buy
python scripts/verify/poc4_rerun.py              # PoC-4 独立复跑背书(需 WorkBuddy venv)
```
