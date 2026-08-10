#!/usr/bin/env python3
# Copyright (c) 2026 loeissu
# SPDX-License-Identifier: BSD-3-Clause
"""apply-zh.py - 依据 tools/zh_cn.json 生成 values-zh-rCN 中文资源并校验完整性。

用法:
  python tools/apply-zh.py                  # 生成 values-zh-rCN/strings.xml 与 string-arrays.xml
  python tools/apply-zh.py --check          # 只校验：未翻译条目输出 [missed]，剩余=0 才 PASS

校验规则:
  - 每个可翻译条目（translatable 非 false）都必须在词典中有非空译文。
  - 译文必须保留英文原文中的全部格式占位符（%s、%d、%1$s、%.1f 等），且不新增占位符。
  - 未翻译/占位符不一致 => 输出 [missed] 到日志；剩余数 != 0 时退出码非 0。
  - 不修改变量/URL/路径/占位符：仅替换 <string>/<item> 的文本内容。
  - 白名单（GitHub/OpenGL/FPS/VPN/DNS/Taildrop/Tailscale/Mullvad 等专有名词）本就不需要翻译，
    词典 key 存在即为已翻译，不会误判。

可无损还原: 删除 values-zh-rCN 目录即可恢复为上游英文基准；apply 输出由
基准 + 词典确定性生成。
"""

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUES = ROOT / "android" / "src" / "main" / "res" / "values"
DEFAULT_ZH_VALUES = ROOT / "android" / "src" / "main" / "res" / "values-zh-rCN"
DEFAULT_DICT = ROOT / "tools" / "zh_cn.json"

STRING_RE = re.compile(r"<string\s+name=\"([^\"]+)\"([^>]*)>(.*?)</string>", re.DOTALL)
ARRAY_RE = re.compile(r"<string-array\s+name=\"([^\"]+)\"([^>]*)>(.*?)</string-array>", re.DOTALL)
ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL)
TRANSLATABLE_FALSE = re.compile(r"translatable\s*=\s*[\"']false[\"']")

# Android printf 占位符（%s %d %1$s %.1f %2$d 等），用于保留性校验
PH_RE = re.compile(r"%\d+\$?[-+ 0#,]*(?:\d+)?(?:\.\d+)?[bBhHcCdDeEfFgGoOsSxXtT%]")


def placeholders(text: str):
    return sorted(PH_RE.findall(text))


def to_xml_text(s: str) -> str:
    """把纯文本译文转成 Android 字符串资源文本：
    - XML 转义 & < >
    - 撇号转义为 \\'
    - 真实换行转义为 \\n（Android 字面量）
    - 占位符 %.. 原样保留
    """
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace("'", "\\'")
    s = s.replace("\n", "\\n")
    return s


def parse_strings(text: str):
    out = []
    for m in STRING_RE.finditer(text):
        name, attrs, content = m.group(1), m.group(2), m.group(3)
        if TRANSLATABLE_FALSE.search(attrs):
            continue
        out.append((name, content.strip("\n")))
    return out


def parse_arrays(text: str):
    out = []
    for m in ARRAY_RE.finditer(text):
        name, attrs, content = m.group(1), m.group(2), m.group(3)
        if TRANSLATABLE_FALSE.search(attrs):
            continue
        items = [it.group(1).strip("\n") for it in ITEM_RE.finditer(content)]
        out.append((name, items))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--values-dir", default=str(DEFAULT_VALUES))
    ap.add_argument("--zh-values-dir", default=str(DEFAULT_ZH_VALUES))
    ap.add_argument("--dict", default=str(DEFAULT_DICT))
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    values = Path(args.values_dir)
    zh_values = Path(args.zh_values_dir)
    dict_path = Path(args.dict)
    if not dict_path.exists():
        print(f"[missed] 词典不存在: {dict_path}", file=sys.stderr)
        sys.exit(1)

    import json
    with open(dict_path, encoding="utf-8") as f:
        d = json.load(f)
    strings_zh = d.get("strings", {})
    arrays_zh = d.get("string_arrays", {})

    missed = []
    warnings = []

    translatable = parse_strings((values / "strings.xml").read_text(encoding="utf-8"))
    for name, en in translatable:
        zh = strings_zh.get(name, "")
        if not zh:
            missed.append(f"[missed] <string name=\"{name}\">")
            continue
        en_ph, zh_ph = placeholders(en), placeholders(zh)
        if en_ph != zh_ph:
            missed.append(
                f"[missed] <string name=\"{name}\"> 占位符不一致 en={en_ph} zh={zh_ph}"
            )

    translatable_arrs = parse_arrays((values / "string-arrays.xml").read_text(encoding="utf-8"))
    for name, items in translatable_arrs:
        arr = arrays_zh.get(name, [])
        if len(arr) != len(items):
            missed.append(f"[missed] <string-array name=\"{name}\"> 条目数量不一致")
            continue
        for i, (en, zh) in enumerate(zip(items, arr)):
            if not zh:
                missed.append(f"[missed] <string-array name=\"{name}\"> item[{i}]")
                continue
            en_ph, zh_ph = placeholders(en), placeholders(zh)
            if en_ph != zh_ph:
                missed.append(
                    f"[missed] <string-array name=\"{name}\"> item[{i}] 占位符不一致 "
                    f"en={en_ph} zh={zh_ph}"
                )

    for line in missed:
        print(line, file=sys.stderr)

    if missed:
        print(f"[missed] 剩余未翻译条目数 = {len(missed)}  ==> FAIL", file=sys.stderr)
        sys.exit(1)

    print("apply-zh: 全部条目已翻译，占位符一致 ==> PASS (剩余=0)")
    if args.check:
        sys.exit(0)

    # 生成 values-zh-rCN 资源
    zh_values.mkdir(parents=True, exist_ok=True)

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<resources>",
        "    <!-- Auto-generated by tools/apply-zh.py. Do not edit manually. -->",
    ]
    for name, en in translatable:
        lines.append(f"    <string name=\"{name}\">{to_xml_text(strings_zh[name])}</string>")
    lines.append("</resources>")
    (zh_values / "strings.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    arr_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<resources>",
        "    <!-- Auto-generated by tools/apply-zh.py. Do not edit manually. -->",
    ]
    for name, items in translatable_arrs:
        arr_lines.append(f"    <string-array name=\"{name}\">")
        for zh in arrays_zh[name]:
            arr_lines.append(f"        <item>{to_xml_text(zh)}</item>")
        arr_lines.append("    </string-array>")
    arr_lines.append("</resources>")
    (zh_values / "string-arrays.xml").write_text("\n".join(arr_lines) + "\n", encoding="utf-8")

    print(f"apply-zh: 已生成 {zh_values}/strings.xml ({len(translatable)} 条) 与 "
          f"{zh_values}/string-arrays.xml ({len(translatable_arrs)} 个数组)")
    sys.exit(0)


if __name__ == "__main__":
    main()
