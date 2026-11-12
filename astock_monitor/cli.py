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

    p_sent = sub.add_parser("collect-sentiment", help="情绪数据:涨停池(每日必采,仅留~3周)+两融全量回补")
    p_sent.add_argument("--date", default=None, help="YYYY-MM-DD,默认今天")

    p_aud = sub.add_parser("audit-signal", help="结论审计:NW t + bootstrap CI + 事件研究对照(随机化推断)")
    p_aud.add_argument("--verdict", default="avoid_watch", choices=["avoid_watch", "buy_watch", "neutral"])
    p_aud.add_argument("--window", type=int, default=5, choices=[5, 20])
    p_aud.add_argument("--index", default="000300.SH")
    p_aud.add_argument("--seed", type=int, default=42)

    p_sig = sub.add_parser("signal", help="生成指数信号(防泄漏:只用截至昨日)")
    p_sig.add_argument("--date", default=None, help="信号日 YYYY-MM-DD,默认今天")
    p_sig.add_argument("--index", default="000300.SH", help="指数符号,默认沪深300")

    sub.add_parser("forecast-judge", help="判卷到期信号(T+5/T+20,真实数据,不提前猜)")

    p_rp = sub.add_parser("forecast-replay", help="历史回放:生成+判卷+汇总(同一条流水线)")
    p_rp.add_argument("--start", required=True)
    p_rp.add_argument("--end", required=True)
    p_rp.add_argument("--index", default="000300.SH")

    sub.add_parser("forecast-summary", help="对账记分牌汇总")

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

    if args.cmd in ("signal", "forecast-judge", "forecast-replay", "forecast-summary"):
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
                sig = generate_signal(rows, day)
                n = F.record_signal(conn, sig)
                import json as _json
                print(_json.dumps(sig.as_dict(), ensure_ascii=False, indent=2))
                print(f"落盘 {n} 行(forecast_log)")
                return 0
            if args.cmd == "forecast-summary":
                import json as _json
                cost = float(cfg["backtest"].get("cost_round_trip", 0.002))
                print(_json.dumps(F.summarize(conn, cost_rt=cost), ensure_ascii=False, indent=2))
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
                breadth_map = None
                bh = resolve_path(cfg, "paths.lake_norm") / "breadth_history" / "part.parquet"
                if bh.exists():
                    import pandas as pd  # noqa: PLC0415
                    bdf = pd.read_parquet(bh)
                    breadth_map = {d: float(v) for d, v in
                                   zip(pd.to_datetime(bdf["date"]).dt.date, bdf["up_ratio"])}
                from .sentiment import load_margin_greed
                greed_map = load_margin_greed(resolve_path(cfg, "paths.lake_raw"))
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

    if args.cmd == "collect-sentiment":
        from .sentiment import backfill_margin, collect_zt_pool
        conn = _db(cfg)
        try:
            day = date.fromisoformat(args.date) if args.date else None
            r1 = collect_zt_pool(cfg, conn, day=day)
            r2 = backfill_margin(cfg, conn)
        finally:
            conn.close()
        print({"zt_pool": r1, "margin": r2})
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
