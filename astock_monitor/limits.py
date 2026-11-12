"""涨跌停前置校验层(PoC-1 硬需求:AKQuant v0.3.85 引擎不含涨跌停规则,源码三重证据)。

规则正本 = METHODS.md §2,本模块逐条实现,黄金测试钉死:

1. 涨跌停价 = round_half_up(昨收 × (1±pct), 2),精确到分、四舍五入。
   禁止 float round():银行家舍入把 10.45×1.1=11.495 舍成 11.49(正确 11.50),
   10.45×0.9=9.405 舍成 9.40(正确 9.41)——必须走 Decimal ROUND_HALF_UP。
2. 幅度表:主板 ±10%;创业板 2020-08-24 起 ±20%(此前 ±10%);科创板 ±20%;
   北交所 ±30%;主板 ST ±5%(创业/科创 ST 仍 ±20%)。
3. 规则:涨停价禁买、跌停价禁卖;拒绝原因与 AKQuant reject_reason 同构(Risk: 前缀)。

已知限制:ST 以传入名称判定(历史 ST 变更无 PIT,局限 L5);新股上市初期无涨跌停
由上层以 no_limit=True 显式标注(不在本层猜测)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# 创业板注册制改革日:20% 幅度生效(此前 10%)
CHINEXT_20PCT_SINCE = date(2020, 8, 24)

DEFAULT_BOARD_PCT: dict[str, float] = {
    "main": 0.10,
    "chinext": 0.20,
    "chinext_before_2020_08_24": 0.10,
    "star": 0.20,
    "bse": 0.30,
    "st_main": 0.05,
}


def board_of(code: str) -> str:
    """按代码前缀判板块:main / chinext / star / bse。

    688=科创板;300/301=创业板;43/83/87/88/92 开头=北交所(6 位);
    其余(600/601/603/605/000/001/002/003 等)=主板。
    """
    code = code.strip()
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith(("43", "83", "87", "88", "92")):
        return "bse"
    return "main"


def limit_pct(code: str, name: str = "", on_date: date | None = None,
              table: dict[str, float] | None = None) -> float:
    """该股在 on_date 的涨跌停幅度(METHODS.md §2 幅度表)。

    name 必须传**当日名称**(历史 ST 变更无 PIT,由上层保证,局限 L5)。
    """
    t = table or DEFAULT_BOARD_PCT
    b = board_of(code)
    if b == "bse":
        return t["bse"]
    if b in ("chinext", "star"):
        if b == "chinext" and on_date is not None and on_date < CHINEXT_20PCT_SINCE:
            return t["chinext_before_2020_08_24"]
        return t[b]
    if name and "ST" in name.upper():
        return t["st_main"]
    return t["main"]


def price_limits(prev_close: float, code: str, name: str = "",
                 on_date: date | None = None,
                 table: dict[str, float] | None = None) -> tuple[float, float]:
    """(涨停价, 跌停价),Decimal ROUND_HALF_UP 精确到分。"""
    pct = Decimal(str(limit_pct(code, name, on_date, table)))
    base = Decimal(str(prev_close))
    one = Decimal("1")
    cent = Decimal("0.01")
    up = (base * (one + pct)).quantize(cent, rounding=ROUND_HALF_UP)
    dn = (base * (one - pct)).quantize(cent, rounding=ROUND_HALF_UP)
    return float(up), float(dn)


@dataclass(frozen=True)
class Decision:
    """校验结论:allowed / reason(与 AKQuant reject_reason 同构的 Risk: 前缀)/ 审计字段。"""

    allowed: bool
    reason: str
    board: str
    pct: float
    limit_up: float
    limit_down: float


def check_order(side: str, price: float, prev_close: float, code: str,
                name: str = "", on_date: date | None = None,
                no_limit: bool = False,
                table: dict[str, float] | None = None) -> Decision:
    """下单前置校验:涨停禁买、跌停禁卖。

    side ∈ {"buy","sell"};no_limit=True(新股上市初期等)直接放行并留痕。
    """
    b = board_of(code)
    if no_limit:
        return Decision(True, f"no_limit: {code} 无涨跌停约束(新股期等,上层标注)", b, 0.0, 0.0, 0.0)
    pct = limit_pct(code, name, on_date, table)
    limit_up, limit_down = price_limits(prev_close, code, name, on_date, table)
    if side == "buy" and price >= limit_up:
        return Decision(False, f"Risk: LimitUp blocks BUY for {code}: price {price:.2f} >= limit_up {limit_up:.2f}",
                        b, pct, limit_up, limit_down)
    if side == "sell" and price <= limit_down:
        return Decision(False, f"Risk: LimitDown blocks SELL for {code}: price {price:.2f} <= limit_down {limit_down:.2f}",
                        b, pct, limit_up, limit_down)
    return Decision(True, "ok", b, pct, limit_up, limit_down)
