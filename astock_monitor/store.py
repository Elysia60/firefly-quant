"""存储层:SQLite(WAL,幂等 upsert)做账本,Parquet 湖存数据。

分工(对齐 PoC/筛查定案):
- SQLite monitor.db:collect_manifest(采集任务账本,防重复请求)+ collect_log(运行日志)
- Parquet 湖:data/lake/raw/{source}/{dataset}/... 原样落盘(可由 akshare 独立重建)
- 幂等纪律:manifest 主键 = task_key(source+dataset+参数哈希);重跑先查账本,已存在即跳过
- 原子写:Parquet 先写 tmp 再 os.replace,进程崩溃不留半截文件

pandas/pyarrow 惰性导入——账本逻辑保持零依赖,可单测。
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def get_conn(db_path: Path) -> sqlite3.Connection:
    """打开 SQLite 连接,确保 WAL 模式(csqaq 纪律:在线备份/并发读友好)。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collect_manifest (
            task_key    TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            dataset     TEXT NOT NULL,
            params_json TEXT NOT NULL,
            rows        INTEGER,
            first_date  TEXT,
            last_date   TEXT,
            file_path   TEXT,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS collect_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts     TEXT NOT NULL,
            level  TEXT NOT NULL,
            event  TEXT NOT NULL,
            detail TEXT
        );
        """
    )
    conn.commit()


def task_key(source: str, dataset: str, params: dict) -> str:
    """任务主键 = source|dataset|参数规范化哈希(参数顺序无关)。"""
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"{source}|{dataset}|{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def has_task(conn: sqlite3.Connection, tkey: str) -> dict | None:
    row = conn.execute(
        "SELECT task_key, source, dataset, params_json, rows, first_date, last_date, file_path, updated_at"
        " FROM collect_manifest WHERE task_key = ?",
        (tkey,),
    ).fetchone()
    if row is None:
        return None
    keys = ["task_key", "source", "dataset", "params_json", "rows", "first_date", "last_date", "file_path", "updated_at"]
    return dict(zip(keys, row))


def record_task(
    conn: sqlite3.Connection,
    tkey: str,
    source: str,
    dataset: str,
    params: dict,
    rows: int,
    first_date: str | None,
    last_date: str | None,
    file_path: str | None,
) -> None:
    """幂等 upsert:同一 task_key 重跑覆盖旧账本行(数据文件本身也是原子覆盖)。"""
    conn.execute(
        "INSERT INTO collect_manifest"
        " (task_key, source, dataset, params_json, rows, first_date, last_date, file_path, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(task_key) DO UPDATE SET"
        " rows=excluded.rows, first_date=excluded.first_date, last_date=excluded.last_date,"
        " file_path=excluded.file_path, updated_at=excluded.updated_at",
        (tkey, source, dataset, json.dumps(params, ensure_ascii=False, sort_keys=True),
         rows, first_date, last_date, file_path, _now()),
    )
    conn.commit()


def log_event(conn: sqlite3.Connection, level: str, event: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO collect_log (ts, level, event, detail) VALUES (?, ?, ?, ?)",
        (_now(), level, event, detail),
    )
    conn.commit()


def write_parquet_atomic(df, path: Path) -> Path:
    """DataFrame → Parquet 原子写(tmp + os.replace)。pandas/pyarrow 惰性导入。"""
    import pandas as pd  # noqa: PLC0415 — 数据路径才需要

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return path


def read_parquet(path: Path):
    import pandas as pd  # noqa: PLC0415

    return pd.read_parquet(path)
