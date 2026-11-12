"""配置加载:config.json 是唯一配置正本,路径相对仓库根目录解析。

不引第三方依赖;路径统一返回 pathlib.Path(绝对路径)。
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.json"


def load_config(path: str | Path | None = None) -> dict:
    """读 config.json;缺失字段直接 KeyError 报错(fail loud,不静默给默认值)。"""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def resolve_path(cfg: dict, key_path: str) -> Path:
    """按 'paths.xxx' 或 'collect.xxx' 点路径取配置并解析为绝对路径。

    相对路径一律相对仓库根目录(config.json 所在目录),与 cwd 无关。
    """
    node: object = cfg
    for part in key_path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"config 缺少键: {key_path}")
        node = node[part]
    p = Path(str(node))
    return p if p.is_absolute() else (REPO_ROOT / p)


def ensure_dir(p: Path) -> Path:
    """确保目录存在(幂等),返回原路径。"""
    p.mkdir(parents=True, exist_ok=True)
    return p
