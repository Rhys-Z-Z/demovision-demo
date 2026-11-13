# -*- coding: utf-8 -*-
"""安全测试：is_under_data_dir 防目录穿越（§10）。

覆盖：
  - ../ 穿越
  - symlink 指向数据根外部
  - data-evil 相邻目录（前缀误判：/data-evil 不得视为 /data 之下）
  - 数据根自身与之外的绝对路径越权

pytest 迁移要点（对照旧 unittest 版）：
  - 旧版 setUpClass 手动接管 DEMOVISION_DATA_DIR + skipTest 兜底，整段删除：
    conftest.py 已统一接管，DATA_DIR 天然指向临时目录，模块级 import 即可。
  - 外部目录改用 pytest 自带 tmp_path fixture（每用例独享、自动清理），
    替代手写 tempfile.mkdtemp。
  - 不再继承 unittest.TestCase，self.assert* 改为裸 assert
    （失败时 pytest 自动回显完整表达式与中间值，诊断信息更强）。
"""
from __future__ import annotations

import os

from app.config import DATA_DIR
from app.utils.paths import is_under_data_dir


def _mk(rel: str) -> str:
    """在数据根下创建 rel 的父目录并返回绝对路径"""
    p = os.path.join(DATA_DIR, rel)
    os.makedirs(os.path.dirname(p) or DATA_DIR, exist_ok=True)
    return p


class TestIsUnderDataDir:
    def test_normal_under(self):
        p = _mk("2026_Sep/Sep_8/VS1234")
        assert is_under_data_dir(p)

    def test_root_itself_rejected(self):
        # 数据根本身不是"之下"的文件，按拒绝处理
        assert not is_under_data_dir(DATA_DIR)

    def test_parent_traversal_rejected(self):
        # ../ 穿越：先归一化，realpath 后必然逃逸数据根
        p = _mk("2026_Sep/Sep_8")
        evil = os.path.join(p, "..", "..", "..", "..", "etc", "passwd")
        assert not is_under_data_dir(evil)

    def test_adjacent_prefix_rejected(self):
        # 字符串前缀相邻目录（{DATA_DIR}_evil）：不得视为数据根之下
        # （startswith(root+sep) 判定生效）
        evil_root = DATA_DIR + "_evil"
        os.makedirs(evil_root, exist_ok=True)
        assert not is_under_data_dir(evil_root)
        assert not is_under_data_dir(os.path.join(evil_root, "x"))

    def test_absolute_escape_rejected(self, tmp_path):
        # tmp_path：pytest 内置 fixture，每个用例独享的临时目录，用后自动清理
        assert not is_under_data_dir(str(tmp_path))
        assert not is_under_data_dir(str(tmp_path / "file.txt"))

    def test_symlink_to_outside_rejected(self, tmp_path):
        # symlink 指向数据根外部：resolve() 后逃逸，必须拒绝
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = _mk("2026_Sep/Sep_8/link")
        os.symlink(str(outside), link)
        assert not is_under_data_dir(link)
