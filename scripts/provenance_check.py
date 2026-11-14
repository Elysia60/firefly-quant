#!/usr/bin/env python3
"""PROVENANCE 校验器(--write 生成清单;默认模式逐文件比对 SHA256)。

用法:
  python scripts/provenance_check.py --write   # 发布时:生成/更新 PROVENANCE.md 清单段
  python scripts/provenance_check.py           # 验证:当前文件与清单逐字节比对
退出码:0 = ALL OK / 1 = 有不符或缺失。
"""
import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROV = REPO / "PROVENANCE.md"
BEGIN = "<!-- MANIFEST"
END = "--> /MANIFEST"


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8").stdout
    return [Path(REPO / line.strip()) for line in out.splitlines()
            if line.strip() and "PROVENANCE.md" not in line]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def write_manifest():
    lines = ["| 文件 | SHA256 |", "|---|---|"]
    for p in tracked_files():
        if not p.exists():
            continue
        lines.append(f"| {p.relative_to(REPO).as_posix()} | {sha256(p)} |")
    text = PROV.read_text(encoding="utf-8")
    head = text.split(BEGIN)[0]
    tail = text.split(END)[-1] if END in text else ""
    PROV.write_text(head + BEGIN + " 由 provenance_check.py --write 生成,勿手改\n"
                    + "\n".join(lines) + "\n" + END + tail, encoding="utf-8")


def verify() -> int:
    text = PROV.read_text(encoding="utf-8")
    if BEGIN not in text:
        print("清单不存在——先跑 --write")
        return 1
    manifest = {}
    seg = text.split(BEGIN)[1].split(END)[0]
    for line in seg.splitlines():
        if line.startswith("| ") and "SHA256" not in line and "---" not in line:
            parts = [x.strip() for x in line.strip("|").split("|")]
            if len(parts) == 2:
                manifest[parts[0]] = parts[1]
    bad, missing = [], []
    for rel, expected in manifest.items():
        p = REPO / rel
        if not p.exists():
            missing.append(rel)
            continue
        if sha256(p) != expected:
            bad.append(rel)
    extra = [str(p.relative_to(REPO).as_posix()) for p in tracked_files()
             if p.relative_to(REPO).as_posix() not in manifest
             and "PROVENANCE.md" not in str(p)]
    if bad or missing:
        for x in bad:
            print(f"✗ 篡改/不符: {x}")
        for x in missing:
            print(f"✗ 缺失: {x}")
        return 1
    print(f"ALL OK({len(manifest)} 文件逐字节一致"
          + (f";另有未入清单新文件 {len(extra)}(正常,属发布后新增)" if extra else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(write_manifest() or 0 if "--write" in sys.argv else verify())
