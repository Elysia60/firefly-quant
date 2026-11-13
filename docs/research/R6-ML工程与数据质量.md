# R6 · ML 工程细节 + 数据质量监控 + 多市场适配侦察报告

> 侦察日期:2026-11-13 · 已落 roadmap P5(8 条动工检查清单)

## 一、LightGBM 选股工程细节

### 标签构造三选
| 标签 | 横截面排序表现 |
|---|---|
| 未来 N 日绝对收益 | 受 regime 主导,学到 beta 而非 alpha,IC 随牛熊波动 |
| **超额收益** | 去市场分量,IC 稳定性明显更好(GKX RFS 2020) |
| **截面 Rank 化** | 对离群值/regime 最不敏感,与 IC 口径一致;丢幅度(TopK 无损) |

**共识:N 日超额 + 截面 rank 化最稳**。激进派:LambdaRankIC(arXiv 2605.00501,把 Rank IC 写成可微 loss,每日一个 group);Label Alchemy(Coqueret & Guida 2026)目标工程对比。
qlib 标签偏移约定 `Ref($close,-2)/Ref($close,-1)-1` 值得照抄——T 信号→T+1 成交写进定义,三处一致。

### 预处理顺序(华泰标准)
```
复权价算因子 → 截面去极值(MAD×3 或 1%/99%) → 截面中性化(行业哑变量+对数市值回归残差) → 截面标准化(zscore/rank)
```
全逐日截面、不跨期累积 → 天然 PIT。用 RankNorm 可省去极值。

### 样本加权与不可交易
- 时序衰减 exp(−λ·age) 在滚动/扩展重训下增益不大——**借"扩展窗+定期重训"不调权重**
- 华泰口径:剔 ST/PT、剔下一交易日涨跌停与停牌;(a) 训练评估都剔 vs (b) 训练保留评估必剔——至少评估层严格执行,三档限价分开
- 回归/排序无类别不平衡问题(这也是不用二分类的理由)

### 过拟合控制
- early stopping 口径=**验证集逐日截面 Rank IC 均值/ICIR,不是 RMSE**;或 objective=lambdarank/xendcg + group=每日股票数
- 保守参数:num_leaves 15-31、max_depth 4-6、min_data_in_leaf 数百-千、lr 0.01-0.05、feature_fraction 0.5-0.8、bagging 0.7-0.9+freq 1-5、lambda_l1/l2 0.1-10、max_bin 64-128、path_smooth/extra_trees
- **特征重要性:跨 CV 折 mean(|SHAP|) 中位数+离散度,跨折方差大直接弃用**(PMC 2024 指南;gain 对高基数有偏)
- 多种子集成(2024 卖方:50 个 LightGBM 离散度当分歧度指标)
- Optuna/FLAML 可用但**搜索空间限死上述区间**

### Purged CV 接合
- skfolio `CombinatorialPurgedCV`(sklearn 兼容,活跃)或 eslazarev/purged-cross-validation(含路径重建)
- purge ≥ 标签 horizon;embargo 再加 1-2×horizon;CPCV 多路径算 IC 分布分位数而非只看均值
- mlfinlab 已闭源收费勿依赖

## 二、数据质量监控

- **Great Expectations 不值**(重基建,领域化检查匹配不上);pandera 是唯一值得考虑的 schema 层
- 量化专用开源几乎空白;Market Data Sanity Checker(GitHub Action)的**检查项清单值得抄**
- **该自检的 6 条规则**:
  1. 日历完整性:exchange_calendars(前身 zipline,支持 XSHG 等 50 所)对账"应交易日有无数据"+"不该出现的日期"
  2. OHLC 一致性:high≥max(o,c)、low≤min(o,c)、量≥0
  3. 跳变:|pct_change| 超板块涨跌停幅度+容差=异常
  4. **复权断裂:对账比逐日涨跌幅或复权因子,不比价格**(Tushare FAQ 铁律:前复权随 end_date 变);复权因子只在除权除息日跳变
  5. 停牌语义:量=0+价格横走 ≠ 缺行;akshare 两者混着来
  6. adtk/stumpy 收益有限,人工阈值更可控

## 三、多市场适配(yfinance/ccxt)

### yfinance 最大的坑
- **2025 起 auto_adjust 默认 True**:Close 就是复权价、Adj Close 消失、**历史复权价随未来分红持续重写**(issue #2280/#2308)——违背 PIT
- 适配:auto_adjust=False + actions(splits/dividends)自算复权因子落库(与 A 股 raw+factor 口径统一)
- **幸存者偏差:Yahoo 基本无退市股**——只能做"当前存活+指数"研究级,**不能做选股回测**
- 指数价格指数无复权概念,长期超额用 ^SP500TR 类全收益
- 日切=交易所本地 naive 日;DST 切换日(3/11 月)显式测试

### ccxt(加密日线)
- `fetch_ohlcv` 返回 [ts, o, h, l, c, v],**ts=开盘时间 UTC 毫秒**;1d=UTC 00:00 切日、无停牌概念
- **since/limit 不统一**(Binance 1000/Kraken 720/部分忽略)→ 统一分页循环+timestamp 去重+查 has['fetchOHLCV']
- volume 默认 base 币数量;quote 要另取——schema 分 volume_base/volume_quote
- 缺 K=流动性枯竭/下架/宕机,与 A 股"停牌"是不同状态字段
- **跨市场合并禁 naive date join**(同一天 crypto UTC 线与美股只重叠 4.5h)

### 统一 schema 最小清单
symbol(市场前缀)/market/ts_open_utc/trade_date_local(交易所时区折算)/OHLC raw/adj_factor(自算)/volume_base/volume_quote/currency/status(trading|suspended|delisted)/limit_up_down/source/ingested_at

## 借/不借
**借**:华泰三件套(剔除规则/预处理顺序/训练窗对比)、qlib 标签约定、skfolio CPCV、LambdaRankIC 思路、SHAP 跨折稳定性+多种子集成、exchange_calendars、Sanity Checker 清单、ccxt 分页去重模式、双时间戳字段设计
**不借**:mlfinlab(闭源)、绝对收益标签、无约束搜索、RMSE 早停、二分类标签、GX 全家桶、yfinance 当生产源、pre-adjusted 单列存储、跨市场 naive join

## 四、ML 层动工前 8 件事(检查清单全文见 optimization-roadmap.md)
1 标签口径一票否决(单一函数) 2 超额+rank 标签 3 逐日截面预处理管线 4 purge≥horizon+embargo 5 早停=RankIC 6 保守参数+种子集成 7 可交易性硬规则(limits.py 已就绪) 8 模型记分牌(无记录不进回测)

## 链接
华泰 AI 选股概览: crm.htsc.com.cn/doc/2020/10750101/fce4a859 · 华泰单因子: .../dae9cd9e · GKX: academic.oup.com/rfs/article/33/5/2223/5758276 · qlib benchmarks README · LambdaRankIC: arXiv 2605.00501 · Label Alchemy: SSRN · skfolio CPCV: skfolio.org · SHAP 实践: pmc.ncbi.nlm.nih.gov/articles/PMC11513550 · exchange_calendars: github.com/gerrymanoim/exchange_calendars · pandera: github.com/unionai-oss/pandera · yfinance #2280: github.com/ranaroussi/yfinance/issues/2280 · Teddy Koker 幸存者偏差: teddykoker.com/2019/05 · ccxt Manual wiki
