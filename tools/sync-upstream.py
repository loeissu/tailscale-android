#!/usr/bin/env python3
# Copyright (c) 2026 loeissu
# SPDX-License-Identifier: BSD-3-Clause
"""sync-upstream.py - 检测并同步上游正式 Release 到汉化分支（阶段四）。

模式（last-release 更新时机二选一，默认 A 简单模式）:
  A 简单模式: sync 推送 main 前更新 tools/zh-last-release.txt；
            若后续 build 失败，人工重跑 release 工作流，不阻塞下次同步。
  B 严格模式: build 发布成功后再更新 last-release（经 repository_dispatch 回调）。
            启用方式: --mode B。

流程:
  1. 读取 tools/zh-last-release.txt（上次同步 tag）。
  2. 经 GitHub API 检测上游最新 Release tag。
  3. 无新版 => 打印 "无新版跳过"，退出码 0。
  4. 有新版 => 本地执行:
     a. fetch upstream <tag>
     b. 以新 tag 创建临时分支 sync/zh-<tag>
     c. 恢复保留清单（tools/retain-list.json）:
        - added:   从 main 复制回工作区
        - shared:  git merge-file 三路合并（base=上次同步 tag, ours=main, theirs=新 tag）
     d. python tools/apply-zh.py          生成 values-zh-rCN
     e. python tools/apply-zh.py --check  校验（剩余=0 才 PASS）
     f. 更新 tools/zh-last-release.txt
     g. 提交并推送 sync/zh-<tag> 分支
  5. 简单模式 A: 更新 last-release 并 commit 后，把 main 更新到 sync 分支并推送；
     打标签 v{短版本}-zh 并推送，触发 release 工作流。
  任何失败: 远程 main 不变、不发布；退出码非 0；日志由 CI 保留，可手动重跑。

用法:
  python tools/sync-upstream.py [--token GH_TOKEN] [--mode A|B]
环境变量: GITHUB_TOKEN（API + 推送鉴权）。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "tailscale/tailscale-android"
UPSTREAM_REMOTE = "https://github.com/tailscale/tailscale-android.git"
RELEASE_API = f"https://api.github.com/repos/{UPSTREAM}/releases/latest"

TAG_VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)(?:-t[0-9a-f]+-g[0-9a-f]+)?$")


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.stderr.write(f"command failed: {args}\n{r.stdout}\n{r.stderr}\n")
        raise SystemExit(1)
    return r


def git(cwd, *args, check=True):
    return sh(["git", *args], cwd=cwd, check=check)


def latest_upstream_release(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "sync-upstream-zh",
        "Accept": "application/vnd.github+json",
    }
    req = Request(RELEASE_API, headers=headers)
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tag_name", "")


def short_version(tag):
    """从上游 tag（如 1.102.2-t..-g..）取短版本号（1.102.2）。"""
    m = TAG_VERSION_RE.match(tag)
    return m.group(1) if m else tag


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token", default=None, help="GitHub token（缺省读 GITHUB_TOKEN）")
    ap.add_argument("--mode", choices=["A", "B"], default="A", help="last-release 更新时机")
    ap.add_argument("--upstream-tag", default=None, help="指定上游 tag（测试用，跳过 API 检测）")
    args = ap.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("error: GITHUB_TOKEN 未设置", file=sys.stderr)
        sys.exit(1)

    last_release = (ROOT / "tools" / "zh-last-release.txt").read_text(encoding="utf-8").strip()
    print(f"上次同步: {last_release}")

    new_tag = args.upstream_tag or latest_upstream_release(token)
    print(f"上游最新 Release: {new_tag}")

    if new_tag == last_release:
        print("无新版跳过（当前已是最新）")
        sys.exit(0)

    if args.upstream_tag and new_tag != args.upstream_tag:
        print(f"指定 tag 与 API 检测不一致: {new_tag} vs {args.upstream_tag}", file=sys.stderr)
        sys.exit(1)

    retain = json.loads((ROOT / "tools" / "retain-list.json").read_text(encoding="utf-8"))
    added_paths = retain["added"]
    shared_paths = list(retain.get("shared", {}).keys())

    # 确保上游 tag 已获取
    git(ROOT, "fetch", "upstream", "--tags", new_tag)

    branch = f"sync/zh-{new_tag}"
    git(ROOT, "checkout", "-b", branch, new_tag)

    # --- 恢复保留清单 ---
    for p in added_paths:
        git(ROOT, "restore", "--source=main", "--staged", "--worktree", p)
        print(f"restored added: {p}")

    for p in shared_paths:
        # base = 上次同步 tag 的版本；ours = main 的汉化版；theirs = 新 tag（当前工作区）
        r_base = git(ROOT, "show", f"{last_release}:{p}", check=False)
        if r_base.returncode != 0:
            git(ROOT, "checkout", "main", "--", p)
            print(f"shared(first-sync): {p} 采用 main 版本")
            continue
        with tempfile.TemporaryDirectory() as td:
            base_f = Path(td) / "base"
            ours_f = Path(td) / "ours"
            theirs_f = Path(td) / "theirs"
            base_f.write_bytes(r_base.stdout.encode("utf-8"))
            ours_f.write_bytes(git(ROOT, "show", f"main:{p}").stdout.encode("utf-8"))
            theirs_f.write_bytes((ROOT / p).read_bytes())
            r = sh(["git", "merge-file", str(ours_f), str(base_f), str(theirs_f)], cwd=ROOT, check=False)
            if r.returncode != 0:
                print(f"shared: {p} 三路合并冲突，需要人工处理:\n{r.stdout}\n{r.stderr}", file=sys.stderr)
                sys.exit(1)
            (ROOT / p).write_bytes(ours_f.read_bytes())
        print(f"shared merged (3-way): {p}")

    # --- apply 词典 ---
    sh([sys.executable, "tools/apply-zh.py"], cwd=ROOT)
    sh([sys.executable, "tools/apply-zh.py", "--check"], cwd=ROOT)

    # --- 更新 last-release ---
    (ROOT / "tools" / "zh-last-release.txt").write_text(new_tag + "\n", encoding="utf-8")

    git(ROOT, "add", "-A")
    git(ROOT, "commit", "-m", f"zh: sync upstream {new_tag}", check=False)

    print(f"sync 分支就绪: {branch}")
    if args.mode == "A":
        git(ROOT, "push", "origin", f"{branch}:{branch}", "--force-with-lease")
        # 简单模式 A: 推送前已更新 last-release
        # 将 main 更新到 sync 分支（force-with-lease，内容 = 上游新 tag + 保留清单 + apply 结果）
        git(ROOT, "push", "origin", f"{branch}:main", "--force-with-lease")
        tag = f"v{short_version(new_tag)}-zh"
        git(ROOT, "tag", "-f", tag)
        git(ROOT, "push", "origin", tag, "--force")
        print(f"已更新 main 并推送 tag {tag}")
        print("请查看 release 工作流结果；若失败可手动重跑 release.yml，不阻塞下次同步（模式 A）")
    else:
        print("严格模式 B：请人工确认 release 发布成功后，再调用本脚本更新 last-release 并推送")
        print(f"待推送分支: {branch}")
    sys.exit(0)


if __name__ == "__main__":
    main()
