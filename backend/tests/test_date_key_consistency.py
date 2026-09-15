# -*- coding: utf-8 -*-
"""一致性测试：date_key_of() 与 ship_out.get_date_dir() 相对部分逐字符一致（R2）。

若 ship_out 不可导入（依赖 ROS 环境等），跳过并告警，不阻断。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime

# 预置数据根，避免污染：每次进程独立临时目录（不能写死固定路径——
# 否则与后导入的 test_slam_archive 共享同一 DATA_DIR，跨进程残留会让归档断言不稳定）
os.environ.setdefault(
    "DEMOVISION_DATA_DIR", tempfile.mkdtemp(prefix="demovision_test_consistency_"))


class TestDateKeyConsistency(unittest.TestCase):
    def test_date_key_matches_ship_out(self):
        from app.config import DATA_DIR
        from app.utils.paths import date_key_of

        # 尝试导入 ship_out（可能依赖 ROS/环境）
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
        try:
            from ship_out import DemoVisionDetector  # type: ignore
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"ship_out 不可导入，跳过一致性测试: {e}")

        det = DemoVisionDetector(use_log_terminal=False)
        # 直接用真实系统时间，两者都以 now 计算
        full = det.get_date_dir()
        # 去掉 BASE_DIR 前缀后的相对部分
        rel_part = full.replace(det.config.BASE_DIR + os.sep, "", 1)
        key = date_key_of()
        self.assertEqual(
            key, rel_part,
            f"date_key_of()={key} 与 ship_out.get_date_dir() 相对部分={rel_part} 不一致",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)