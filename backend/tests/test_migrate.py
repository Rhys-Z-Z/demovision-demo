# -*- coding: utf-8 -*-
"""启动迁移测试：幂等加列 / 建索引 / 历史行回填（db/migrate.py）。

为什么值得测：
    迁移是唯一直接改生产库结构的代码，也是最容易"只跑一次就再也不会被
    测到"的代码。上线后升级老库时它出错 = 启动失败或历史记录丢字段。
    这里用 sqlite 造一份"旧结构库"（缺 date_key/rel_path/artifacts_json），
    跑迁移后逐项断言：列补上了、旧绝对路径回填成 rel、date_key 能从前两段
    推出、artifacts 来自真实目录、跨 DATA_DIR 的旧路径保持 NULL。

做法：monkeypatch 模块级 engine 指向临时库，不影响会话共享库。
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import DATA_DIR
from app.db import migrate

# 旧版三张表：只有绝对路径列，没有 date_key / rel_path / log_rel_path / artifacts_json
_LEGACY_DDL = """
CREATE TABLE detection_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_uuid TEXT, start_time TEXT, end_time TEXT, status TEXT,
  device_type TEXT, test_mode TEXT, devices_sn TEXT,
  result_dir_path TEXT, overall_status TEXT, summary_json TEXT
);
CREATE TABLE slam_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_uuid TEXT, sn TEXT, start_time TEXT, end_time TEXT, status TEXT,
  duration_sec REAL, output_dir_path TEXT, csv_file_path TEXT,
  png_file_path TEXT, stats_text TEXT, is_qualified INTEGER,
  mean_dist_mm REAL, std_dist_mm REAL
);
CREATE TABLE imu_calibration_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_uuid TEXT, sn TEXT, start_time TEXT, end_time TEXT, status TEXT,
  result_dir_path TEXT, txt_file_path TEXT, bin_file_path TEXT,
  summary_json TEXT, qualified INTEGER
);
"""

_NEW_COLUMNS = {"date_key", "rel_path", "log_rel_path", "artifacts_json"}


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """造旧结构库并把 migrate.engine 指向它（用例后自动还原）"""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_LEGACY_DDL)
    conn.commit()
    conn.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(migrate, "engine", engine)
    yield str(db_path)
    asyncio.run(engine.dispose())


def _exec(db: str, sql: str, params=()) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _query(db: str, sql: str) -> list:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _columns(db: str, table: str) -> set[str]:
    return {row[1] for row in _query(db, f"PRAGMA table_info({table})")}


class TestEnsureSchema:
    def test_adds_missing_columns_idempotently(self, legacy_db):
        """三张表都补齐新列；重复执行不报错（启动可能多次）"""
        asyncio.run(migrate.run_migrations())
        asyncio.run(migrate.run_migrations())   # 幂等：第二次不得抛异常

        for table in ("detection_tasks", "slam_sessions", "imu_calibration_tasks"):
            assert _NEW_COLUMNS.issubset(_columns(legacy_db, table)), table

    def test_creates_screenshots_table_and_indexes(self, legacy_db):
        asyncio.run(migrate.run_migrations())

        shot_cols = _columns(legacy_db, "screenshots")
        assert {"ts", "sn", "topic", "date_key", "rel_path", "file_size"} <= shot_cols

        indexes = {r[0] for r in _query(
            legacy_db, "SELECT name FROM sqlite_master WHERE type='index'")}
        for name in ("idx_det_date", "idx_slam_sn", "idx_imu_time",
                     "idx_shot_date", "idx_shot_sn"):
            assert name in indexes


class TestBackfill:
    def test_backfill_from_data_dir(self, legacy_db):
        """旧绝对路径在 DATA_DIR 下 → rel_path/date_key/artifacts/log_rel 全部回填"""
        rel = "2019_Mar/Mar_3/VS9000000020/test_result_00000020_143500"
        full = os.path.join(DATA_DIR, rel)
        os.makedirs(full, exist_ok=True)
        for name in ("a.txt", "run.log"):
            with open(os.path.join(full, name), "w", encoding="utf-8") as f:
                f.write("x")
        _exec(legacy_db,
              "INSERT INTO detection_tasks (task_uuid, start_time, result_dir_path) "
              "VALUES (?, ?, ?)",
              ("mig-d1", "2019-03-03 10:00:00", full))

        asyncio.run(migrate.run_migrations())

        row = _query(legacy_db,
                     "SELECT rel_path, date_key, artifacts_json, log_rel_path "
                     "FROM detection_tasks WHERE task_uuid='mig-d1'")[0]
        assert row[0] == rel
        assert row[1] == "2019_Mar/Mar_3"          # rel 前两段
        assert json.loads(row[2]) == ["a.txt", "run.log"]
        assert row[3] == os.path.join(rel, "run.log")

    def test_log_rel_path_only_when_log_exists(self, legacy_db):
        """目录里没有 run.log → log_rel_path 保持 NULL（不得瞎填）"""
        rel = "2019_Mar/Mar_3/VS9000000021/test_result_00000021_143500"
        full = os.path.join(DATA_DIR, rel)
        os.makedirs(full, exist_ok=True)
        _exec(legacy_db,
              "INSERT INTO slam_sessions (task_uuid, sn, start_time, output_dir_path) "
              "VALUES (?, ?, ?, ?)",
              ("mig-s1", "VS9000000021", "2019-03-03 11:00:00", full))

        asyncio.run(migrate.run_migrations())

        row = _query(legacy_db,
                     "SELECT rel_path, log_rel_path FROM slam_sessions "
                     "WHERE task_uuid='mig-s1'")[0]
        assert row[0] == rel
        assert row[1] is None

    def test_legacy_path_outside_data_dir_keeps_rel_null(self, legacy_db):
        """旧数据在旧位置（DATA_DIR 之外）→ rel_path=NULL，date_key 由 start_time 推出"""
        _exec(legacy_db,
              "INSERT INTO imu_calibration_tasks (task_uuid, start_time, result_dir_path) "
              "VALUES (?, ?, ?)",
              ("mig-i1", "2019-03-04 09:30:00", "/var/old_location/imu_calib_x"))

        asyncio.run(migrate.run_migrations())

        rel_path, date_key = _query(
            legacy_db,
            "SELECT rel_path, date_key FROM imu_calibration_tasks "
            "WHERE task_uuid='mig-i1'")[0]
        assert rel_path is None                      # 不搬文件，不伪造相对路径
        assert date_key == "2019_Mar/Mar_4"          # 由 start_time 计算

    def test_invalid_start_time_falls_back_to_now(self, legacy_db):
        """start_time 非法/缺失 → date_key 走 now 兜底，迁移不中断"""
        _exec(legacy_db,
              "INSERT INTO detection_tasks (task_uuid, start_time, result_dir_path) "
              "VALUES (?, ?, ?)",
              ("mig-d2", None, "/var/old_location/x"))

        asyncio.run(migrate.run_migrations())

        date_key = _query(legacy_db,
                          "SELECT date_key FROM detection_tasks "
                          "WHERE task_uuid='mig-d2'")[0][0]
        assert date_key and "/" in date_key         # 形如 2026_Nov/Nov_13
