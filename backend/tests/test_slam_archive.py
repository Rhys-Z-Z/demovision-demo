# -*- coding: utf-8 -*-
"""SLAM 归档单测（A4，无需硬件/ROS，本地可跑）。

覆盖：
  1) 归档成功：伪造 {DATA_DIR}/{日期}/{sn8}_output_slam + 假 *_stats.txt
     → 调 _finalize → rename 到 {日期}/{SN}/{sn8}_output_slam_{HHMMSS}，
       rel_path / log_rel_path / artifacts_json / 旧绝对路径列全部更新。
  2) 残留预归档：日期根遗留规范名目录 → _pre_archive_stale → 旧目录被归档。
  3) 失败注入：{日期}/{SN} chmod 0o500 → 归档失败 → 任务仍 finished、
     rel_path=运行时位置、warning 日志、审计 result=failed（结束恢复权限）。

运行方式（在 backend 目录下）：
  cd demovision_web_system/backend && python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

# 确保 `import app.*` 可解析（与 test_paths.py 一致，允许从任意目录直接跑本文件）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入 app.* 之前设置数据/数据库根，避免读到真实落盘区
_TMP_ROOT = tempfile.mkdtemp(prefix="demovision_test_archive_")
os.environ.setdefault("DEMOVISION_DATA_DIR", os.path.join(_TMP_ROOT, "data"))
os.environ.setdefault("DEMOVISION_DB_DIR", os.path.join(_TMP_ROOT, "db"))

from sqlalchemy import select  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.database import AsyncSessionLocal, init_db  # noqa: E402
from app.db.models import OperationLog  # noqa: E402
from app.api import slam  # noqa: E402
from app.utils import paths  # noqa: E402


class _FrozenDateTime:
    """冻结 app.utils.paths 模块内 datetime，使归档时间戳（HHMMSS）确定可断言"""

    _fixed = datetime(2026, 9, 10, 14, 35, 0)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed.replace(tzinfo=tz)
        return cls._fixed


# 每个用例独立 SN，避免冻结日期下共享日期目录互相污染
SN_T1 = "VS1111111111"
SN8_T1 = "11111111"
SN_T3 = "VS3333333333"
SN8_T3 = "33333333"
SN8_T2 = "22222222"

_STATS_TEXT = (
    "平均欧式距离 (Mean): 2.5 mm\n"
    "标准差 (Std): 0.5 mm\n"
    "3σ 区间: [-4.0, 4.0] mm\n"
    "合格性判断: 合格\n"
    "有效数据点数: 100\n"
)


async def _seed_slam_session(task_uuid: str, run_dir: str, sn: str) -> None:
    async with AsyncSessionLocal() as session:
        await crud.create_slam_session(session, task_uuid, sn, 10.0, run_dir)


async def _get_slam_session(task_uuid: str):
    async with AsyncSessionLocal() as session:
        return await crud.get_slam_session(session, task_uuid)


async def _get_audit(task_uuid: str):
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(OperationLog).where(OperationLog.task_uuid == task_uuid)
            .order_by(OperationLog.id.desc())
        )).scalars().first()


class TestSlamArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        asyncio.run(init_db())

    def setUp(self) -> None:
        # 冻结路径层时间，保证 archive_slam_name / date_key_of 确定
        self._dt_patcher = mock.patch.object(paths, "datetime", _FrozenDateTime)
        self._dt_patcher.start()
        self.addCleanup(self._dt_patcher.stop)
        # 清空模块级运行态，避免用例间串扰
        slam._tasks.clear()
        slam._processes.clear()
        slam._finalized.clear()

    def _mk_runtime(self, date_key: str, sn8: str) -> str:
        run_dir = os.path.join(DATA_DIR, date_key, f"{sn8}_output_slam")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, f"{sn8}_stats.txt"), "w",
                  encoding="utf-8") as f:
            f.write(_STATS_TEXT)
        with open(os.path.join(run_dir, "run.log"), "w",
                  encoding="utf-8") as f:
            f.write("SLAM 录制完成\n")
        return run_dir

    # ============ 1) 归档成功 ============
    def test_finalize_archives_to_sn_layer(self):
        date_key = paths.date_key_of()
        run_dir = self._mk_runtime(date_key, SN8_T1)
        task_uuid = "11111111-1111-4111-8111-111111111111"
        asyncio.run(_seed_slam_session(task_uuid, run_dir, SN_T1))
        slam._tasks[task_uuid] = {
            "uuid": task_uuid, "sns": [SN_T1], "output_dir": run_dir,
            "date_key": date_key, "duration": 10.0,
        }

        asyncio.run(slam._finalize(task_uuid, source="test"))

        # 运行期规范名目录已搬走
        self.assertFalse(os.path.exists(run_dir))
        # 归档到 {日期}/{SN}/{sn8}_output_slam_{HHMMSS}
        arch_dir = os.path.join(
            DATA_DIR, date_key, SN_T1, f"{SN8_T1}_output_slam_143500")
        self.assertTrue(os.path.isdir(arch_dir))
        self.assertTrue(os.path.isfile(os.path.join(arch_dir, f"{SN8_T1}_stats.txt")))
        self.assertTrue(os.path.isfile(os.path.join(arch_dir, "run.log")))

        # DB 四件套全部更新
        row = asyncio.run(_get_slam_session(task_uuid))
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "finished")
        self.assertEqual(row.rel_path, os.path.relpath(arch_dir, DATA_DIR))
        self.assertEqual(row.date_key, date_key)
        self.assertEqual(row.log_rel_path, os.path.join(row.rel_path, "run.log"))
        self.assertEqual(row.output_dir_path, arch_dir)  # 旧绝对路径列同步更新
        arts = json.loads(row.artifacts_json)
        self.assertIn(f"{SN8_T1}_stats.txt", arts)
        self.assertIn("run.log", arts)
        self.assertTrue(row.is_qualified)

    # ============ 2) 残留预归档 ============
    def test_pre_archive_stale(self):
        date_key = paths.date_key_of()
        date_dir = os.path.join(DATA_DIR, date_key)
        os.makedirs(date_dir, exist_ok=True)
        run_dir = os.path.join(date_dir, f"{SN8_T2}_output_slam")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "run.log"), "w", encoding="utf-8") as f:
            f.write("旧运行残留\n")
        # 预归档前：规范名目录位于日期根（无 SN 层）
        self.assertTrue(os.path.isdir(run_dir))

        asyncio.run(slam._pre_archive_stale(date_dir, SN8_T2))

        self.assertFalse(os.path.exists(run_dir))
        arch_dir = os.path.join(
            date_dir, SN8_T2, f"{SN8_T2}_output_slam_143500")
        self.assertTrue(os.path.isdir(arch_dir))
        self.assertTrue(os.path.isfile(os.path.join(arch_dir, "run.log")))

    # ============ 3) 失败注入 ============
    def test_finalize_failure_keeps_runtime_position(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root 下 chmod 无法模拟权限失败，跳过失败注入")
        date_key = paths.date_key_of()
        run_dir = self._mk_runtime(date_key, SN8_T3)
        task_uuid = "33333333-3333-4333-8333-333333333333"
        asyncio.run(_seed_slam_session(task_uuid, run_dir, SN_T3))
        slam._tasks[task_uuid] = {
            "uuid": task_uuid, "sns": [SN_T3], "output_dir": run_dir,
            "date_key": date_key, "duration": 10.0,
        }
        # 预置 {日期}/{SN} 为只读目录 → shutil.move 抛 PermissionError
        sn_dir = os.path.join(DATA_DIR, date_key, SN_T3)
        os.makedirs(sn_dir, exist_ok=True)
        os.chmod(sn_dir, 0o500)
        self.addCleanup(lambda: os.chmod(sn_dir, 0o755))
        try:
            with mock.patch.object(slam.logger, "warning") as warn:
                asyncio.run(slam._finalize(task_uuid, source="test"))
            self.assertTrue(
                any("归档失败" in str(c) for c in warn.call_args_list),
                f"应输出归档失败 warning: {warn.call_args_list}",
            )
        finally:
            os.chmod(sn_dir, 0o755)  # 结束恢复权限

        # 运行期目录保留（未归档）
        self.assertTrue(os.path.isdir(run_dir))
        row = asyncio.run(_get_slam_session(task_uuid))
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "finished")   # 任务仍 finished（仅归档失败）
        self.assertEqual(row.rel_path, os.path.relpath(run_dir, DATA_DIR))
        self.assertEqual(row.output_dir_path, run_dir)  # 旧绝对路径列保持运行时位置
        # 审计 result=failed
        audit_row = asyncio.run(_get_audit(task_uuid))
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row.action, "finish_slam")
        self.assertEqual(audit_row.result, "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
