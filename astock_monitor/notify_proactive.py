"""主动消息推送出口(watchdog 与 triggers 共用)。

双通道设计:
  1. 仓库本地通道: data/proactive/(gitignored,公开仓不含)
  2. 伴侣通道: 路径从 data/state/proactive_dir.txt 读取(本机创建,不入库)——
     存在则同时写入;不存在跳过(公开部署零依赖)
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "data" / "state"
LOCAL_DIR = REPO / "data" / "proactive"
CHANNEL_FILE = STATE_DIR / "proactive_dir.txt"


def push_lines(lines: list[str], filename: str | None = None) -> str | None:
    """追加写入两个通道;失败返回 None,不抛异常(告警出口不可因自身故障中断主流程)。"""
    name = filename or f"{dt.date.today():%Y-%m-%d}-watchdog.md"
    written = None
    for d in [LOCAL_DIR, _companion_dir()]:
        if d is None:
            continue
        try:
            d.mkdir(parents=True, exist_ok=True)
            p = d / name
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            written = str(p)
        except OSError:
            continue
    return written


def _companion_dir() -> Path | None:
    try:
        if CHANNEL_FILE.exists():
            txt = CHANNEL_FILE.read_text(encoding="utf-8").strip()
            return Path(txt) if txt else None
    except OSError:
        pass
    return None
