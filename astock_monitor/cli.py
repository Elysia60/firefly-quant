"""CLI 入口:doctor / calendar-check / collect-daily / fetch-hist / backfill / limits-check。

Windows GBK 教训(csqaq #3):强制 stdout UTF-8;bat 里同时设 PYTHONUTF8=1。
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date

from .config import load_config, resolve_path
from .store import get_conn, init_db


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _db(cfg: dict):
    conn = get_conn(resolve_path(cfg, "paths.db"))
    init_db(conn)
    return conn


def _build_signal_maps(cfg: dict) -> tuple[dict | None, dict]:
    """信号上下文 maps(与 forecast-replay 同源,单一实现)。

    breadth_map = 湖 normalized/breadth_history(上涨家数占比);
    sentiment_map = 两融贪婪度 ×100(csqaq v1.0 锚点契约)。
    2026-11-17 修复两处:
      ① signal 路径此前未接 maps,momentum/sentiment 腿静默缺失;
      ② load_margin_greed 自 P3"量纲统一"起返回 0-1(服务 triggers 的 T-杠杆>0.9),
         但 SENTIMENT_ANCHORS 是 0-100 → 0-1 全值域落在第一锚点段,
         sentiment 腿被钉死 ~100(零区分度)。此处 ×100 恢复信号刻度,
         triggers 的 0-1 契约不受影响。
    """
    breadth_map = None
    bh = resolve_path(cfg, "paths.lake_norm") / "breadth_history" / "part.parquet"
    if bh.exists():
        import pandas as pd  # noqa: PLC0415
        bdf = pd.read_parquet(bh)
        breadth_map = {d: float(v) for d, v in
                       zip(pd.to_datetime(bdf["date"]).dt.date, bdf["up_ratio"])}
    from .sentiment import load_margin_greed
    greed_map = load_margin_greed(resolve_path(cfg, "paths.lake_raw"))
    greed_map = {d: v * 100.0 for d, v in greed_map.items()}
    return breadth_map, greed_map


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(prog="astock_monitor", description="萤火计划 A 股量化监控系统")
    parser.add_argument("--config", default=None, help="config.json 路径(默认仓库根)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="七项自检")
    sub.add_parser("calendar-check", help="日历:湖读取+新浪对拍+新鲜度(联网对拍)")

    p_daily = sub.add_parser("collect-daily", help="日更:按日期全市场快照(1 请求)")
    p_daily.add_argument("--date", default=None, help="YYYY-MM-DD,默认今天")

    p_hist = sub.add_parser("fetch-hist", help="按股历史(东财 hfq;仅交叉验证/小补丁)")
    p_hist.add_argument("--code", required=True)
    p_hist.add_argument("--start", required=True)
    p_hist.add_argument("--end", required=True)
    p_hist.add_argument("--adjust", default="hfq", choices=["", "qfq", "hfq"])

    p_sina = sub.add_parser("fetch-hist-sina", help="退市股回退(新浪源)")
    p_sina.add_argument("--code", required=True)

    p_bf = sub.add_parser("backfill", help="历史回填(CNEquity TDX 主源)")
    p_bf.add_argument("--codes", default="", help="逗号分隔代码;空则需 --codes-file")
    p_bf.add_argument("--codes-file", default="", help="每行一个代码的文本文件")
    p_bf.add_argument("--start", required=True)
    p_bf.add_argument("--end", required=True)
    p_bf.add_argument("--try-run", action="store_true", help="尝试在本机执行 cne(沙箱内会被拦)")

    p_lim = sub.add_parser("limits-check", help="涨跌停校验层单点验证")
    p_lim.add_argument("--code", required=True)
    p_lim.add_argument("--prev-close", type=float, required=True)
    p_lim.add_argument("--price", type=float, required=True)
    p_lim.add_argument("--side", choices=["buy", "sell"], required=True)
    p_lim.add_argument("--name", default="")
    p_lim.add_argument("--date", default=None)

    p_v = sub.add_parser("verify-poc4", help="复跑 PoC-4 接口对齐(需 akquant)")
    p_v.add_argument("--python", default=sys.executable, help="用于执行的 python(默认当前)")

    p_fin = sub.add_parser("collect-financials", help="盈利数据:业绩报表全市场一张表(1请求/报告期,PIT披露时滞消费侧过滤)")
    p_fin.add_argument("--period", required=True, help="报告期 YYYYMMDD,如 20260930")
    p_sent = sub.add_parser("collect-sentiment", help="情绪数据:涨停池(每日必采,仅留~3周)+两融全量回补")
    p_sent.add_argument("--date", default=None, help="YYYY-MM-DD,默认今天")

    sub.add_parser("triggers", help="2027 watch 触发面板(跨越才推送,不 front-run)")
    p_pi = sub.add_parser("paper-init", help="初始化纸面账户(默认现金 100 万;熔断的净值来源)")
    p_pi.add_argument("--cash", type=float, default=1_000_000.0)
    p_pm = sub.add_parser("paper-mark", help="纸面账户每日估值(读湖快照收盘价)+ 熔断评估")
    p_pm.add_argument("--date", default=None, help="YYYY-MM-DD,缺省今天")
    p_pm.add_argument("--targets", default=None, help="可选:目标权重 JSON,先调仓再估值")
    p_pr = sub.add_parser("paper-rebalance", help="纸面账户按目标权重调仓(手数向下取整,卖前买后)")
    p_pr.add_argument("--targets", required=True, help="目标权重 JSON {code: weight}")
    p_pr.add_argument("--date", default=None)
    p_pm2 = sub.add_parser("paper-status", help="查看纸面账户与熔断状态")
    p_cb = sub.add_parser("circuit-check", help="回撤熔断 P6:评估持仓/组合回撤(只降不升,fail-closed;DSR 中性)")
    p_cb.add_argument("--positions", required=True, help="持仓 JSON {symbol:{entry_price,current_price,weight}}")
    p_cb.add_argument("--portfolio-dd", type=float, required=True, help="组合回撤(负数,如 -0.18)")
    p_cb.add_argument("--limit-down", default="", help="今日跌停卖不出的 symbol(逗号分隔)")
    p_cb.add_argument("--push", action="store_true", help="清仓档位推送主动消息")
    p_cbr = sub.add_parser("circuit-reset", help="人工过审复位(仅 cleared 状态有效;半自动纪律)")
    p_cbr.add_argument("--approved-by", required=True, help="谁批的(必填,入审计)")
    p_cbr.add_argument("--reason", default="", help="复位理由")

    p_aud = sub.add_parser("audit-signal", help="结论审计:NW t + bootstrap CI + 事件研究对照(随机化推断)")
    p_aud.add_argument("--verdict", default="avoid_watch", choices=["avoid_watch", "buy_watch", "neutral"])
    p_aud.add_argument("--window", type=int, default=5, choices=[5, 20])
    p_aud.add_argument("--index", default="000300.SH")
    p_aud.add_argument("--seed", type=int, default=42)

    p_sig = sub.add_parser("signal", help="生成指数信号(防泄漏:只用截至昨日)")
    p_sig.add_argument("--date", default=None, help="信号日 YYYY-MM-DD,默认今天")
    p_sig.add_argument("--index", default="000300.SH", help="指数符号,默认沪深300")
    p_sig.add_argument("--require-session", action="store_true",
                       help="自动化守卫:信号日非交易日则跳过(防周末信号污染 forecast_log)")
    p_db = sub.add_parser("decision-brief", help="每日决策简报(融合 signal/判卷/账户/熔断;非投资建议)")
    p_db.add_argument("--date", default=None, help="简报日 YYYY-MM-DD,默认今天")

    sub.add_parser("forecast-judge", help="判卷到期信号(T+5/T+20,真实数据,不提前猜)")

    p_rp = sub.add_parser("forecast-replay", help="历史回放:生成+判卷+汇总(同一条流水线)")
    p_rp.add_argument("--start", required=True)
    p_rp.add_argument("--end", required=True)
    p_rp.add_argument("--index", default="000300.SH")

    p_sum = sub.add_parser("forecast-summary", help="对账记分牌汇总")
    p_sum.add_argument("--out", default=None,
                       help="同时把汇总 JSON 落到该路径(自动化快照用)")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "doctor":
        from .doctor import print_report, run_doctor
        conn = _db(cfg)
        try:
            print_report(run_doctor(cfg, conn))
        finally:
            conn.close()
        return 0

    if args.cmd == "calendar-check":
        from . import calendar as cal
        days = cal.read_cnequity_calendar(resolve_path(cfg, "paths.cnequity_lake"))
        print(f"CNEquity 湖: {len(days)} 交易日 {days[0]}~{days[-1]}")
        sina = cal.fetch_sina_calendar()
        report = cal.crosscheck(days, sina)
        print(f"新浪对拍({report['status']}): {report.get('count_a')} vs {report.get('count_b')} "
              f"identical={report['identical']}")
        cache = cal.cache_to_json(days, resolve_path(cfg, "collect.calendar_cache"))
        print(f"缓存已刷新: {cache}")
        return 0 if report["identical"] else 1

    if args.cmd == "collect-daily":
        from .collect import collect_daily
        conn = _db(cfg)
        try:
            r = collect_daily(cfg, conn, day=date.fromisoformat(args.date) if args.date else None)
        finally:
            conn.close()
        print(r)
        return 0 if r["status"] in ("ok", "skipped") else 1

    if args.cmd == "fetch-hist":
        from .collect import fetch_hist
        conn = _db(cfg)
        try:
            r = fetch_hist(cfg, conn, args.code, args.start, args.end, adjust=args.adjust)
        finally:
            conn.close()
        print(r)
        return 0

    if args.cmd == "fetch-hist-sina":
        from .collect import fetch_hist_sina
        conn = _db(cfg)
        try:
            r = fetch_hist_sina(cfg, conn, args.code)
        finally:
            conn.close()
        print(r)
        return 0

    if args.cmd == "backfill":
        from .collect import backfill_cnequity
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        if args.codes_file:
            codes = [ln.strip() for ln in open(args.codes_file, encoding="utf-8") if ln.strip()]
        if not codes:
            print("必须给 --codes 或 --codes-file", file=sys.stderr)
            return 2
        r = backfill_cnequity(cfg, codes, args.start, args.end, try_run=args.try_run)
        print(r)
        return 0 if r["status"] in ("prepared", "ok") else 1

    if args.cmd == "limits-check":
        from datetime import date as _date
        from .limits import check_order
        d = check_order(args.side, args.price, args.prev_close, args.code,
                        name=args.name, on_date=_date.fromisoformat(args.date) if args.date else None)
        print(f"allowed={d.allowed} board={d.board} pct={d.pct:.2%} "
              f"limit_up={d.limit_up:.2f} limit_down={d.limit_down:.2f}")
        print(d.reason)
        return 0 if d.allowed else 1

    if args.cmd in ("signal", "forecast-judge", "forecast-replay", "forecast-summary",
                    "decision-brief"):
        from . import calendar as astock_cal
        from . import forecast as F
        from .signals import generate_signal, load_index_closes

        conn = _db(cfg)
        try:
            F.init_db(conn)
            lake = resolve_path(cfg, "paths.cnequity_lake")
            if args.cmd == "signal":
                rows = load_index_closes(lake, args.index)
                day = date.fromisoformat(args.date) if args.date else date.today()
                if getattr(args, "require_session", False):
                    session_days = astock_cal.load_calendar_cache(
                        resolve_path(cfg, "collect.calendar_cache"))
                    if session_days is None:
                        session_days = astock_cal.read_cnequity_calendar(lake)
                    if not astock_cal.is_session_day(day, session_days):
                        import json as _json
                        print(_json.dumps({"skipped": True, "date": day.isoformat(),
                                           "reason": "非交易日(守卫拒绝,不落 forecast_log)"},
                                          ensure_ascii=False))
                        return 0
                breadth_map, greed_map = _build_signal_maps(cfg)
                sig = generate_signal(rows, day, breadth_map=breadth_map,
                                      sentiment_map=greed_map)
                n = F.record_signal(conn, sig)
                import json as _json
                print(_json.dumps(sig.as_dict(), ensure_ascii=False, indent=2))
                print(f"落盘 {n} 行(forecast_log)")
                return 0
            if args.cmd == "decision-brief":
                import json as _json
                from datetime import date as _date
                from pathlib import Path as _Path
                from . import paper_account as PA
                from .decision_brief import (build_brief, judge_accuracy,
                                             latest_signal_row, render)
                acct = PA.load_account(resolve_path(cfg, "paper_account.account_file"))
                eq_f = resolve_path(cfg, "paper_account.equity_file")
                eq_curve = []
                if eq_f.exists():
                    eq_curve = [_json.loads(l) for l in
                                eq_f.read_text(encoding="utf-8").splitlines() if l.strip()]
                cb_state_f = resolve_path(cfg, "circuit_breaker.state_file")
                breaker = (_json.loads(cb_state_f.read_text(encoding="utf-8"))
                           if cb_state_f.exists() else {})
                day = getattr(args, "date", None) or _date.today().isoformat()
                brief = build_brief(latest_signal_row(conn), judge_accuracy(conn),
                                    acct, breaker, eq_curve, day)
                md = render(brief)
                out_dir = _Path(resolve_path(cfg, "paths.results_dir")) / "decision_brief"
                out_dir.mkdir(parents=True, exist_ok=True)
                out = out_dir / f"{brief['day']}.md"
                out.write_text(md, encoding="utf-8")
                print(md)
                print(f"落盘 {out}")
                return 0
            if args.cmd == "forecast-summary":
                import json as _json
                cost = float(cfg["backtest"].get("cost_round_trip", 0.002))
                summ = F.summarize(conn, cost_rt=cost)
                # P6 记分牌两列: 因子 vs 特异 %var + 逐因子收益贡献(堵风格暴露冒充 alpha)
                try:
                    from .riskfactors import factor_attribution
                    judged = conn.execute(
                        "SELECT DISTINCT verdict, signal_date FROM forecast_log WHERE judged=1"
                    ).fetchall()
                    days_by_verdict: dict = {}
                    for verdict, sd in judged:
                        days_by_verdict.setdefault(verdict, []).append(date.fromisoformat(sd))
                    if days_by_verdict:
                        import pandas as pd  # noqa: PLC0415
                        lake = resolve_path(cfg, "paths.cnequity_lake")
                        parts = sorted((lake / "curated" / "daily_bars").glob("trade_date=*/*.parquet"))
                        if parts:
                            # 30 个月度分区 ≈ 2.5 年: 覆盖 252 日因子回看窗口 + 21 日 RSTR 滞后
                            bars = pd.concat(
                                (pd.read_parquet(f, columns=["symbol", "trade_date", "close", "amount"])
                                 for f in parts[-30:]), ignore_index=True)
                            bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
                            idx_rows = load_index_closes(lake, getattr(args, "index", "000300.SH"))
                            idx_ret = {d: rows[i + 1][1] / rows[i][1] - 1.0
                                       for i, (d, _c) in enumerate(rows[:-1])} if (rows := idx_rows) else {}
                            all_days = sorted({d for ds in days_by_verdict.values() for d in ds})
                            att_all = factor_attribution(bars, idx_ret, all_days)
                            summ["factor_attribution"] = {
                                "overall": att_all,
                                "by_verdict_days": {v: len(ds) for v, ds in days_by_verdict.items()},
                            }
                        else:
                            summ["factor_attribution"] = {"status": "no_lake_data"}
                    else:
                        summ["factor_attribution"] = {"status": "no_judged_signals"}
                except Exception as e:  # noqa: BLE001
                    summ["factor_attribution"] = {"status": "unavailable",
                                                  "detail": f"{type(e).__name__}: {e}"}
                summary = _json.dumps(summ, ensure_ascii=False, indent=2)
                print(summary)
                if getattr(args, "out", None):
                    from pathlib import Path as _Path
                    out_p = _Path(args.out)
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_text(summary + "\n", encoding="utf-8")
                    print(f"落盘 {out_p}")
                return 0
            index = getattr(args, "index", "000300.SH")
            rows = load_index_closes(lake, index)
            closes = dict(rows)
            days = astock_cal.load_calendar_cache(resolve_path(cfg, "collect.calendar_cache"))
            if days is None:
                days = astock_cal.read_cnequity_calendar(lake)
            if args.cmd == "forecast-judge":
                n = F.judge_due(conn, closes, days)
                print(f"本次判卷 {n} 条")
                return 0
            if args.cmd == "forecast-replay":
                breadth_map, greed_map = _build_signal_maps(cfg)
                r = F.replay(conn, rows, days,
                             date.fromisoformat(args.start), date.fromisoformat(args.end),
                             breadth_map=breadth_map, sentiment_map=greed_map)
            else:  # forecast-summary
                r = F.summarize(conn)
            import json as _json
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return 0
        finally:
            conn.close()

    if args.cmd == "collect-financials":
        from .financials import collect_yjbb
        conn = _db(cfg)
        try:
            r = collect_yjbb(cfg, conn, args.period)
        finally:
            conn.close()
        print(r)
        return 0 if r["status"] in ("ok", "skipped") else 1

    if args.cmd == "collect-sentiment":
        from .sentiment import backfill_margin, collect_zt_pool
        conn = _db(cfg)
        try:
            from .sentiment import collect_erp
            day = date.fromisoformat(args.date) if args.date else None
            r1 = collect_zt_pool(cfg, conn, day=day)
            r2 = backfill_margin(cfg, conn)
            r3 = collect_erp(cfg, conn)
        finally:
            conn.close()
        print({"zt_pool": r1, "margin": r2, "erp": r3})
        return 0

    if args.cmd == "audit-signal":
        import json as _json
        from . import calendar as astock_cal
        from .audit import bootstrap_mean_ci, event_study, newey_west_t
        from .calendar import add_trading_days
        from .signals import load_index_closes

        conn = _db(cfg)
        try:
            rows = conn.execute(
                "SELECT signal_date, fwd_ret FROM forecast_log"
                " WHERE verdict=? AND window_days=? AND judged=1",
                (args.verdict, args.window)).fetchall()
        finally:
            conn.close()
        if not rows:
            print("无已判卷样本")
            return 1
        lake = resolve_path(cfg, "paths.cnequity_lake")
        idx_rows = load_index_closes(lake, args.index)
        closes = dict(idx_rows)
        days = astock_cal.load_calendar_cache(resolve_path(cfg, "collect.calendar_cache"))
        if days is None:
            days = astock_cal.read_cnequity_calendar(lake)
        # 全历史 T+n 前向收益(事件研究的对照池需要非信号日样本)
        fwd_map = {}
        for d in days:
            if d not in closes:
                continue
            try:
                tgt = add_trading_days(d, args.window, days)
            except ValueError:
                continue
            if tgt in closes:
                fwd_map[d] = closes[tgt] / closes[d] - 1.0
        series = [r[1] for r in rows]
        sig_days = {date.fromisoformat(r[0]) for r in rows}
        nw = newey_west_t(series, window=args.window)
        lo, hi = bootstrap_mean_ci(series, avg_block=args.window, B=1000, seed=args.seed)
        es = event_study(sig_days, fwd_map, days, K=5, min_gap=args.window + 1, seed=args.seed)
        print(_json.dumps({
            "verdict": args.verdict, "window": args.window, "n": len(series),
            "mean_fwd": sum(series) / len(series),
            "nw_t": round(nw, 3) if math.isfinite(nw) else ("+inf" if nw > 0 else "-inf"),
            "boot_ci": [round(lo, 5), round(hi, 5)],
            "event_study": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in es.items()},
        }, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "triggers":
        import json as _json
        from . import triggers as TR
        from .config import resolve_path as _rp
        metrics_pack = TR.load_metric_series(cfg)
        latest = {}
        for name in ("erp_pct", "breadth", "greed", "vol_pct"):
            ser = metrics_pack[name]
            if ser:
                latest[name] = ser[max(ser)]
        idx_rows = metrics_pack["index_rows"]
        reg = metrics_pack["regime"]
        d_last = max(reg)
        latest["regime"] = reg[d_last]["regime"]
        state_f = _rp(cfg, "triggers.state_file")
        prev = {}
        if state_f.exists():
            try:
                prev = _json.loads(state_f.read_text(encoding="utf-8"))
            except ValueError:
                prev = {}
        result = TR.eval_triggers(latest, prev, cfg.get("triggers", {}))
        state_f.write_text(_json.dumps(
            {k: {"fired": v["fired"], "since": v["since"]} for k, v in result.items()},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(_json.dumps({"as_of": str(d_last), "triggers": result},
                          ensure_ascii=False, indent=2))
        new_fires = [k for k, v in result.items() if v["changed"]]
        if new_fires:
            now_s = date.today().isoformat()
            lines = [f"[{now_s}] 2027 watch 触发(跨越): " + "、".join(new_fires)]
            for k in new_fires:
                lines.append(f"  {k}: 当前值 {result[k]['value']}")
            lines.append("纪律:触发只记录并进入样本外审判流程,不构成交易指令(不 front-run)。")
            # 推送出口:主动消息目录(与看门狗同通道;路径常量放在模块级,避免内联转义)
            from .notify_proactive import push_lines
            pf = push_lines(lines)
            print(f"已推送触发告警: {pf} ({len(new_fires)} 项新跨越)")
        return 0

    if args.cmd in ("paper-init", "paper-mark", "paper-rebalance", "paper-status"):
        import json as _json
        from datetime import date as _date
        from pathlib import Path as _Path
        from . import circuit_breaker as CB
        from . import paper_account as PA

        acct_f = resolve_path(cfg, "paper_account.account_file")
        eq_f = resolve_path(cfg, "paper_account.equity_file")
        cb_state_f = resolve_path(cfg, "circuit_breaker.state_file")
        cb_events_f = resolve_path(cfg, "circuit_breaker.events_file")
        day = getattr(args, "date", None) or _date.today().isoformat()

        if args.cmd == "paper-init":
            if acct_f.exists():
                print(_json.dumps({"status": "exists", "path": str(acct_f)}, ensure_ascii=False))
                return 0
            PA.save_account(acct_f, PA.init_account(args.cash, day))
            print(_json.dumps({"status": "ok", "cash": args.cash, "path": str(acct_f)},
                              ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "paper-status":
            acct = PA.load_account(acct_f)
            cb = CB.load_state(cb_state_f)
            print(_json.dumps({"account": acct, "circuit": cb}, ensure_ascii=False, indent=2))
            return 0

        acct = PA.load_account(acct_f)
        if acct is None:
            print(_json.dumps({"status": "no_account",
                               "note": "先跑 paper-init;本次跳过(不阻塞日更)"},
                              ensure_ascii=False))
            return 0

        # 价格:湖 normalized/daily_snapshot
        import pandas as _pd
        from .store import read_parquet as _rp
        snap = resolve_path(cfg, "paths.lake_norm") / "daily_snapshot" / f"dt={day.replace('-', '')}" / "part.parquet"
        if not snap.exists():
            print(_json.dumps({"status": "data_missing", "day": day,
                               "note": "当日快照不存在(未采集/非交易日)→ fail-closed 不估值",
                               "snap": str(snap)}, ensure_ascii=False))
            return 0
        df = _rp(snap)
        prices = {str(r["code"]): float(r["close"]) for _, r in df.iterrows()
                  if r.get("close") == r.get("close")}
        if args.cmd == "paper-rebalance" or getattr(args, "targets", None):
            tf = _Path(args.targets)
            targets = _json.loads(tf.read_text(encoding="utf-8-sig"))
            trades = PA.rebalance(acct, targets, prices, day)
            PA.save_account(acct_f, acct)
        else:
            trades = []
        summary = PA.mark_to_market(acct, prices, day)
        if summary["status"] == "ok":
            PA.save_account(acct_f, acct)
            PA.append_equity(eq_f, {"day": day, "equity": summary["equity"],
                                    "drawdown": summary["drawdown"],
                                    "high_water": summary["high_water"]})
            rep = CB.evaluate(summary["circuit_input"]["positions"],
                              summary["circuit_input"]["portfolio_drawdown"],
                              state=CB.load_state(cb_state_f))
            CB.save_state(cb_state_f, rep["state"])
            CB.append_event(cb_events_f, {"event": "eval", "source": "paper-mark",
                                          "day": day, "mode": rep["mode"],
                                          "portfolio_dd": rep["portfolio_drawdown"]})
            if rep["mode"] == CB.MODE_CLEARED and rep["prev_mode"] != CB.MODE_CLEARED:
                from .notify_proactive import push_lines
                push_lines([f"[{day}] 回撤熔断清仓:纸面组合回撤 {rep['portfolio_drawdown']:.1%} ≤ -25%;"
                            f"冷却中,重启需人工过审(circuit-reset --approved-by)"])
            summary["circuit"] = {"mode": rep["mode"], "actions": rep["actions"],
                                  "requires_manual_reset": rep["requires_manual_reset"]}
        print(_json.dumps({"status": summary["status"], "day": day,
                           "trades": trades, **{k: v for k, v in summary.items()
                                                if k != "circuit_input"}},
                          ensure_ascii=False, indent=2, default=str))
        return 0

    if args.cmd in ("circuit-check", "circuit-reset"):
        import json as _json
        from pathlib import Path as _Path
        from . import circuit_breaker as CB
        state_f = resolve_path(cfg, "circuit_breaker.state_file")
        events_f = resolve_path(cfg, "circuit_breaker.events_file")
        if args.cmd == "circuit-reset":
            st = CB.load_state(state_f)
            new = CB.reset(st, approved_by=args.approved_by, reason=args.reason)
            CB.save_state(state_f, new)
            CB.append_event(events_f, {"event": "manual_reset", "by": args.approved_by,
                                       "reason": args.reason, "mode": new.get("mode")})
            print(_json.dumps(new, ensure_ascii=False, indent=2))
            return 0
        positions = _json.loads(_Path(args.positions).read_text(encoding="utf-8-sig"))
        ld = tuple(s.strip() for s in args.limit_down.split(",") if s.strip())
        rep = CB.evaluate(positions, args.portfolio_dd,
                          state=CB.load_state(state_f), limit_down=ld)
        CB.save_state(state_f, rep["state"])
        CB.append_event(events_f, {"event": "eval", "mode": rep["mode"],
                                   "portfolio_dd": rep["portfolio_drawdown"],
                                   "actions": [a["action"] for a in rep["actions"]]})
        print(_json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        if args.push and rep["mode"] == CB.MODE_CLEARED:
            from .notify_proactive import push_lines
            pf = push_lines([f"[{date.today().isoformat()}] 回撤熔断清仓:组合回撤 "
                             f"{rep['portfolio_drawdown']:.1%} ≤ -25%;冷却中,重启需人工过审"])
            print(f"已推送: {pf}")
        return 0

    if args.cmd == "verify-poc4":
        import subprocess
        from pathlib import Path
        script = Path(__file__).resolve().parent.parent / "scripts" / "verify" / "poc4_rerun.py"
        proc = subprocess.run([args.python, str(script)], capture_output=True, text=True)
        print(proc.stdout[-2000:])
        if proc.returncode != 0:
            print(proc.stderr[-1000:], file=sys.stderr)
        return proc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
