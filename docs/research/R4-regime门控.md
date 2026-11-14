# R4 · Regime 门控侦察报告(已落地 regime.py,[S1] 终审使用)

> 侦察日期:2026-11-13 · **结论先行:规则法(年线/回撤/波动分位/宽度)是唯一"天然因果"的一类**——历史递推函数,shift(1) 后零泄漏、O(n)、无拟合。HMM 必须滚动 refit+在线滤波才因果。

## 一、防泄漏的 regime 识别

### HMM 两个泄漏点(都要堵)
1. **拟合泄漏**:hmmlearn.fit / statsmodels MarkovRegression 是全样本 EM/MLE
2. **推断泄漏**:`predict()`(Viterbi)与 `predict_proba()`(forward-backward 平滑后验 γ)**用了整段未来**——平滑后验 ≠ 滤波概率,最常见隐蔽泄漏

### 防泄漏两正路
- **A. Walk-forward 滚动 refit**(借 ItsSawhill/market-regime-detection 骨架:3 年训练窗、每月 21 日 refit、间隙冻结参数逐日推断)
- **B. 在线前向滤波**(真正 O(n) 因果):冻结参数后手写 3 行前向递推 `α_t(j) ∝ b_j(o_t)·Σ_i α_{t-1}(i)·A_ij`——**hmmlearn 只借引擎和 startprob_/transmat_/means_/covars_,不借 predict 输出**
- 备选 C:BOCPD 贝叶斯在线变点(hildensia/Kats)——天然因果但输出变点概率非状态列,做对照不做主列

### 规则法四件(全天然因果)
年线法 `close.shift(1) > MA250.shift(1)`;回撤阈值(−20% 技术熊);波动率分位 `vol20.shift(1).rolling(500).rank(pct=True)`(**rolling rank 窗含当日必须 shift**);宽度分位。

## 二、A 股牛熊三法对比

| 法 | 数据 | 日度门控可用性 |
|---|---|---|
| **年线法** | 价格当场可算 | **最适合** |
| 估值分位(乐咕 TTM 中位数) | TTM 季度滞后 | 只能月度慢过滤(PE 中枢漂移/熊底盈利收缩反信号/"低分位可以更低") |
| 信用脉冲(社融) | 月频+发布滞后半月 | 只能月度/季度确认过滤(脉冲放量前 30 日跌、后 60 日涨,华尔街见闻) |

## 三、定案的三个门控特征(全事前可算 O(n))

1. **年线滞回**(主):`close.shift(1) > MA250.shift(1)×1.01` 进多 / `×0.96` 退多——**A 股实测参数来自 davidwang0116 回测(比美股 1.03/0.83 窄,牛熊转换更陡)**;可选年线斜率确认
2. **年线宽度** breadth250:站上 MA250 个股占比 >0.6 多 / <0.4 空(湖内可算;中文实践:知乎宽度择时/BigQuant 存量状态;国际:StockCharts S&P1500 above-200MA)
3. **波动否决**:vol20 的 500 日分位 >0.9(华泰"波动率+换手率牛熊分"为进阶版,相关系数 −0.67,双均线择时优于布林带;**不直接抄权重,先核对滚动窗**)

**合成:三票二+5 日持续确认去抖,三态(bear 否决/neutral 不覆盖/bull 确认)**——与 [S1] 兼容:修复年门控的作用是缩短而非替代。

可选 HMM 增强:750 日窗两维特征(日收益+20日波动)fit GaussianHMM K=2~3,按方差排序命名,refit 间隙冻结,前向递推滤波,risk-off = 滤波概率>0.6 且连续 5 日。

## 四、佐证
华泰《A股择时之技术打分体系》规则型策略万得全A 年化 21.05%/mdd −23.74% vs 基准 −55.99%(知乎转述)——纯价格规则在 A 股有效。

## 借/不借速查
| 来源 | 借 | 不借 |
|---|---|---|
| davidwang0116 SMA 回测 | MA250+1.01/0.96 | 杠杆仓位层 |
| ItsSawhill/market-regime-detection | walk-forward 骨架 | KMeans+宏观堆叠 |
| hmmlearn | 引擎+参数属性 | predict_proba 输出 |
| 华泰牛熊研报 | 分位合成思路 | 直接抄权重 |
| QuantsPlaybook(6.9k★ 研报复现库) | 代码风格对照 | 直接运行(tushare 数据源) |
| 乐咕/信用脉冲 | 月度慢过滤 | 日度门控唯一输入 |

## 链接
ItsSawhill: github.com/ItsSawhill/market-regime-detection · hidden-regime: github.com/hidden-regime/hidden-regime · hmmlearn: github.com/hmmlearn/hmmlearn · statsmodels MarkovRegression · hildensia/bayesian_changepoint_detection · davidwang0116 SMA 回测 README · 华泰研报: crm.htsc.com.cn/doc/2019/10750101/465187f1 · QuantsPlaybook: github.com/hugo2046/QuantsPlaybook · 华泰技术打分: zhuanlan.zhihu.com/p/1989424062565483861
