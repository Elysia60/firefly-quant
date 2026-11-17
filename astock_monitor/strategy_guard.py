"""策略守护三态 — 健康/观察/退役(P-REA-3,逆向自 TSP 策略守护机制)。

背景:TSP 每日 K 段复验自动判定策略健康并退役;萤火注册表管"结论",不管"结论
对应策略的持续健康"。本模块把三态判定做成显式函数,供日报风控面引用。

判定规则(预注册,写死,不随结果漂移):
  输入 = 策略的分年收益序列(几何) + 期间收益序列
  稳健分 = 0.6×分年收益中位数 + 0.4×分年收益最差值(TSP 折外稳健分公式,逆向)
  · retired(退役): 稳健分 < 0  或  最近两个自然年连续为负
  · watch(观察):   稳健分 ≥ 0 且 (最近一年为负 或 分年正占比 < 60%)
  · healthy(健康): 其余
边界:分年数 < 2 → 无法判定,返回 "unknown"(不静默造判)。
"""
from __future__ import annotations


def robust_score(yearly_returns: list[float]) -> float:
    """折外稳健分 = 0.6×中位 + 0.4×最差(TSP 公式;中位抗离群,最差防幸存)。"""
    if not yearly_returns:
        return float("nan")
    s = sorted(yearly_returns)
    median = s[len(s) // 2] if len(s) % 2 else (s[len(s)//2 - 1] + s[len(s)//2]) / 2
    return 0.6 * median + 0.4 * s[0]


def judge_strategy(name: str, yearly_returns: dict[int, float]) -> dict:
    """三态判定。yearly_returns = {年份: 收益}。返回判定 dict,可 JSON 序列化。"""
    if len(yearly_returns) < 2:
        return {"strategy": name, "state": "unknown",
                "reason": "分年样本不足(<2),不判定"}
    years = sorted(yearly_returns)
    vals = [yearly_returns[y] for y in years]
    score = robust_score(vals)
    pos_ratio = sum(1 for v in vals if v > 0) / len(vals)
    last = vals[-1]
    prev = vals[-2]
    if score < 0 or (last < 0 and prev < 0):
        state, reason = "retired", f"稳健分 {score:+.1%} <0 或连续两年为负"
    elif score >= 0 and (last < 0 or pos_ratio < 0.6):
        parts = []
        if last < 0:
            parts.append("近一年为负")
        if pos_ratio < 0.6:
            parts.append(f"正占比 {pos_ratio:.0%}")
        state = "watch"
        reason = f"稳健分 {score:+.1%} ≥0 但" + "、".join(parts)
    else:
        state, reason = "healthy", f"稳健分 {score:+.1%},正占比 {pos_ratio:.0%}"
    return {"strategy": name, "state": state, "reason": reason,
            "robust_score": round(score, 4), "years": years,
            "yearly_returns": {str(y): round(yearly_returns[y], 4) for y in years},
            "positive_ratio": round(pos_ratio, 3)}


def judge_from_final_combination(payload: dict, strategies: tuple[str, ...] = ("A", "B", "C", "D")) -> list[dict]:
    """从 results/final_combination.json 直接判四策略。yearly_nav 差分 → 分年收益。"""
    out = []
    strats = payload.get("strategies", {})
    for m in strategies:
        r = strats.get(m)
        if not r:
            continue
        ynav = r.get("yearly_nav", {})
        years = sorted(int(y) for y in ynav)
        if len(years) < 2:
            out.append({"strategy": f"{m}:{r.get('name','')}", "state": "unknown",
                        "reason": "分年样本不足(<2),不判定"})
            continue
        yearly = {}
        prev = 1.0
        for y in years:
            nav = float(ynav[str(y)])
            yearly[y] = nav / prev - 1.0
            prev = nav
        out.append(judge_strategy(f"{m}:{r.get('name','')}", yearly))
    return out
