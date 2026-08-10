#!/usr/bin/env python3
# Copyright (c) 2026 loeissu
# SPDX-License-Identifier: BSD-3-Clause
"""emu_ui_tap.py - 在 Android 模拟器上按文本属性点按 UI 节点（用于 CI 截图前关闭 ANR/VPN 弹窗）。

用法:
  python3 tools/emu_ui_tap.py "Wait"      # 点按文本为 "Wait" 的按钮（ANR 弹窗）
  python3 tools/emu_ui_tap.py "CANCEL"    # 点按文本为 "CANCEL" 的按钮（VPN 请求弹窗）

依赖: adb 在 PATH 中。
"""

import re
import subprocess
import sys


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def main():
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("usage: python3 tools/emu_ui_tap.py <text>", file=sys.stderr)
        sys.exit(2)
    text = sys.argv[1]

    run("adb shell uiautomator dump /sdcard/u.xml")
    xml = run("adb shell cat /sdcard/u.xml").stdout
    pat = re.compile(
        r'text="%s"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(text)
    )
    m = pat.search(xml)
    if not m:
        print(f"emu_ui_tap: node '{text}' not found")
        sys.exit(1)
    x = (int(m.group(1)) + int(m.group(3))) // 2
    y = (int(m.group(2)) + int(m.group(4))) // 2
    run(f"adb shell input tap {x} {y}")
    print(f"emu_ui_tap: tapped '{text}' at {x},{y}")


if __name__ == "__main__":
    main()
