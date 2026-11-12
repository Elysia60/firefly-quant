"""采集层:PoC-2 四项硬要求 + 按日期快照第一原则(第一原则 = METHODS.md §1)。

1. 限速:全进程单并发,请求间隔 >= min_interval(默认 1s)。
2. 退避:触发东财 Push2RateLimitError → 记冷却截止时间并持久化;冷却期内直接拒绝,
   绝不立即重试(PoC-2:反复触发封禁 40 分钟+)。
3. 回退:退市股走新浪源(000003 已验证);日历走 CNEquity 湖/新浪。
4. 落盘即缓存:每次成功写 Parquet + manifest 账本,幂等重跑不重复请求。

命令级分工:
- collect_daily:日更增量,按日期全市场快照(1 请求/天),顺手产出真实涨跌家数宽度(补 L1)。
- fetch_hist / fetch_hist_sina:按股历史(仅交叉验证与小补丁用,不用于全市场回填)。
- backfill_cnequity:历史回填走 CNEquity TDX(EM 按股回填 5400 只在限流面前不可行)。

网络函数全部接受 fetcher 注入——单测零联网。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

from .config import ensure_dir, resolve_path
from .store import has_task, log_event, record_task, task_key, write_parquet_atomic

# 统一 schema(normalized 层列序;raw 层原样保留上游列名)
BAR_COLUMNS = ["date", "code", "name", "open", "high", "low", "close",
               "prev_close", "volume", "amount", "pct_chg", "turnover"]


# ---------------------------------------------------------------- 限速与退避

class RateLimitTriggered(Exception):
    """冷却期内拒绝请求,或本次请求触发限流(调用方应停止而非重试)。"""


def is_rate_limit_error(e: BaseException) -> bool:
    """识别东财滑窗限流(避免 import akshare 依赖)。

    两个实测口径(2026-11-12):
    - akshare 1.20.37 抛 Push2RateLimitError(类名含 RateLimit);
    - 同一限流在旧版/部分路径表现为 push2 断连(RemoteDisconnected)——新版官方文案
      "服务器断开了连接,通常是短时间内请求过多" 即指此形态,故 push2+断连也算限流。
    """
    name = type(e).__name__
    msg = str(e)
    if "RateLimit" in name or "RateLimit" in msg:
        return True
    low = msg.lower()
    return "push2" in low and ("connection" in low or "remotedisconnected" in low or "断开" in msg)


class RateLimiter:
    """持久化限速器:请求间隔 + 冷却截止时间(进程重启后仍生效)。"""

    def __init__(self, min_interval: float = 1.0, state_path: str | Path | None = None,
                 backoff_initial: float = 300.0, backoff_max: float = 2400.0):
        self.min_interval = float(min_interval)
        self.state_path = Path(state_path) if state_path else None
        self.backoff_initial = float(backoff_initial)
        self.backoff_max = float(backoff_max)
        self._last_call: float | None = None
        self._strikes = 0
        self._blocked_until: float | None = None
        if self.state_path is not None:
            self._load_state()

    # -- 状态持久化(cooldown_file) --

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._blocked_until = raw.get("blocked_until")
        except (json.JSONDecodeError, OSError):
            return  # 状态文件损坏视作无冷却,不静默造数据

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"blocked_until": self._blocked_until}, ensure_ascii=False),
            encoding="utf-8")

    # -- 主流程 --

    def blocked_until(self) -> float | None:
        if self._blocked_until is not None and time.time() >= self._blocked_until:
            self._blocked_until = None  # 冷却结束
            self._strikes = 0
            self._save_state()
        return self._blocked_until

    def wait(self) -> None:
        """维持请求间隔(单调钟;进程内单并发由调用方保证)。"""
        if self._last_call is not None:
            gap = time.monotonic() - self._last_call
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def check_blocked(self) -> None:
        """冷却期内直接拒绝(绝不立即重试)。"""
        until = self.blocked_until()
        if until is not None:
            raise RateLimitTriggered(
                f"限流冷却中,直至 {datetime.fromtimestamp(until).isoformat(timespec='seconds')}")

    def trigger_backoff(self, hint_seconds: float | None = None) -> float:
        """触发限流 → 指数退避;东财错误信息提示首罚约 5 分钟,则取 max(hint, 指数值)。"""
        self._strikes += 1
        backoff = min(self.backoff_initial * (2 ** (self._strikes - 1)), self.backoff_max)
        if hint_seconds:
            backoff = max(backoff, float(hint_seconds))
        self._blocked_until = time.time() + backoff
        self._save_state()
        return self._blocked_until


def guarded_call(limiter: RateLimiter, fn, *args, **kwargs):
    """限速 + 冷却检查 + 限流识别的标准调用包装。"""
    limiter.check_blocked()
    limiter.wait()
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 — 识别后统一转译
        if is_rate_limit_error(e):
            limiter.trigger_backoff()
            raise RateLimitTriggered(f"触发东财限流,已进入退避: {e}") from e
        raise


# ---------------------------------------------------------------- 回退与映射

def symbol_sina(code: str) -> str:
    """6 开头=沪市 sh,其余=深市 sz(北交所新浪无日线,PoC-2 口径)。"""
    return ("sh" if code.startswith("6") else "sz") + code


EM_HIST_RENAME = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low",
                  "收盘": "close", "成交量": "volume", "成交额": "amount",
                  "涨跌幅": "pct_chg", "换手率": "turnover"}

SPOT_RENAME = {"代码": "code", "名称": "name", "今开": "open", "最高": "high",
               "最低": "low", "最新价": "close", "昨收": "prev_close",
               "成交量": "volume", "成交额": "amount", "涨跌幅": "pct_chg",
               "换手率": "turnover"}


def normalize_em_hist(df):
    """东财 hist → 统一 BAR_COLUMNS(缺失列置 None,不造数)。"""
    out = df.rename(columns=EM_HIST_RENAME)
    for col in BAR_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[BAR_COLUMNS]


def normalize_spot(df):
    """东财全市场快照 → 统一列;date 由采集日填充。"""
    out = df.rename(columns=SPOT_RENAME)
    for col in BAR_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[BAR_COLUMNS]


def compute_breadth(spot_df: dict) -> dict:
    """真实涨跌家数宽度(补 L1):输入 normalized spot 行(含 pct_chg)。"""
    ups = downs = flats = 0
    for row in spot_df:
        chg = row.get("pct_chg")
        if chg is None:
            continue
        if chg > 0:
            ups += 1
        elif chg < 0:
            downs += 1
        else:
            flats += 1
    total = ups + downs
    return {"up": ups, "down": downs, "flat": flats,
            "breadth_ratio": (ups / total) if total else None}


# ---------------------------------------------------------------- 采集命令

def collect_daily(cfg: dict, conn, day: date | None = None, fetcher=None, limiter=None) -> dict:
    """日更:按日期全市场快照(1 请求/天)。幂等:manifest 已有即跳过。

    spot 接口是实时快照,只对"今天"有意义;day 非None时必须是今天。
    """
    day = day or date.today()
    params = {"day": day.isoformat()}
    tkey = task_key("akshare", "spot_snapshot", params)
    seen = has_task(conn, tkey)
    if seen is not None:
        return {"status": "skipped", "task_key": tkey, "rows": seen["rows"]}

    if fetcher is None:
        import akshare as ak  # noqa: PLC0415

        fetcher = ak.stock_zh_a_spot_em
    limiter = limiter or _limiter_from_cfg(cfg)
    raw_df = guarded_call(limiter, fetcher)
    norm = normalize_spot(raw_df)
    norm = norm[norm["code"].notna()]
    # date 列 = 采集日(快照语义;按源日期归档是 csqaq 教训 #4)
    norm = norm.assign(date=day.isoformat())

    raw_dir = resolve_path(cfg, "paths.lake_raw")
    raw_path = raw_dir / "akshare" / "spot" / f"dt={day:%Y%m%d}" / "part.parquet"
    write_parquet_atomic(raw_df, raw_path)

    norm_dir = resolve_path(cfg, "paths.lake_norm")
    norm_path = norm_dir / "daily_snapshot" / f"dt={day:%Y%m%d}" / "part.parquet"
    write_parquet_atomic(norm, norm_path)

    breadth = compute_breadth(norm.to_dict("records"))
    breadth_dir = norm_dir / "breadth" / f"dt={day:%Y%m%d}"
    write_parquet_atomic(_df_from_records([{**breadth, "date": day.isoformat()}]),
                         breadth_dir / "part.parquet")

    record_task(conn, tkey, "akshare", "spot_snapshot", params, len(norm), day.isoformat(),
                day.isoformat(), str(raw_path))
    log_event(conn, "INFO", "collect_daily", f"{day} rows={len(norm)} breadth={breadth}")
    return {"status": "ok", "task_key": tkey, "rows": len(norm), "breadth": breadth,
            "norm_path": str(norm_path)}


def fetch_hist(cfg: dict, conn, code: str, start: str, end: str,
               adjust: str = "hfq", fetcher=None, limiter=None) -> dict:
    """按股历史(东财 hfq)——仅交叉验证/小补丁;全市场回填走 backfill_cnequity。"""
    params = {"code": code, "start": start, "end": end, "adjust": adjust}
    tkey = task_key("akshare", "hist", params)
    seen = has_task(conn, tkey)
    if seen is not None:
        return {"status": "skipped", "task_key": tkey, "rows": seen["rows"]}

    if fetcher is None:
        import akshare as ak  # noqa: PLC0415

        fetcher = ak.stock_zh_a_hist
    limiter = limiter or _limiter_from_cfg(cfg)
    raw_df = guarded_call(limiter, fetcher, symbol=code, period="daily",
                          start_date=start.replace("-", ""), end_date=end.replace("-", ""),
                          adjust=adjust)
    norm = normalize_em_hist(raw_df)
    norm = norm[norm["date"].notna()].assign(code=code)

    raw_dir = resolve_path(cfg, "paths.lake_raw")
    raw_path = raw_dir / "akshare" / "hist" / f"{code}.parquet"
    write_parquet_atomic(raw_df, raw_path)
    norm_path = resolve_path(cfg, "paths.lake_norm") / "daily_bars" / f"{code}.parquet"
    write_parquet_atomic(norm, norm_path)

    record_task(conn, tkey, "akshare", "hist", params, len(norm),
                str(norm["date"].min()) if len(norm) else None,
                str(norm["date"].max()) if len(norm) else None, str(norm_path))
    return {"status": "ok", "task_key": tkey, "rows": len(norm), "norm_path": str(norm_path)}


def fetch_hist_sina(cfg: dict, conn, code: str, fetcher=None, limiter=None) -> dict:
    """退市股回退:新浪源(000003 已验证);股本/换手列为空(PoC-2,局限 L2)。"""
    params = {"code": code, "source": "sina"}
    tkey = task_key("sina", "hist", params)
    seen = has_task(conn, tkey)
    if seen is not None:
        return {"status": "skipped", "task_key": tkey, "rows": seen["rows"]}

    if fetcher is None:
        import akshare as ak  # noqa: PLC0415

        fetcher = ak.stock_zh_a_daily
    limiter = limiter or _limiter_from_cfg(cfg)
    raw_df = guarded_call(limiter, fetcher, symbol=symbol_sina(code))
    if raw_df is None or len(raw_df) == 0:
        raise ValueError(f"新浪源无数据: {code}")
    out = raw_df.rename(columns={"date": "date"})[["date", "open", "high", "low", "close", "volume", "amount"]]
    out = out.assign(code=code, name=None, prev_close=None, pct_chg=None, turnover=None)
    out = out[[c for c in BAR_COLUMNS if c in out.columns]]

    raw_path = resolve_path(cfg, "paths.lake_raw") / "sina" / "hist" / f"{code}.parquet"
    write_parquet_atomic(raw_df, raw_path)
    norm_path = resolve_path(cfg, "paths.lake_norm") / "daily_bars" / f"{code}.parquet"
    write_parquet_atomic(out, norm_path)

    record_task(conn, tkey, "sina", "hist", params, len(out),
                str(out["date"].min()), str(out["date"].max()), str(norm_path))
    log_event(conn, "INFO", "fetch_hist_sina", f"{code} rows={len(out)}")
    return {"status": "ok", "task_key": tkey, "rows": len(out), "norm_path": str(norm_path)}


def symbol_cne(code: str) -> str:
    """6 位代码 → CNEquity 湖内 instruments 的后缀格式(000001.SZ / 600519.SH / 920001.BJ)。"""
    code = code.strip()
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    return f"{code}.BJ"


def backfill_cnequity(cfg: dict, universe_codes: list[str], start: str, end: str,
                      config_path: str | Path | None = None,
                      try_run: bool = False) -> dict:
    """历史回填主源 = CNEquity TDX(关锁决策,METHODS §0)。

    真实接口(2026-11-12 对 cne CLI 实测,--plan 干跑已验证):
      cne config create --config <lake_cfg> --data-root <lake> --force
      cne backfill daily_bars --config <lake_cfg> --start S --end E --symbols c1,c2,...
      cne backfill daily_bars --config <lake_cfg> --profile delisted   # 退市股(幸存者偏差对策)
    daily_bars 按 symbol 逐只抓取,与窗口年数无关——务必用 --symbols 限定作用域,
    先小批试点(50 只/1 年)校验 PIT/退市/复权,再放全市场。

    默认只生成命令与成分清单(不动网络);try_run=True 才执行——沙箱内
    msvcrt.locking 会被拦(PoC-3),真实抓取须在宿主机命令行跑。
    """
    repo_root = Path(__file__).resolve().parent.parent
    lake_cfg = Path(config_path) if config_path else repo_root / "configs" / "cnequity.toml"
    lake_root = repo_root / "data" / "cnequity-lake"
    syms = ",".join(symbol_cne(c) for c in universe_codes)
    commands = [
        f'cne config create --config "{lake_cfg}" --data-root "{lake_root}" --force',
        f'cne backfill daily_bars --config "{lake_cfg}" --plan --start {start} --end {end} --symbols {syms}',
        f'cne backfill daily_bars --config "{lake_cfg}" --start {start} --end {end} --symbols {syms}',
        f'cne backfill daily_bars --config "{lake_cfg}" --profile delisted',
    ]
    result = {
        "status": "prepared",
        "universe_count": len(universe_codes),
        "window": [start, end],
        "lake_config": str(lake_cfg),
        "commands": commands,
        "note": "先跑 --plan 干跑核对作用域;真实抓取在宿主机命令行(沙箱拦 msvcrt.locking,PoC-3)",
    }
    if try_run:
        import subprocess
        cne_exe = "cne"
        try:
            proc = subprocess.run(
                [cne_exe, "backfill", "daily_bars", "--config", str(lake_cfg),
                 "--start", start, "--end", end, "--symbols", syms],
                capture_output=True, text=True, timeout=3600)
            result["status"] = "ok" if proc.returncode == 0 else "failed"
            result["stdout_tail"] = proc.stdout[-800:]
            result["stderr_tail"] = proc.stderr[-800:]
        except FileNotFoundError:
            result["status"] = "cne_not_found"
            result["hint"] = "宿主机无 cne 命令;用 WorkBuddy venv 的 Scripts/cne.exe 或把 venv/Scripts 加入 PATH"
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
    return result


# ---------------------------------------------------------------- 内部工具

def _limiter_from_cfg(cfg: dict) -> RateLimiter:
    c = cfg["collect"]
    return RateLimiter(
        min_interval=c["min_interval_seconds"],
        state_path=resolve_path(cfg, "collect.cooldown_file"),
        backoff_initial=c["backoff_initial_seconds"],
        backoff_max=c["backoff_max_seconds"],
    )


def _df_from_records(records: list[dict]):
    import pandas as pd  # noqa: PLC0415

    return pd.DataFrame(records)
