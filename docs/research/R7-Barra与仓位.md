# R7 · Barra 风格因子 / 绩效归因 / 仓位算法 侦察报告(已落地 riskfactors.py)

> 侦察日期:2026-11-13 · star/维护状态为当日 GitHub API 实测

## 一、Barra CNE5 十风格构造公式(QuantML quant-handbook 23 讲,MSCI CNE5 一致)

| 因子 | 公式要点 | 数据 |
|---|---|---|
| Size | LNCAP=ln(流通市值) | 股本 |
| Beta | 252 日超额收益时序回归,EWMA 半衰 63 | 价+指数 ✅ |
| Momentum | RSTR=Σ(半衰 126)[ln(1+r)−ln(1+r_f)],**T=504 滞后 L=21** | 价+指数 ✅ |
| Residual Vol | 0.74·DASTD+0.16·CMRA+0.10·HSIGMA,对 Beta/Size 正交化 | 价+指数 ✅ |
| Non-linear Size | lnCap³ 残差 | 股本 |
| Value | BTOP=净资产/总市值 | 财报+股本 |
| Liquidity | 0.35·STOM+0.35·STOQ+0.30·STOA | 量+股本(✅近似:ln(21日Σ成交额) 或 Amihud,截面相关 0.9+) |
| Earnings Yield / Growth / Leverage | 财报系 | 财报 |

回归与协方差骨架(**各开源 repo 共同核心,最该借**):截面 WLS(w_i=√流通市值,Breusch-Pagan 拒绝同方差)+ 行业因子"市值加权行业收益和为零"约束(KKT 增广)+ Σ=XFXᵀ+Δ(EWMA+PSD 修正)。CNE6 扩展 Mid-Cap/LTR/EarningsVariability/Quality/Profitability/Investment/DividendYield。

### 开源实现实测
| Repo | Star | 最后提交 | 判词 |
|---|---|---|---|
| ShiliangZhang-nku/Barra_CNE6 | 389 | 2020-01 停更 | 因子最全(15 类),深耦合 Wind 管道不可用;公式书 |
| YTZzzzz/Barra_CNE5 | 184 | 2018 停更 | style_factor.py 结构最贴官方 |
| **quantskills/skill-risk-model** | 2 | **2026-11-05 活跃** | **最值得借的骨架**:输入仅 returns+市值+行业三 DataFrame → WLS 因子收益+EWMA+LedoitWolf 收缩 Σ+逐因子 %var;GPL-3.0 只参考重写 |
| rosie068/BARRA_risk | 84 | 2020 停更 | 课程作业 |
| finexsf/Barra-CNE6-LightGBM | 5 | 2026-03 | 与萤火 ML 层同构可对照 |

**结论:没有拿来即用的高维护库。借 skill-risk-model 骨架 + 停更库的公式细节,自己重写。**

### 纯价量可算性(萤火关键)
- **现在就能算(5 个)**:Momentum RSTR(**滞后 21 日必须**,防反转污染)/Beta/DASTD+CMRA+HSIGMA/Amihud 近似 Liquidity/LTR
- **必须等数据**:Size(股本快照,一年一更即可——**A 股第一解释力因子,优先补**)、NLSize、Value、EarningsYield、Growth、Leverage、Quality 全家族
- 已落地:riskfactors.py 四因子(Beta/RSTR lag21/DASTD/Amihud)

## 二、绩效归因

方法谱系:Brinson(行业维度)/ **因子收益法(Barra 式:选股 vs 风格的正确工具)** / **回归法(FF 式,单因子记分牌最轻:一个 OLS 就够)** / 风险归因(Euler 分解 %var,skill-risk-model 内建)。

开源:stefan-jansen/alphalens-reloaded(686★,2026-10 活跃——**已知坑:默认不 lag 因子,对当日收益算 IC 泄露一期,必须自己 shift**)/ pyfolio-reloaded(623★)/ quantstats(7859★,2026-11 活跃,轻量)/ gghez/pybrinson(小而干净)。

