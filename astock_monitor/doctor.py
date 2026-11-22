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
    # 2026-11-18 修正候选网:旧网把"大涨未封板"(20cm 板涨 10-16% 不触板)也当涨停样本,
    # 造成 6/20 假 WARN——limits.py 与数据均无错。改为:仅验证**真封板**股
    # (close==计算涨停价/跌停价),N 前缀新股(首日无涨跌幅)剔除,非封板剔除并计数。
    matched, sealed_n, skipped = 0, 0, 0
    for _, row in cand.iterrows():
        name = str(row.get("name") or "")
        if name.startswith("N"):
            skipped += 1
            continue
        on = date.fromisoformat(str(row["date"])) if row.get("date") else None
        up, dn = price_limits(float(row["prev_close"]), str(row["code"]),
                              name=name, on_date=on)
        close = float(row["close"])
        if abs(close - up) < 0.005 or abs(close - dn) < 0.005:
            sealed_n += 1
            matched += 1 if abs(close - up) < 0.005 else 0
        else:
            skipped += 1
        if sealed_n >= 20:
            break
    if sealed_n == 0:
        return {"name": "limits_sample", "status": "PASS",
                "detail": f"快照 {len(cand)} 只涨幅≥9%但均未封板(正常),规则层待封板样本"}
    if matched == sealed_n:
        return {"name": "limits_sample", "status": "PASS",
                "detail": f"抽样 {sealed_n} 只真封板股,close==涨停价 全部吻合(剔除非封板 {skipped} 只)"}
    return {"name": "limits_sample", "status": "WARN",
            "detail": f"真封板 {sealed_n} 只中 {sealed_n - matched} 只 close!=计算涨停价——检查名称/板块幅度口径(局限 L5)"}


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
        detail.append("akquant=缺失(回测冒烟需 本地沙箱 venv)")
    if missing:
        return {"name": "deps", "status": "WARN", "detail": "缺少: " + ",".join(missing) + "; " + "; ".join(detail)}
    return {"name": "deps", "status": "PASS", "detail": "; ".join(detail)}


def check_dq_calendar(cfg: dict) -> dict:
    """DQ-1 日历对账(roadmap 定案: exchange_calendars XSHG 为独立第三方口径)。
    湖日历 vs XSHG 会话表在覆盖窗口内逐日比对;分歧 WARN 不 FAIL(可能是覆盖率伪影)。
    离线计算,零网络。"""
    try:
        import exchange_calendars as xc  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {"name": "dq_calendar", "status": "WARN",
                "detail": "exchange_calendars 未安装——日历对账缺独立第三方源"}
    try:
        import pandas as pd  # noqa: PLC0415
        days = read_cnequity_calendar(resolve_path(cfg, "paths.cnequity_lake"))
    except Exception as e:  # noqa: BLE001
        return {"name": "dq_calendar", "status": "WARN", "detail": f"湖日历不可读,跳过对账: {e}"}
    lo, hi = min(days), max(days)
    try:
        cal = xc.get_calendar("XSHG")
        # 对账窗口裁到双方交集(XSHG 默认 bound 只到今年末,湖可能更长)
        hi_eff = min(pd.Timestamp(hi), pd.Timestamp(cal.last_session))
        sessions = cal.sessions_in_range(pd.Timestamp(lo), hi_eff)
        xshg = {d.date() for d in sessions}
    except Exception as e:  # noqa: BLE001
        return {"name": "dq_calendar", "status": "WARN", "detail": f"XSHG 会话表不可用: {e}"}
    lake_set = set(days)
    lake_set_cmp = {d for d in lake_set if d <= hi_eff.date()}
    only_lake = sorted(lake_set_cmp - xshg)
    only_xshg = sorted(xshg - lake_set_cmp)
    if not only_lake and not only_xshg:
        return {"name": "dq_calendar", "status": "PASS",
                "detail": f"湖日历 {lo}~{hi_eff.date()} 与 XSHG {len(xshg)} 个交易日零分歧"
                          f"(湖总覆盖 {len(lake_set)} 日)"}
    return {"name": "dq_calendar", "status": "WARN",
            "detail": f"日历分歧: 仅湖={len(only_lake)} 仅XSHG={len(only_xshg)}"
                      f" (湖侧样例 {[str(d) for d in only_lake[:3]]}"
                      f" / XSHG侧样例 {[str(d) for d in only_xshg[:3]]})"}


