"""limits.py 黄金测试:已知答案表(含 float 银行家舍入陷阱边界)/ 板块幅度 / 拒单规则。"""

import unittest
from datetime import date

from astock_monitor import limits


class PriceLimitsGoldenTest(unittest.TestCase):
    """黄金答案表:手工可核,重点钉死 Decimal ROUND_HALF_UP 与 float round 的分界。"""

    def test_half_way_rounds_up(self):
        # 10.45 × 1.1 = 11.495 → 11.50(float round 给 11.49,错)
        # 10.45 × 0.9 = 9.405 → 9.41(float round 给 9.40,错)
        up, dn = limits.price_limits(10.45, "600519")
        self.assertEqual((up, dn), (11.50, 9.41))

    def test_plain_case_11_53(self):
        # 11.53 × 1.1 = 12.683 → 12.68;× 0.9 = 10.377 → 10.38
        up, dn = limits.price_limits(11.53, "600519")
        self.assertEqual((up, dn), (12.68, 10.38))

    def test_main_board_10pct(self):
        up, dn = limits.price_limits(10.00, "600519")
        self.assertEqual((up, dn), (11.00, 9.00))
        up, dn = limits.price_limits(10.00, "000001")
        self.assertEqual((up, dn), (11.00, 9.00))

    def test_chinext_date_dependent(self):
        # 创业板 2020-08-24 注册制改革:此前 10%,之后 20%
        up_old, _ = limits.price_limits(10.00, "300123", on_date=date(2020, 8, 21))
        self.assertEqual(up_old, 11.00)
        up_new, dn_new = limits.price_limits(10.00, "300123", on_date=date(2020, 8, 24))
        self.assertEqual((up_new, dn_new), (12.00, 8.00))

    def test_star_board_20pct(self):
        up, dn = limits.price_limits(10.00, "688981")
        self.assertEqual((up, dn), (12.00, 8.00))

    def test_bse_30pct(self):
        for code in ("430047", "832000", "871981", "889966", "920001"):
            up, dn = limits.price_limits(10.00, code)
            self.assertEqual((up, dn), (13.00, 7.00), msg=code)

    def test_st_main_5pct(self):
        up, dn = limits.price_limits(10.00, "600519", name="ST某某")
        self.assertEqual((up, dn), (10.50, 9.50))
        up, dn = limits.price_limits(10.00, "000001", name="*ST某某")
        self.assertEqual((up, dn), (10.50, 9.50))

    def test_st_on_chinext_still_20pct(self):
        # 创业板 ST 不降档(改革后统一 20%)
        up, dn = limits.price_limits(10.00, "300123", name="ST某某", on_date=date(2021, 1, 1))
        self.assertEqual((up, dn), (12.00, 8.00))


class CheckOrderTest(unittest.TestCase):
    def test_buy_at_limit_up_rejected(self):
        d = limits.check_order("buy", 11.00, 10.00, "600519")
        self.assertFalse(d.allowed)
        self.assertTrue(d.reason.startswith("Risk: LimitUp blocks BUY"))

    def test_buy_below_limit_up_allowed(self):
        d = limits.check_order("buy", 10.99, 10.00, "600519")
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "ok")

    def test_sell_at_limit_down_rejected(self):
        d = limits.check_order("sell", 9.00, 10.00, "600519")
        self.assertFalse(d.allowed)
        self.assertTrue(d.reason.startswith("Risk: LimitDown blocks SELL"))

    def test_sell_above_limit_down_allowed(self):
        d = limits.check_order("sell", 9.01, 10.00, "600519")
        self.assertTrue(d.allowed)

    def test_no_limit_marker_passthrough(self):
        d = limits.check_order("buy", 99.00, 10.00, "600519", no_limit=True)
        self.assertTrue(d.allowed)
        self.assertTrue(d.reason.startswith("no_limit:"))

    def test_decision_carries_audit_fields(self):
        d = limits.check_order("buy", 11.00, 10.45, "600519", name="ST某某")
        self.assertEqual(d.board, "main")
        self.assertEqual(d.pct, 0.05)
        # 精确值:10.45×1.05=10.9725 → 10.97;×0.95=9.9275 → 9.93
        self.assertEqual(d.limit_up, 10.97)
        self.assertEqual(d.limit_down, 9.93)

    def test_board_detection(self):
        self.assertEqual(limits.board_of("600519"), "main")
        self.assertEqual(limits.board_of("000001"), "main")
        self.assertEqual(limits.board_of("300123"), "chinext")
        self.assertEqual(limits.board_of("301236"), "chinext")
        self.assertEqual(limits.board_of("688981"), "star")
        self.assertEqual(limits.board_of("920001"), "bse")


if __name__ == "__main__":
    unittest.main()
