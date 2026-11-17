"""纸面账户 —— P6 回撤熔断的"净值来源"(自动估值,零人工记账)。

为什么需要:熔断要的是**每日净值与持仓回撤**,不是手工 JSON。本模块维护一个
模拟账户(初始现金 100 万),每日收盘后用湖里的 normalized 快照估值、记净值历史、
算高水位与回撤,再喂给 circuit_breaker.evaluate()。半自动纪律:只产出状态与
动作建议,不自动下单。

设计纪律:
  · 只读湖里已有收盘价,不造数;持仓股当日无价 → fail-closed(data_missing,不猜)
  · 净值历史 append-only JSONL;账户状态原子写
  · A 股一手 100 股;目标权重调仓为被动手数(向下取整),不足一手不动
  · 成本按 config.backtest.cost_round_trip(0.2%)单边折半计提
  · 空仓合法:第一天 equity=现金,回撤 0,熔断 normal
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

INIT_CASH = 1_000_000.0
LOT = 100                       # A 股一手
COST_RT = 0.002                 # 往返成本(与 config 口径一致)
SINGLE_CAP = 0.35               # 与 portfolio.SINGLE_CAP 一致(防单票超限)


def _now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def load_account(path: str | Path) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    data.setdefault("cash", 0.0)
    data.setdefault("positions", {})
    data.setdefault("high_water", None)
    data.setdefault("last_day", None)
    return data


def init_account(cash: float = INIT_CASH, day: str | None = None) -> dict:
    if cash < 0:
        raise ValueError(f"初始现金不能为负,收到 {cash}")
    return {"cash": float(cash), "positions": {}, "high_water": None,
            "last_day": day, "created": _now(), "trades": 0, "fees_paid": 0.0}


def save_account(path: str | Path, acct: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(acct, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def append_equity(path: str | Path, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def holdings_value(acct: dict, prices: dict[str, float]) -> float:
    return sum(int(h["shares"]) * float(prices[code])
               for code, h in acct["positions"].items())


def equity(acct: dict, prices: dict[str, float]) -> float:
    return float(acct["cash"]) + holdings_value(acct, prices)


def missing_prices(acct: dict, prices: dict[str, float]) -> list[str]:
    """持仓里当天没有收盘价的代码(停牌/缺数据 → fail-closed,不猜价)。"""
    return [code for code in acct["positions"] if code not in prices or prices[code] != prices[code]]


def mark_to_market(acct: dict, prices: dict[str, float], day: str) -> dict:
    """按收盘价估值。返回 summary;acct 原地更新(调用方负责 save)。

    summary: {status, day, equity, drawdown, high_water, positions_detail, circuit_input}
      status="ok" | "data_missing"(fail-closed) | "duplicate"(同一天重复估值,幂等跳过)
    """
    if acct.get("last_day") == day:
        return {"status": "duplicate", "day": day, "equity": None,
                "note": "当天已估值,幂等跳过"}
    miss = missing_prices(acct, prices)
    if miss:
        return {"status": "data_missing", "day": day, "equity": None,
                "missing": sorted(miss),
                "note": "持仓股当日无收盘价 → fail-closed:不估值、不记净值、熔断读不到新回撤"}

    eq = equity(acct, prices)
    hw = acct.get("high_water")
    if hw is None or eq > hw:
        hw = eq
    acct["high_water"] = hw
    acct["last_day"] = day
    dd = eq / hw - 1.0 if hw else 0.0

    detail = {}
    for code, h in acct["positions"].items():
        px = float(prices[code])
        val = int(h["shares"]) * px
        detail[code] = {"shares": int(h["shares"]), "cost": round(float(h["cost"]), 4),
                        "price": px, "value": round(val, 2),
                        "drawdown": round(px / float(h["cost"]) - 1.0, 6) if h["cost"] else 0.0,
                        "weight": round(val / eq, 6) if eq else 0.0}
    circuit_input = {
        "positions": {c: {"entry_price": d["cost"], "current_price": d["price"],
                          "weight": d["weight"]} for c, d in detail.items()},
        "portfolio_drawdown": round(dd, 6),
    }
    return {"status": "ok", "day": day, "equity": round(eq, 2),
            "drawdown": round(dd, 6), "high_water": round(hw, 2),
            "positions_detail": detail, "circuit_input": circuit_input}


def rebalance(acct: dict, targets: dict[str, float], prices: dict[str, float],
              day: str, cost_rt: float = COST_RT) -> list[dict]:
    """把持仓调到目标权重(按收盘价,手数向下取整;卖在前买在后)。返回成交清单。

    纪律:单票目标权重 > SINGLE_CAP 直接拒绝(ValueError);目标权重和 >1 拒绝;
    持仓股无价 → 不调仓并抛 ValueError(不猜价);成本单边 = 成交额 × cost_rt/2。
    """
    if not targets:
        return []
    if sum(targets.values()) > 1.0 + 1e-9:
        raise ValueError(f"目标权重和 {sum(targets.values()):.3f} > 1.0")
    bad = [s for s, w in targets.items() if w > SINGLE_CAP + 1e-9]
    if bad:
        raise ValueError(f"单票目标权重超过上限 {SINGLE_CAP}: {bad}")
    no_price = [s for s in targets if s not in prices or prices[s] != prices[s]]
    if no_price:
        raise ValueError(f"目标股当日无价格,拒绝调仓: {sorted(no_price)}")

    eq = equity(acct, prices)
    fee_rate = cost_rt / 2.0
    trades: list[dict] = []
    fee_total = 0.0

    # 1) 卖:降到目标以下(或清仓)的部分
    for code in list(acct["positions"]):
        h = acct["positions"][code]
        px = float(prices[code]) if code in prices else None
        if px is None:
            continue
        cur_val = int(h["shares"]) * px
        tgt_val = targets.get(code, 0.0) * eq
        target_shares = int(tgt_val // (px * LOT)) * LOT if px > 0 else 0
        if int(h["shares"]) > target_shares:
            sell = int(h["shares"]) - target_shares
            notional = sell * px
            fee = notional * fee_rate
            acct["cash"] += notional - fee
            acct["positions"][code]["shares"] = target_shares
            if target_shares == 0:
                del acct["positions"][code]
            trades.append({"code": code, "side": "sell", "shares": sell,
                           "price": px, "notional": round(notional, 2), "fee": round(fee, 2)})
            fee_total += fee
            acct["trades"] = acct.get("trades", 0) + 1

    # 2) 买:补到目标
    for code, weight in targets.items():
        px = float(prices[code])
        target_shares = int((weight * eq) // (px * LOT)) * LOT
        cur = int(acct["positions"].get(code, {}).get("shares", 0))
        if target_shares > cur:
            buy = target_shares - cur
            notional = buy * px
            fee = notional * fee_rate
            if notional + fee > acct["cash"] + 1e-6:
                # 现金不足:按可用现金缩手(向下取整百股)
                affordable = int((acct["cash"] / (px * (1 + fee_rate))) // LOT) * LOT
                buy = min(buy, affordable)
                if buy <= 0:
                    continue
                notional = buy * px
                fee = notional * fee_rate
            acct["cash"] -= notional + fee
            pos = acct["positions"].setdefault(code, {"shares": 0, "cost": 0.0})
            old_shares = int(pos["shares"])
            new_shares = old_shares + buy
            pos["cost"] = (old_shares * float(pos["cost"]) + notional) / new_shares if new_shares else 0.0
            pos["shares"] = new_shares
            trades.append({"code": code, "side": "buy", "shares": buy,
                           "price": px, "notional": round(notional, 2), "fee": round(fee, 2)})
            fee_total += fee
            acct["trades"] = acct.get("trades", 0) + 1

    acct["fees_paid"] = round(float(acct.get("fees_paid", 0.0)) + fee_total, 2)
    acct["last_day"] = day
    return trades
