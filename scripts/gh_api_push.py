#!/usr/bin/env python3
"""经 gh api(Git Data API)推送——git HTTPS 端点被卡时走 api.github.com 通道。

流程:空仓库引导(Contents API PUT)→ 逐文件 blob → tree → commit → main → tag。
网络闪断(api.github.com 间歇 EOF)→ 每调用 5 次退避重试。
"""
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWNER_REPO = "Elysia60/firefly-quant"
NUL = chr(0)  # git ls-files -z 的分隔符(用 chr 构造,防源码里出现真空字节)


def gh(endpoint: str, payload: dict | None = None, method: str | None = None,
       attempts: int = 10):
    """gh api + 网络闪断重试。"""
    last = None
    for attempt in range(1, attempts + 1):
        cmd = ["gh", "api", f"repos/{OWNER_REPO}/{endpoint}"]
        if payload is not None or method:
            cmd += ["-X", method or "POST", "--input", "-"]
        if payload is not None:
            cmd += ["--input", "-"]
        r = subprocess.run(cmd, input=(json.dumps(payload) if payload is not None else ""),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode == 0:
            return json.loads(r.stdout) if (r.stdout or "").strip() else {}
        err = r.stderr[:300]
        transient = any(k in err for k in ("EOF", "handshake", "Connection", "timeout",
                                           "connection reset", "unexpected disconnect"))
        if not transient:
            raise RuntimeError(f"gh api {endpoint}: {err}")
        last = RuntimeError(f"gh api {endpoint}(第 {attempt} 次): {err}")
        print(f"  网络闪断,重试 {attempt}/{attempts}…")
        time.sleep(min(3 * attempt, 10))
    raise last


def put_contents(path: str, content_b64: str, message: str):
    """Contents API PUT(空仓库引导/单文件更新,自动产生提交)。"""
    return gh(f"contents/{path}", {"message": message, "content": content_b64},
              method="PUT")


def main() -> int:
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True).stdout
    files = [Path(REPO / x) for x in raw.decode("utf-8").split(NUL) if x]
    print(f"上传 {len(files)} 个文件…")

    # 引导提交:仅当仓库尚无提交时 PUT;若 README 已存在(此前引导过)→ 直接取头
    base = None
    try:
        base = gh("commits/main")["sha"]
        print("仓库已有提交,跳过引导")
    except RuntimeError:
        try:
            bootstrap = REPO / "README.md"
            put_contents("README.md",
                         base64.b64encode(bootstrap.read_bytes()).decode(),
                         "萤火 Firefly v0.2.0:引导提交(bootstrap via Contents API)")
        except RuntimeError as e:
            if "422" not in str(e) and "sha" not in str(e):
                raise
            print("README 已存在(此前引导过),继续")
        base = gh("commits/main")["sha"]
        print("引导提交完成")

    # blob 缓存(内容寻址):跨次重跑只补缺失,收敛式推进
    cache_p = REPO / "data" / "state" / "gh_blob_cache.json"
    cache = {}
    try:
        cache = json.loads(cache_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    tree = []
    uploaded = skipped = 0
    for i, p in enumerate(files):
        rel = p.relative_to(REPO).as_posix()
        raw = p.read_bytes()
        fkey = hashlib.sha256(raw).hexdigest()
        if fkey in cache:
            tree.append({"path": rel, "mode": "100755" if rel.endswith(".bat") else "100644",
                         "type": "blob", "sha": cache[fkey]})
            skipped += 1
            continue
        content = base64.b64encode(raw).decode()
        blob = gh("git/blobs", {"content": content, "encoding": "base64"})
        cache[fkey] = blob["sha"]
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tree.append({"path": rel, "mode": "100755" if rel.endswith(".bat") else "100644",
                     "type": "blob", "sha": blob["sha"]})
        uploaded += 1
        print(f"  [{i+1}/{len(files)}] {rel} 上传")
    print(f"  blob: 新传 {uploaded} / 缓存复用 {skipped}")

    tree_sha = gh("git/trees", {"tree": tree})["sha"]
    parents = [base]
    commit = gh("git/commits", {
        "message": ("萤火 Firefly v0.2.0:全链路发布\n\n"
                    "数据湖(双源对账196万行) · 对账记分牌 · regime门控 · 审计三件套\n"
                    "结论注册表[S1]-[S7](含反方陈述与推翻观测) · 147单测 · 计划任务自动化\n\n"
                    "License: CC BY-NC-SA 4.0 · 出处: github.com/Elysia60/firefly-quant"),
        "tree": tree_sha, "parents": parents})["sha"]

    # main:有引导提交则 PATCH 前进,空 ref 则 POST 创建
    try:
        gh("git/refs/heads/main", {"sha": commit, "force": True}, method="PATCH")
    except RuntimeError:
        gh("git/refs", {"ref": "refs/heads/main", "sha": commit})
    try:
        gh("git/refs", {"ref": "refs/tags/v0.2.0-firefly", "sha": commit})
    except RuntimeError as e:
        print("tag 已存在:", e)
    print(f"完成: commit {commit[:12]} → main + tag v0.2.0-firefly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
