"""alpha_lite.py 单测:因子手算对照 / 标签 shift 语义 / IC 性质。"""
import importlib.util
import unittest
from datetime import date, timedelta

from astock_monitor import alpha_lite as AL


def _have():
    return all(importlib.util.find_spec(m) for m in ("pandas", "numpy"))


@unittest.skipUnless(_have(), "需要 pandas+numpy")
class FactorGoldenTest(unittest.TestCase):
    def setUp(self):
        import pandas as pd
        self.pd = pd
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(30)]
        # 已知序列:close 100→逐日 +2;open=close−1;high=close+2;low=close−2;volume=1000
        rows = []
        c = 100.0
        for d in days:
            o, cl = c - 1, c
            h, l = c + 2, c - 2
            rows.append((d, "T1", o, h, l, cl, 1000))
            c += 2
        self.bars = pd.DataFrame(rows, columns=[
            "trade_date", "symbol", "open", "high", "low", "close", "volume"])  # 行元组首列=日期
        self.bars["trade_date"] = self.bars["trade_date"].astype(str)

    def test_kmid_ksft_golden(self):
        out = AL.compute_factor_panel(self.bars)
        row = out.iloc[11]
        # iloc[11]: close=122, open=121, high=124, low=120(c 从 100 起逐日 +2)
        self.assertAlmostEqual(row["KMID"], (122 - 121) / 121, places=9)
        self.assertAlmostEqual(row["KSFT"], (2 * 122 - 124 - 120) / 121, places=9)

    def test_roc5_golden(self):
        out = AL.compute_factor_panel(self.bars)
        # iloc[10] 的 ROC5 = close[5]/close[10] − 1 = 110/120 − 1
        row = out.iloc[10]
        self.assertAlmostEqual(row["ROC5"], 110 / 120 - 1, places=9)
        self.assertTrue(out["ROC5"].iloc[:5].isna().all())  # 不足 5 日 → NaN

    def test_rsv20_bounds(self):
        out = AL.compute_factor_panel(self.bars)
        rsv = out["RSV20"].dropna()
        self.assertTrue(((rsv >= 0) & (rsv <= 1)).all())  # 单调上涨序列 → RSV 恒为 1
        self.assertAlmostEqual(rsv.iloc[-1], 1.0, places=9)

    def test_shift_direction_leak_proof(self):
        """ROC5 只用过去:篡改末行(未来)收盘,历史行 ROC5 不变。"""
        out1 = AL.compute_factor_panel(self.bars)
        tampered = self.bars.copy()
        tampered.loc[tampered.index[-1], "close"] = 9999.0
        out2 = AL.compute_factor_panel(tampered)
        self.assertTrue(
            (out1.iloc[:-6]["ROC5"].fillna(-9) == out2.iloc[:-6]["ROC5"].fillna(-9)).all())


@unittest.skipUnless(_have(), "需要 pandas+numpy")
class LabelTest(unittest.TestCase):
    def test_label_shift_semantics(self):
        import pandas as pd
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(25)]
        closes = [100.0 + i for i in range(25)]  # close[t]=100+t
        cl = pd.DataFrame({"symbol": "T", "trade_date": [str(d) for d in days],
                           "close": closes})
        panel = pd.DataFrame({"symbol": "T", "date": [str(d) for d in days[:5]],
                              "F": 1.0})
        lab = AL.forward_label(panel, cl, horizon=20)
        # label(t=day1)=close[day1+21]/close[day1+1] − 1 = (121/101) − 1
        self.assertAlmostEqual(lab["label_raw"].iloc[0], 121 / 101 - 1, places=9)

    def test_tail_nan_not_fabricated(self):
        import pandas as pd
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(25)]
        cl = pd.DataFrame({"symbol": "T", "trade_date": [str(d) for d in days],
                           "close": [100.0 + i for i in range(25)]})
        panel = pd.DataFrame({"symbol": "T", "date": [str(days[-1])], "F": 1.0})
        lab = AL.forward_label(panel, cl, horizon=20)
        self.assertTrue(pd.isna(lab["label_raw"].iloc[0]))  # 末尾未到期 → NaN


@unittest.skipUnless(_have(), "需要 pandas+numpy")
class ICTest(unittest.TestCase):
    def test_perfect_factor_ic_one(self):
        import pandas as pd
        # 因子=标签本身 → 每日截面 Spearman IC = 1
        rows = []
        for d in range(30):
            day = date(2024, 1, 1) + timedelta(days=d)
            for i in range(400):
                rows.append((f"S{i}", str(day), float(i), float(i) * 2.0))
        panel = pd.DataFrame(rows, columns=["symbol", "date", "F", "label_raw"])
        ic = AL.daily_spearman_ic(panel, "F", min_n=300)
        self.assertGreater(len(ic), 25)
        summary = AL.ic_summary(ic, nw_window=20)
        self.assertAlmostEqual(summary["mean_ic"], 1.0, places=6)
        self.assertFalse(summary["small_sample"])

    def test_min_n_guard(self):
        import pandas as pd
        rows = [("S1", "2024-01-01", 1.0, 1.0)]
        panel = pd.DataFrame(rows, columns=["symbol", "date", "F", "label_raw"])
        ic = AL.daily_spearman_ic(panel, "F", min_n=300)
        self.assertEqual(len(ic), 0)  # 小截面 → 跳过,不造 IC


if __name__ == "__main__":
    unittest.main()
