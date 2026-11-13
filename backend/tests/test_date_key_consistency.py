# -*- coding: utf-8 -*-
"""一致性测试：date_key_of() 与 ship_out.get_date_dir() 相对部分逐字符一致（R2）。

迁移要点：
  - 旧版模块顶层 os.environ.setdefault(...) 删除——conftest.py 统一裁决，
    DATA_DIR 在任何测试模块 import 前就已指向临时目录。
  - ship_out 不可导入时 skipTest(...) 改为 pytest.skip(...)（可在任何位置
    就地跳过，不依赖 unittest 基类）。
"""
from __future__ import annotations

import os
import sys

import pytest

from app.utils.paths import date_key_of

# scripts/ 加入 sys.path 以便导入 ship_out（demo 模拟器，无 ROS 依赖）
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")


class TestDateKeyConsistency:
    def test_date_key_matches_ship_out(self):
        sys.path.insert(0, _SCRIPTS)
        try:
            from ship_out import DemoVisionDetector  # type: ignore
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"ship_out 不可导入，跳过一致性测试: {e}")

        det = DemoVisionDetector(use_log_terminal=False)
        # 直接用真实系统时间，两者都以 now 计算
        full = det.get_date_dir()
        # 去掉 BASE_DIR 前缀后的相对部分
        rel_part = full.replace(det.config.BASE_DIR + os.sep, "", 1)
        assert date_key_of() == rel_part, (
            f"date_key_of()={date_key_of()} 与 "
            f"ship_out.get_date_dir() 相对部分={rel_part} 不一致"
        )
