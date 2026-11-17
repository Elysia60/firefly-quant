"""盈利数据采集 — 业绩报表(⑧ 生产率盲区的数据底座第一步)。

来源:akshare stock_yjbb_em(东财业绩报表,全市场一张表,1 请求/报告期)。
定位(预注册声明):2027 剧本"企业生存质量"维度的**仪表底座**——风暴中
谁活下来(盈利质量分布),**不是**选股因子(不加因子,DSR 中性,曼昆精读 ⑧)。

纪律:
  · 幂等:同报告期已采即跳过(manifest 记账)
  · 落湖:raw/akshare/yjbb/dt={报告期}/part.parquet(与 zt/margin 同风格)
  · 税制类比:报告期数据有披露时滞,PIT 需按公告日过滤——v1 只落原始表,
    PIT 加工在消费侧做(诚实声明,不静默造 PIT)
"""
from __future__ import annotations

import pandas as pd

from .collect import guarded_call
from .config import resolve_path
from .store import has_task, log_event, record_task, task_key, write_parquet_atomic


def collect_yjbb(cfg: dict, conn, period: str, fetcher=None, limiter=None) -> dict:
    """业绩报表落湖(全市场一张表)。period = 'YYYYMMDD'(报告期,如 20260930)。"""
    if not (len(period) == 8 and period.isdigit()):
        raise ValueError(f"period 需为 YYYYMMDD,得到 {period!r}")
    params = {"dataset": "yjbb", "period": period}
    tkey = task_key("akshare", "yjbb", params)
    seen = has_task(conn, tkey)
    if seen is not None:
        return {"status": "skipped", "task_key": tkey, "rows": seen["rows"]}

    if fetcher is None:
        import akshare as ak  # noqa: PLC0415
        fetcher = ak.stock_yjbb_em
    limiter = limiter or _limiter(cfg)
    raw = guarded_call(limiter, fetcher, period)
    if raw is None or len(raw) == 0:
        raise ValueError(f"业绩报表 {period} 返回空")

    raw_dir = resolve_path(cfg, "paths.lake_raw") / "akshare" / "yjbb" / f"dt={period}"
    path = write_parquet_atomic(raw, raw_dir / "part.parquet")
    record_task(conn, tkey, "akshare", "yjbb", params, len(raw),
                period, period, str(path))
    log_event(conn, "INFO", "collect_yjbb", f"{period} rows={len(raw)}")
    return {"status": "ok", "task_key": tkey, "rows": len(raw), "path": str(path)}


def _limiter(cfg: dict):
    from .collect import RateLimiter
    return RateLimiter(min_interval=float((cfg.get("collect") or {}).get("min_interval", 1.0)))
