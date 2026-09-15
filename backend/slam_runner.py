#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLAM 薄启动器（L2 源码保护用极薄入口，非业务逻辑）。

背景：slam_plotter_final.py 被 Cython 编译为 .so 后，无法再以
`python slam_plotter_final.py --duration N` 脚本方式直接运行（.so 无可执行 __main__）。
本文件仅负责：把 scripts 目录加入 sys.path → import 编译后的 slam_plotter_final 模块
→ 原样透传 argv[1:] 并调用其 main()，行为与直接跑脚本完全等价（P3 行为零变化）。

本文件为构建产物中唯一保留的明文 .py（置于 backend/ 根、不在 backend/app 包内，
不参与 Cython 编译，见 build_setup.py 排除说明）。
"""
import os
import sys

# 本文件位于 backend/，scripts/*.so 位于同级 scripts/
_SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
)
sys.path.insert(0, _SCRIPTS_DIR)

import slam_plotter_final  # noqa: E402  编译后的 .so

# argparse.parse_args() 只读 sys.argv[1:]，argv[0] 用什么无关紧要，置回脚本名便于日志
sys.argv = [os.path.join(_SCRIPTS_DIR, "slam_plotter_final")] + sys.argv[1:]
slam_plotter_final.main()