def check_dq_returns(cfg: dict, fetcher=None) -> dict:
    """DQ-2 复权对账(roadmap 定案铁律: **比涨跌幅,不比价格**)。
    抽湖内一只股最近 ~90 个交易日,与新浪不复权 close 的 pct_change 对拍;
    双侧 |pct|<=0.11 的正常日才进比对(对称剔除除权日),容差 1e-3。
    网络失败 WARN 跳过;>1% 的巨差 FAIL(数据污染级别)。fetcher 可注入供零联网测试。"""
    norm_parts = sorted((resolve_path(cfg, "paths.cnequity_lake")
                         / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
    if not norm_parts:
        return {"name": "dq_returns", "status": "WARN", "detail": "湖无 daily_bars,涨跌幅对账无样本"}
    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date", "close"])
                        for f in norm_parts[-3:]), ignore_index=True)
    except Exception as e:  # noqa: BLE001
        return {"name": "dq_returns", "status": "WARN", "detail": f"湖不可读: {e}"}
    if df.empty:
        return {"name": "dq_returns", "status": "WARN", "detail": "湖 daily_bars 为空"}
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date  # 与第二源统一为 date 型
    sym = sorted(df["symbol"].unique())[0]
    sub = df[df["symbol"] == sym].sort_values("trade_date").tail(90)
    code6 = sym.split(".")[0]
    if fetcher is None:
        def fetcher(code6=code6):
            import akshare as ak  # noqa: PLC0415
            from .collect import symbol_sina
            raw = ak.stock_zh_a_daily(symbol=symbol_sina(code6))
            raw["trade_date"] = pd.to_datetime(raw["date"]).dt.date
            return raw[["trade_date", "close"]]
    try:
        ext = fetcher(code6)
    except Exception as e:  # noqa: BLE001
        return {"name": "dq_returns", "status": "WARN",
                "detail": f"第二源({sym})不可达,对账跳过: {type(e).__name__}"}
    lake_pct = sub.set_index("trade_date")["close"].pct_change()
    ext_s = pd.Series(ext["close"].values, index=pd.Index(ext["trade_date"], name="trade_date"),
                      name="close").sort_index()
    ext_pct = ext_s.pct_change()
    joined = pd.DataFrame({"lake": lake_pct, "ext": ext_pct}).dropna()
    normal = joined[(joined["lake"].abs() <= 0.11) & (joined["ext"].abs() <= 0.11)]
    if normal.empty:
        return {"name": "dq_returns", "status": "WARN",
                "detail": f"{sym} 无可比对正常日(样本 {len(joined)} 天全被剔除)"}
    diff = (normal["lake"] - normal["ext"]).abs()
    worst = float(diff.max())
    n_over = int((diff > 1e-3).sum())
    if worst > 0.01:
        return {"name": "dq_returns", "status": "FAIL",
                "detail": f"{sym} {len(normal)} 天涨跌幅对拍出现巨差 max={worst:.4f}——数据污染,禁止出结论"}
    if n_over:
        return {"name": "dq_returns", "status": "WARN",
                "detail": f"{sym} {len(normal)} 天对拍 {n_over} 天超容差 1e-3 (max={worst:.5f})——检查复权口径"}
    return {"name": "dq_returns", "status": "PASS",
            "detail": f"{sym} {len(normal)} 天涨跌幅对拍一致 (max diff={worst:.2e})"}


