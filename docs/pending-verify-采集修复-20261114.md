# 采集修复 · 交接与待验证（2026-11-14）

> 修的是「日更采集静默失败」：2026-11-13 15:40 首次自动跑，Task Scheduler 显示 Last Result 0，
> 实际只有 doctor 与日历状态被写，湖与 monitor.db 未动；手动复跑在翻页中途被东财断连。

## 已修（提交 913ac33 / 6a34a34 / 88058b4）

1. `collect.fetch_spot_em` 自建快照：先单请求拉满（pz=6000），被截断再按页补齐，每页走 `RateLimiter`。
   替代 akshare `stock_zh_a_spot_em` 的 59 页无间隔翻页（限流诱因）。
2. `is_rate_limit_error`：补 `e.request.url` 判定——requests 的 ConnectionError message 里没有 "push2"，
   旧判据漏判导致冷却未记录；同时把 HTTPError 排除（4xx/5xx 不是限流）。
3. `collect_daily`：非交易日 `status=skipped / reason=non_trading_day`，不把上一交易日快照伪装成当日数据。
4. `run_daily.bat`：全输出落 `logs\daily-*.log`；逐步检查 `errorlevel`；失败以非零退出码收尾
   （Scheduler 的 Last Result 不再假绿）；`chcp 65001` 统一日志编码。

## 已验证（可复现）

- `python -m unittest discover -s tests -t .` → `Ran 121 tests ... OK`（115 → 121，新增 6 个用例）
- `cmd /c run_daily.bat` → `RC=0`：doctor PASS / collect-daily 按周末跳过 / 涨停池 37 行采集成功
- 日志：`logs/daily-20261114-044843.log`，UTF-8 可直接读

## 未验证（pending_verify，依赖外部条件）

- **真实全市场快照的成功路径**：2026-11-14 04:35–05:36，东财 `push2.eastmoney.com/api/qt/clist/get`
  对本机持续返回 `RemoteDisconnected`；同一时段 `push2his`（历史）、`datacenter`（两融）、
  `quote.eastmoney.com` 均 HTTP 200——是**端点级限流**，curl / PowerShell / requests 全部被断。
  已做 12 次、48 分钟退避重试仍未解除，不再继续敲（继续敲只会延长封禁）。
- 验收方法（解封后或交易日 15:40 自动跑后）：
  1. `python -m astock_monitor.cli collect-daily`（交易日）
  2. `data/lake/raw/akshare/spot/dt=YYYYMMDD/part.parquet` 存在且行数 > 4000
  3. `data/lake/normalized/daily_snapshot/dt=YYYYMMDD/part.parquet` 存在
  4. `data/lake/normalized/breadth/dt=YYYYMMDD/part.parquet` 存在，且 up+down+flat 与行数一致
- 不污染生产湖的全链路校验脚本：`C:\Users\14676\Documents\Codex\_tmp_astock\verify_write.py`
  （建临时 cfg，跑 collect_daily，检查三份 parquet 后打印 VERDICT）

## 另：日更脚本仍缺 signal / forecast-judge

`run_daily.bat` 目前只有 doctor → collect-daily → collect-sentiment。
信号与判卷要在 `cli.py` 的 `--require-session` 守卫落地后再接（否则周末会往 forecast_log 写伪信号）；
当前仓库里 `astock_monitor/calendar.py` 与 `cli.py` 有他人未提交改动，本次未触碰。