**对记分牌增益(中等但便宜)**:①防"行业/风格暴露冒充 alpha"——分层组合加因子/行业收益贡献分解;②风险侧 %var(因子 vs 特异)——风险 80% 来自已知风格=被风格 beta 携带,ML 训练应正交;③时序回归 alpha 检验(对萤火信号集合回归,增量 alpha t 值)——服务 ML 去冗余。
**不借**:pyfolio/alphalens 整套(重叠+lag 坑)、Brinson 单独引入(无行业数据)。

## 三、仓位算法/资金管理

| 算法 | 公式与要点 |
|---|---|
| 回撤 ladder | exposure=base×f(DD):<10%→1.0,10-15%→0.7,15-20%→0.5,>20% 停新仓;**高水位持久化(防重启绕过)+减仓单永远放行** |
| Kelly/半 Kelly | 连续 f*=μ/σ²;**实操 0.25-0.5 分数(Thorp 2006;A 股肥尾+参数误差,full Kelly 回撤中位数不可忍)+天花板地板** |
| CPPI | exposure=m×(NAV−floor);**m≤1/最大单日跌幅,A 股跌停 gap risk(Cont 2007 SSRN 1021084)下 m 取 2-3 非教科书 4-6**;TIPP 变体 floor 随高水位棘轮 |

三者关系:CPPI/TIPP=连续回撤控制,ladder=分段简化,Kelly=信号质量定价,vol targeting=市场状态定价。**萤火最自然组合:min(vol_target, ladder(DD), 0.5×Kelly) 取最小。**

开源:**SilentFleetKK/riskguard**(68★,2026-07,中文 MIT **核心零依赖带完整测试**:DrawdownCircuitBreaker −45%→−5.6% 真实例子+牛市少赚"保费"诚实展示、审计哈希链、状态持久化——**熔断状态机+测试直接可借**)/ Alpaca-CPPI(公式参考)/ deltaray-io/kelly-criterion(公式)/ polakowo/vectorbt(9832★ 仓位参数化参考)/ Riskfolio-Lib(4605★ 重,非当前瓶颈)。

## 四、萤火下一层最短路径(侦察原文定案)

**第一周(纯价量,无新数据依赖)——因子风险模型 MVP:**
1. 信号引擎旁实现 5 个纯价量风格因子列:RSTR(滞后 21)/Beta/DASTD/CMRA/ln(21日成交额)近似 Liquidity——**已落地 riskfactors.py(四因子)**
2. 记分牌加两列:因子 vs 特异 %var + 逐因子收益贡献

**第二周——仓位层(两三天):**
3. `min(vol_target, ladder(DD), 0.5×Kelly)`;借 riskguard 熔断状态机(减仓放行/高水位持久化);A 股 m≤3、跌停日只降不升

**第三阶段(等数据,不要提前):**
4. 股本快照(静态一年一更,成本最低)→ LNCAP/NLSize——**Size 优先级高于所有财务因子**
5. 财务历史 → Value/EarningsYield/Growth/Leverage(借 CNE5/CNE6 公式)
6. 行业 Brinson 归因等行业分类数据

**明确不借**:pyfolio/alphalens 整库(重叠+lag 坑)、Riskfolio-Lib、full Kelly、各 Barra repo 的 Wind 管道。**真稀缺资源是股本/财务两个数据接口——把接入排期而不是把代码排期。**

## 链接
skill-risk-model: github.com/quantskills/skill-risk-model · Barra_CNE6: github.com/ShiliangZhang-nku/Barra_CNE6 · Barra_CNE5: github.com/YTZzzzz/Barra_CNE5 · QuantML handbook: github.com/QuantMLResearch/quant-handbook(module_06/23) · alphalens-reloaded: github.com/stefan-jansen/alphalens-reloaded · quantstats: github.com/ranaroussi/quantstats · riskguard: github.com/SilentFleetKK/riskguard · Cont 2007: SSRN 1021084 · Risk-Constrained Kelly: blog.quantinsti.com/risk-constrained-kelly-criterion · vectorbt: github.com/polakowo/vectorbt
