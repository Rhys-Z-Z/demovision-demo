# -*- coding: utf-8 -*-
"""安全测试：is_under_data_dir 防目录穿越（§10）。

覆盖：
  - ../ 穿越
  - symlink 指向数据根外部
  - data-evil 相邻目录（前缀误判：/data-evil 不得视为 /data 之下）
  - 数据根自身与之外的绝对路径越权
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class TestIsUnderDataDir(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 整个类共用同一个临时数据根（app.config 只 import 一次，DATA_DIR 为模块级缓存值）
        cls._real_data = os.environ.get("DEMOVISION_DATA_DIR", "")
        cls._tmp = tempfile.mkdtemp(prefix="demovision_test_data_")
        cls._tmp_outer = tempfile.mkdtemp(prefix="demovision_test_outer_")
        os.environ["DEMOVISION_DATA_DIR"] = cls._tmp

        from app.config import DATA_DIR  # 必须在环境变量设置后导入
        from app.utils.paths import is_under_data_dir
        cls.DATA_DIR = DATA_DIR
        # 模块级函数赋为类属性后须经 staticmethod，避免 self 被当作首参
        cls.is_under_data_dir = staticmethod(is_under_data_dir)
        if Path(DATA_DIR).resolve() != Path(cls._tmp).resolve():
            cls.skipTest(cls, "DEMOVISION_DATA_DIR 未被测试目录接管")

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ["DEMOVISION_DATA_DIR"] = cls._real_data

    def _mk(self, rel: str) -> str:
        p = os.path.join(self._tmp, rel)
        os.makedirs(os.path.dirname(p) or self._tmp, exist_ok=True)
        return p

    def test_normal_under(self):
        p = self._mk("2026_Sep/Sep_8/VS1234")
        self.assertTrue(self.is_under_data_dir(p))

    def test_root_itself_rejected(self):
        # 数据根本身不是"之下"的文件，按拒绝处理
        self.assertFalse(self.is_under_data_dir(self._tmp))

    def test_parent_traversal_rejected(self):
        # ../ 穿越：先归一化，realpath 后必然逃逸数据根
        p = self._mk("2026_Sep/Sep_8")
        evil = os.path.join(p, "..", "..", "..", "..", "etc", "passwd")
        self.assertFalse(self.is_under_data_dir(evil))

    def test_adjacent_prefix_rejected(self):
        # 以数据根+后缀命名的相邻目录：不得视为数据根之下（startswith(root+sep) 判定生效）
        evil_root = self._tmp + "_evil"
        os.makedirs(evil_root, exist_ok=True)
        self.assertFalse(self.is_under_data_dir(evil_root))
        self.assertFalse(self.is_under_data_dir(os.path.join(evil_root, "x")))

    def test_absolute_escape_rejected(self):
        self.assertFalse(self.is_under_data_dir(self._tmp_outer))
        self.assertFalse(self.is_under_data_dir(os.path.join(self._tmp_outer, "file.txt")))

    def test_symlink_to_outside_rejected(self):
        # symlink 指向数据根外部：resolve() 后逃逸，必须拒绝
        outside = os.path.join(self._tmp_outer, "secret.txt")
        with open(outside, "w") as f:
            f.write("secret")
        link = self._mk("2026_Sep/Sep_8/link")
        os.symlink(outside, link)
        self.assertFalse(self.is_under_data_dir(link))


if __name__ == "__main__":
    unittest.main(verbosity=2)
