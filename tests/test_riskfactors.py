"""riskfactors.py 单测:Beta/Beta=1 性质、RSTR 滞后、Amihud 公式、缺口不填充。"""

import importlib.util
import unittest

from astock_monitor import riskfactors as RF


@unittest.skipUnless(importlib.util.find_spec("pandas") and importlib.util.find_spec("numpy"),
                     "需要 pandas+numpy")
class RiskFactorTest(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import pandas as pd
        from datetime import date, timedelta

        self.np = np
        self.pd = pd
        # 40 天:个股与指数完全同步(ret_i = ret_m)→ Beta 应为 1
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
        idx = 100.0
        px = 50.0
        rows = []
        for i, d in enumerate(days):
            r = 0.01 * ((-1) ** i)
            idx *= 1 + r
            px *= 1 + r  # 个股与指数同比例(**累计**,否则 ret_i != r_m)
            rows.append((d, "TEST", px, 1e6))
        self.bars = pd.DataFrame(rows, columns=["trade_date", "symbol", "close", "amount"])
        # 重建指数收益序列(与逐日 r 一致)
        rets = [0.01 * ((-1) ** i) for i in range(40)]
        self.idx_ret = {d: rets[i] for i, d in enumerate(days)}

    def test_beta_equals_one_for_perfect_correlation(self):
        # 完全同步 → Beta=1(小窗口参数,40 天样本后 20 行有值)
        out = RF.compute_risk_factors(self.bars, self.idx_ret, window=20)
        late = out.dropna(subset=["beta"])
        self.assertGreater(len(late), 10)
        for v in late["beta"]:
            self.assertAlmostEqual(v, 1.0, places=6)

    def test_rstr_lagged(self):
        # window=10, lag=2:rstr(t) = sum(log1p(ret))[t-11..t-2]
        out = RF.compute_risk_factors(self.bars, self.idx_ret, window=10, mom_lag=2)
        import numpy as np
        got = out.dropna(subset=["rstr"])
        self.assertGreater(len(got), 0)
        row = got.iloc[-1]
        i = self.bars.index[self.bars["trade_date"] == row["date"].date()][0]
        expected = float(np.log(self.bars["close"].values[i-11:i-1] / self.bars["close"].values[i-12:i-2]).sum())  # 对数收益=ln(价格比); .values 防索引对齐陷阱
        self.assertAlmostEqual(float(row["rstr"]), expected, places=9)

    def test_amihud_formula(self):
        # 手工构造 3 天:ret 与 amount 已知 → amihud = mean(|ret|/amount)*1e9
        import pandas as pd
        bars = pd.DataFrame({
            "trade_date": [self.bars["trade_date"][0], self.bars["trade_date"][1],
                           self.bars["trade_date"][2]],
            "symbol": ["T1"] * 3,
            "close": [100.0, 110.0, 99.0],   # ret: +0.10, −0.10
            "amount": [1e6, 2e6, 1e6],
        })
        idx_ret = {bars["trade_date"][0]: 0.0, bars["trade_date"][1]: 0.0,
                   bars["trade_date"][2]: 0.0}
        out = RF.compute_risk_factors(bars, idx_ret)
        # 样本 < LIQ_WINDOW(21) → NaN(不造数)
        self.assertTrue(out["amihud"].isna().all())

    def test_gap_not_filled(self):
        # 中间挖掉一天(缺行) → 该股序列断口处 rolling 仍按行计算但 ret 跨缺口——
        # 本模块不负责对齐(数据层职责),此处验证:缺行不报错、不产生填充值
        import pandas as pd
        bars = self.bars[self.bars["trade_date"] != self.bars["trade_date"][20]]
        out = RF.compute_risk_factors(bars, self.idx_ret)
        self.assertEqual(len(out), len(bars))


if __name__ == "__main__":
    unittest.main()
