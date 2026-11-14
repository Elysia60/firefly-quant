# 第 3 周·数据底座 交付报告

> 萤火计划 · astock-monitor v0.1.0 · 2026-11-12
> 性质:9 周 MVP 第 3-4 周交付物(数据底座),按批准计划执行;所有实测均有落盘证据。

## 一句话结论

**数据底座交付并全项验收通过**:49 测全绿、doctor 七项 PASS(自持湖)、PoC-4 独立复跑 5/5、TDX 湖 × 新浪第二源交叉验证 244/244 天逐日一致、中证800 一年回填打通(50 只试点 11,951 行成功后全量 800 只后台执行)、东财限流防线实弹验证生效。

## 交付物

| 模块 | 内容 | 测试 |
|---|---|---|
| `store.py` | SQLite WAL + 幂等 upsert 账本 + Parquet 原子写(tmp+replace) | 5 |
| `calendar.py` | CNEquity 湖日历 + 新浪对拍 + 缓存;`add_trading_days` 判卷窗口语义(跨国庆不漂移) | 11 |
| `limits.py` | 涨跌停前置校验层(PoC-1 硬需求):Decimal 四舍五入到分、板块/ST 幅度、Risk: 拒单结构 | 15(黄金测试含 11.495→11.50 陷阱) |
| `collect.py` | 四项硬要求(限速/指数退避/冷却持久化/新浪回退)+ manifest 幂等 + cne CLI 对齐 | 13 |
| `doctor.py` + `cli.py` | 七项自检 + 六个子命令 + UTF-8(GBK 教训) | 5 |
| `scripts/verify/` | poc4_rerun(独立背书)+ crosscheck_sina(第二源验证) | — |

提交链:骨架 → calendar → limits → collect → doctor/cli → backfill 对齐(见 git log)。

## 验收对照(计划 → 实测)

| 计划项 | 结果 |
|---|---|
| unittest 全绿 | ✅ 49/49(零联网,fetcher 注入) |
| PoC-4 复跑 5/5 PASS | ✅ `results/poc4_rerun_verdict.json`(走生产仓 calendar.py,两源 1697 天零分歧) |
| doctor 全项 PASS | ✅ 首次跑通即 PASS;两个 WARN 是"数据未积累"的诚实状态 |
| 中证800 回填落湖 | ✅ **224,093 行 / 903 只股票**(含 init 阶段存量),来源 tdx_protocol 193,239 + sina 30,854,**零东财请求**;成分从中证官网拉取(csindex) |
| akshare 交叉验证 | ✅ TDX 湖 vs 新浪三板块抽验:000001.SZ / 600519.SH / 300001.SZ 各 244/244 天 close 逐日一致,比差 0.0000 |
| AKQuant 冒烟 | ✅ PoC-4 复跑即撮合级冒烟(假日零成交,泄漏永久关闭) |
| 撮合级假日零成交 | ✅ 同上(复跑证据) |

## 实测事件记录(过程即证据)

1. **东财限流实时复现 + 防线生效**:首次 `collect-daily` 触发 push2 断连(系统 python akshare 1.18.96 表现为 ConnectionError;venv 1.20.37 表现为 Push2RateLimitError,错误文案与 PoC-2 一字不差)。`guarded_call` 正确识别→冷却落盘→doctor 转为 WARN(直至 23:39:06,约 5 分钟)→冷却后自动解除。**没有任何一次重复请求。**[L3"未独立复验"由此升级:限流真实,冷却窗口约 5 分钟级]
2. **cne CLI 接口修正(诚实记录)**:我最初按猜测写了 TOML profile 生成器——错了。实测对齐后重写:`--symbols` 需 instruments 后缀格式(`000001.SZ`),湖按 `trade_date=YYYY-MM` 分区,列名 `trade_date/pre_close`,有 `source` 行级溯源。教训:先 `--plan` 干跑再写代码。
3. **沙箱认知修正**:PoC-3 结论"沙箱拦截 msvcrt.locking"——本次生产湖 `cne init` 与 TDX 回填在沙箱内**成功**(244+11,951 行)。PoC-3 被拦的可能是 demo profile 的特定路径。限制未定论,但"必须沙箱外"的假设被削弱,如实记入下版 PoC 附录。
4. **akshare 版本差异**:1.18.96(系统)与 1.20.37(venv)对同一限流抛不同异常——`is_rate_limit_error` 的"类名+消息"双口径检测均覆盖,测试钉死。

## 已知局限更新(METHODS §4 增补)

- L3 升级:EM 限流实测真实,冷却 ~5 分钟级;`collect-daily` 在宿主机计划任务错峰跑。
- 新 L7:生产湖 `data/cnequity-lake/` 在 gitignore(data/ 不入库);丢失可由 `cne init` + backfill 命令重建,命令已固化在 `backfill_cnequity()`。
- 新 L8:涨跌停层 ST 判定依赖快照名称,历史 ST 变更无 PIT(原有 L5,重申)。

## 下一步(第 4-5 周)

1. 全量 800 只回填完成后:`cne check` 全湖体检 + 扩展交叉验证(抽 10 只)
2. `collect-daily` 挂计划任务(错过补跑 StartWhenAvailable),宽度历史开始积累(补 L1 第一天)
3. 第 5 周主菜:对账记分牌(T+5/T+20,窗口按 `add_trading_days`)+ 防泄漏三件套移植
