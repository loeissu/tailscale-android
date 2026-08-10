#!/usr/bin/env python3
# Copyright (c) 2026 loeissu
# SPDX-License-Identifier: BSD-3-Clause
"""extract-zh.py - 从上游英文基准提取可翻译字符串，更新 tools/zh_cn.json。

用法:
  python tools/extract-zh.py                    # 用默认路径（仓库根目录下）更新词典
  python tools/extract-zh.py --values-dir X     # 指定 values 目录
  python tools/extract-zh.py --dict Y           # 指定词典路径
  python tools/extract-zh.py --out Z            # 指定输出词典路径（默认覆盖 --dict）

行为:
  - 解析 values/strings.xml 与 values/string-arrays.xml。
  - 只收录 translatable（跳过 translatable="false"）。
  - 保留 zh_cn.json 中已有的翻译；新增条目以空串占位。
  - 输出剩余未翻译数（stderr），0 时退出码 0，否则退出码 1。
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUES = ROOT / "android" / "src" / "main" / "res" / "values"
DEFAULT_DICT = ROOT / "tools" / "zh_cn.json"

STRING_RE = re.compile(r"<string\s+name=\"([^\"]+)\"([^>]*)>(.*?)</string>", re.DOTALL)
ARRAY_RE = re.compile(r"<string-array\s+name=\"([^\"]+)\"([^>]*)>(.*?)</string-array>", re.DOTALL)
ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL)
TRANSLATABLE_FALSE = re.compile(r"translatable\s*=\s*[\"']false[\"']")
NAME_ATTR = re.compile(r"name=\"([^\"]+)\"")


def _decode(raw: str) -> str:
    """把资源原文解码为普通文本（用于显示/占位符提取），仅供参考。"""
    return raw


def parse_strings(text: str):
    out = []
    for m in STRING_RE.finditer(text):
        name, attrs, content = m.group(1), m.group(2), m.group(3)
        if TRANSLATABLE_FALSE.search(attrs):
            continue
        out.append((name, content))
    return out


def parse_arrays(text: str):
    out = []
    for m in ARRAY_RE.finditer(text):
        name, attrs, content = m.group(1), m.group(2), m.group(3)
        if TRANSLATABLE_FALSE.search(attrs):
            continue
        items = [it.group(1) for it in ITEM_RE.finditer(content)]
        out.append((name, items))
    return out


def load_dict(path: Path):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"strings": {}, "string_arrays": {}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--values-dir", default=str(DEFAULT_VALUES))
    ap.add_argument("--dict", default=str(DEFAULT_DICT))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    values = Path(args.values_dir)
    strings_file = values / "strings.xml"
    arrays_file = values / "string-arrays.xml"

    d = load_dict(Path(args.dict))
    d.setdefault("strings", {})
    d.setdefault("string_arrays", {})
    d.setdefault("meta", {})
    d["meta"]["description"] = "Tailscale Android 汉化词典 (resource key -> 简体中文)"
    d["meta"]["generated_by"] = "tools/extract-zh.py"

    def add(container, key, default):
        if key not in container or container[key] in (None, ""):
            container[key] = default

    new_strs = 0
    for name, content in parse_strings(strings_file.read_text(encoding="utf-8")):
        if name not in d["strings"]:
            d["strings"][name] = ""
            new_strs += 1
        elif not d["strings"][name]:
            new_strs += 1

    new_arrs = 0
    for name, items in parse_arrays(arrays_file.read_text(encoding="utf-8")):
        if name not in d["string_arrays"] or len(d["string_arrays"][name]) != len(items):
            d["string_arrays"][name] = [""] * len(items)
            new_arrs += 1
        else:
            for i, v in enumerate(d["string_arrays"][name]):
                if not v:
                    new_arrs += 1

    d["meta"]["string_count"] = len(d["strings"])
    d["meta"]["array_count"] = len(d["string_arrays"])

    out = Path(args.out) if args.out else Path(args.dict)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    missing = sum(1 for v in d["strings"].values() if not v)
    missing += sum(1 for arr in d["string_arrays"].values() for v in arr if not v)

    print(f"extract-zh: strings={len(d['strings'])} arrays={len(d['string_arrays'])} "
          f"new_keys={new_strs + new_arrs} missing={missing} -> {out}")
    if missing:
        print(f"[missed] 剩余未翻译条目数 = {missing}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