def check_dq_sanity(cfg: dict) -> dict:
    """DQ-3 Market Data Sanity 清单(roadmap 定案: OHLC 一致性/跳变超限价/非正价格)。
    只查最近 2 个月度分区(控制耗时);违例=数据污染,FAIL。无数据 WARN。"""
    parts = sorted((resolve_path(cfg, "paths.cnequity_lake")
                    / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
    if not parts:
        return {"name": "dq_sanity", "status": "WARN", "detail": "湖无 daily_bars,sanity 无样本"}
    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.concat((pd.read_parquet(f) for f in parts[-2:]), ignore_index=True)
    except Exception as e:  # noqa: BLE001
        return {"name": "dq_sanity", "status": "WARN", "detail": f"湖不可读: {e}"}
    if df.empty:
        return {"name": "dq_sanity", "status": "WARN", "detail": "湖 daily_bars 为空"}
    bad_ohlc = int(((df["high"] < df[["open", "close"]].max(axis=1))
                    | (df["low"] > df[["open", "close"]].min(axis=1))
                    | (df["high"] < df["low"])).sum())
    bad_price = int((df["close"] <= 0).sum())
    df = df.sort_values(["symbol", "trade_date"])
    pct = df.groupby("symbol")["close"].pct_change()
    # 跳变超限价: 全板块涨停上限 30%(北交所)+余量 → 0.35;每 symbol 首日无前收自动 NaN
    bad_jump = int((pct.abs() > 0.35).sum())
    violations = bad_ohlc + bad_price + bad_jump
    if violations:
        return {"name": "dq_sanity", "status": "FAIL",
                "detail": f"最近 {len(parts[-2:])} 分区 {len(df)} 行: OHLC 违例 {bad_ohlc},"
                          f" 非正价格 {bad_price}, 跳变超限 {bad_jump}——数据污染级,禁止出结论"}
    return {"name": "dq_sanity", "status": "PASS",
            "detail": f"最近 {len(parts[-2:])} 分区 {len(df)} 行: OHLC/价格/涨跌幅三清洁"}


def check_bars_freshness(cfg: dict) -> dict:
    """P6+: bars 新鲜度——最近完整日(≥700 只)距今 ≤4 个日历日 PASS;
    >4 天 WARN(collect/回填断链——11-12~11-20 断链 10 天而 doctor 全 PASS 的盲区封堵)。
    治理: candidate/仓位层消费 bars,数据陈旧必须先于结论被看见。"""
    root = resolve_path(cfg, "paths.cnequity_lake") / "curated" / "daily_bars"
    parts = sorted(root.rglob("*.parquet"))  # 分区两层嵌套(月/日),rglob 兜底
    if not parts:
        return {"name": "bars_freshness", "status": "WARN", "detail": "湖无 daily_bars 分区"}
    latest = parts[-1]  # 月级分区(trade_date=YYYY-MM),日粒度在数据列里
    latest_month = latest.parent  # 同月可能有多个 parquet(原 merged+增量回填)——必须全读

    try:
        import pandas as pd  # noqa: PLC0415
        df = pd.concat((pd.read_parquet(f, columns=["symbol", "trade_date"])
                        for f in sorted(latest_month.glob("*.parquet"))), ignore_index=True)
    except Exception as e:  # noqa: BLE001
        return {"name": "bars_freshness", "status": "WARN", "detail": f"最新分区不可读: {e}"}
    if df.empty:
        return {"name": "bars_freshness", "status": "WARN", "detail": "最新月分区为空"}
    td = pd.to_datetime(df["trade_date"])
    day_counts = df.assign(_d=td).groupby("_d")["symbol"].nunique()
    _full = day_counts[day_counts >= 700]
    if _full.empty:
        return {"name": "bars_freshness", "status": "WARN",
                "detail": "本月无 ≥700 只的完整日——采集不完整"}
    last_day = _full.index.max()
    day_s = last_day.strftime("%Y-%m-%d")
    n_rows = int(_full.max())
    age = (date.today() - last_day.date()).days
    if age > 4:
        return {"name": "bars_freshness", "status": "WARN",
                "detail": f"{day_s} 距今 {age} 天——collect/回填断链,候选与仓位按陈旧数据看待"}
    return {"name": "bars_freshness", "status": "PASS",
            "detail": f"{day_s}({n_rows} 只)距今 {age} 天——新鲜"}


def run_doctor(cfg: dict, conn=None, fetcher=None) -> dict:
    checks = [
        check_paths(cfg),
        check_cnequity_lake(cfg),
        check_calendar(cfg),
        check_cooldown(cfg),
        check_lake_integrity(cfg, conn),
        check_limits_sample(cfg),
        check_deps(),
        check_dq_calendar(cfg),
        check_dq_returns(cfg, fetcher=fetcher),
        check_dq_sanity(cfg),
        check_bars_freshness(cfg),
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
