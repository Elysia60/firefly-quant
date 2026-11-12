"""doctor 自检(csqaq 纪律:「可靠」的定义是不需要人记得;自检主动发现降级)。

七项检查,全部给出 PASS/WARN/FAIL + 可读 detail;FAIL 只来自"会造成错误结论"的问题,
缺数据(未积累)一律 WARN 不 FAIL——诚实报告,不虚报也不吞警报。
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .calendar import cache_to_json, load_calendar_cache, read_cnequity_calendar
from .config import ensure_dir, resolve_path
from .limits import price_limits


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_paths(cfg: dict) -> dict:
    try:
        for key in ("paths.data_dir", "paths.lake_raw", "paths.lake_norm", "paths.state_dir"):
            ensure_dir(resolve_path(cfg, key))
        return {"name": "paths", "status": "PASS", "detail": "数据目录可解析可创建"}
    except Exception as e:  # noqa: BLE001
        return {"name": "paths", "status": "FAIL", "detail": f"{type(e).__name__}: {e}"}


def check_cnequity_lake(cfg: dict) -> dict:
    lake = resolve_path(cfg, "paths.cnequity_lake")
    if not lake.exists():
        return {"name": "cnequity_lake", "status": "WARN",
                "detail": f"湖不存在({lake});回填与日历主源不可用,可走新浪/akshare 兜底"}
    parts = list(lake.glob("curated/trading_calendar/trade_date=*/part-merged.parquet"))
    if not parts:
        return {"name": "cnequity_lake", "status": "WARN", "detail": f"湖存在但无 trading_calendar 分区: {lake}"}
    return {"name": "cnequity_lake", "status": "PASS", "detail": f"湖可达,{len(parts)} 个日历分区"}


def check_calendar(cfg: dict) -> dict:
    """日历可达性 + 新鲜度;湖可用时顺手刷新缓存(离线兜底)。"""
    cache_path = resolve_path(cfg, "collect.calendar_cache")
    days, source = None, None
    try:
        days = read_cnequity_calendar(resolve_path(cfg, "paths.cnequity_lake"))
        source = "cnequity_lake"
        cache_to_json(days, cache_path)
    except Exception:  # noqa: BLE001 — 湖不可达走缓存,是设计内降级
        days = load_calendar_cache(cache_path)
        source = "cache" if days else None
    if not days:
        return {"name": "calendar", "status": "FAIL",
                "detail": "无任何日历来源(湖不可达且无缓存)——回测与判卷窗口都会错,禁止继续"}
    today = date.today()
    covered = max(days)
    if covered >= today:
        return {"name": "calendar", "status": "PASS",
                "detail": f"来源={source} {days[0]}~{covered} 覆盖今日({len(days)} 交易日)"}
    return {"name": "calendar", "status": "WARN",
            "detail": f"来源={source} 只覆盖到 {covered},今日({today})缺位——今日无法判卷/回测"}


def check_cooldown(cfg: dict) -> dict:
    path = resolve_path(cfg, "collect.cooldown_file")
    if not path.exists():
        return {"name": "rate_limit", "status": "PASS", "detail": "无冷却状态"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        blocked = raw.get("blocked_until")
    except (json.JSONDecodeError, OSError):
        return {"name": "rate_limit", "status": "WARN", "detail": "冷却状态文件损坏(按无冷却处理)"}
    if blocked is None or time.time() >= blocked:
        return {"name": "rate_limit", "status": "PASS", "detail": "冷却已解除"}
    until = datetime.fromtimestamp(blocked).isoformat(timespec="seconds")
    return {"name": "rate_limit", "status": "WARN", "detail": f"限流冷却中,直至 {until}——期间采集层会直接拒绝"}


def check_lake_integrity(cfg: dict, conn) -> dict:
    if conn is None:
        return {"name": "lake_integrity", "status": "WARN", "detail": "无账本连接,跳过"}
    try:
        rows = conn.execute(
            "SELECT task_key, file_path FROM collect_manifest WHERE file_path IS NOT NULL").fetchall()
    except Exception as e:  # noqa: BLE001
        return {"name": "lake_integrity", "status": "WARN", "detail": f"账本不可读: {e}"}
    if not rows:
        return {"name": "lake_integrity", "status": "WARN", "detail": "账本为空(尚无采集)"}
    missing = [k for k, fp in rows if not Path(fp).exists()]
    if missing:
        return {"name": "lake_integrity", "status": "FAIL",
                "detail": f"账本 {len(rows)} 项中 {len(missing)} 项文件缺失: {missing[:5]}"}
    return {"name": "lake_integrity", "status": "PASS", "detail": f"账本 {len(rows)} 项,文件齐全"}


def check_limits_sample(cfg: dict) -> dict:
    """用最近一天快照里的真实涨停板股回验 limits.py(无数据则 WARN 不 FAIL)。"""
    norm_dir = resolve_path(cfg, "paths.lake_norm") / "daily_snapshot"
    dts = sorted(norm_dir.glob("dt=*"))
    if not dts:
        return {"name": "limits_sample", "status": "WARN", "detail": "快照未积累,涨跌停层无实盘样本可回验"}
    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.read_parquet(sorted(dts[-1].glob("*.parquet"))[0])
    except Exception as e:  # noqa: BLE001
        return {"name": "limits_sample", "status": "WARN", "detail": f"快照不可读: {e}"}
    if "prev_close" not in df.columns or df.empty:
        return {"name": "limits_sample", "status": "WARN", "detail": "快照缺 prev_close 列,跳过回验"}
    cand = df[(df["prev_close"] > 0) & (df["close"] > 0)].copy()
    cand = cand[cand["close"] >= cand["prev_close"] * 1.09]
    if cand.empty:
        return {"name": "limits_sample", "status": "PASS", "detail": "最近快照无涨停板股(正常行情),规则层待样本"}
    matched = 0
    for _, row in cand.head(20).iterrows():
        on = date.fromisoformat(str(row["date"])) if row.get("date") else None
        up, _dn = price_limits(float(row["prev_close"]), str(row["code"]),
                               name=str(row.get("name") or ""), on_date=on)
        matched += 1 if abs(up - float(row["close"])) < 0.005 else 0
    total = min(20, len(cand))
    if matched == total:
        return {"name": "limits_sample", "status": "PASS", "detail": f"抽样 {total} 只涨停股,close==涨停价 全部吻合"}
    return {"name": "limits_sample", "status": "WARN",
            "detail": f"抽样 {total} 只涨停股仅 {matched} 只吻合——检查名称/板块幅度口径(局限 L5)"}


def check_deps() -> dict:
    detail, missing = [], []
    for mod in ("pandas", "pyarrow", "akshare"):
        try:
            detail.append(f"{mod}={getattr(importlib.import_module(mod), '__version__', '?')}")
        except Exception:  # noqa: BLE001
            missing.append(mod)
    try:
        importlib.import_module("akquant")
        detail.append("akquant=ok")
    except Exception:  # noqa: BLE001
        detail.append("akquant=缺失(回测冒烟需 WorkBuddy venv)")
    if missing:
        return {"name": "deps", "status": "WARN", "detail": "缺少: " + ",".join(missing) + "; " + "; ".join(detail)}
    return {"name": "deps", "status": "PASS", "detail": "; ".join(detail)}


def run_doctor(cfg: dict, conn=None) -> dict:
    checks = [
        check_paths(cfg),
        check_cnequity_lake(cfg),
        check_calendar(cfg),
        check_cooldown(cfg),
        check_lake_integrity(cfg, conn),
        check_limits_sample(cfg),
        check_deps(),
    ]
    overall = "PASS" if all(c["status"] != "FAIL" for c in checks) else "FAIL"
    report = {"overall": overall, "generated_at": _now_iso(), "checks": checks}
    state_dir = ensure_dir(resolve_path(cfg, "paths.state_dir"))
    (state_dir / "doctor_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def print_report(report: dict) -> None:
    icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    print(f"doctor overall = {report['overall']}")
    for c in report["checks"]:
        print(f"  {icon[c['status']]} {c['name']:<16} {c['detail']}")
