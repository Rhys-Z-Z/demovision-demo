#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键跑全量单测（推荐入口）。

每个测试模块在**独立子进程**中运行：各模块在导入 app.config 前设置各自的
环境变量（DATA_DIR / DB_DIR / DEMO_MODE），而 app.config 是进程级缓存，
同一进程内共享会导致模块间互相污染（如 test_paths 被跳过、归档断言串扰）。
按模块隔离后全部用例可稳定通过。

用法（backend 目录下）：
    python3 tests/run_all.py
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

modules = sorted(
    os.path.splitext(os.path.basename(p))[0]
    for p in glob.glob(os.path.join(HERE, "test_*.py"))
)

failed = []
for m in modules:
    print(f"\n===== {m} =====", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "unittest", f"tests.{m}", "-v"],
        cwd=BACKEND,
    )
    if r.returncode != 0:
        failed.append(m)

print()
if failed:
    print(f"FAILED: {', '.join(failed)}")
    sys.exit(1)
print(f"ALL PASSED（{len(modules)} 个模块）")
