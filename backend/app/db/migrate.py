# -*- coding: utf-8 -*-
"""数据库迁移（§4）：幂等 ALTER 加列、建索引、历史行回填、operation_logs 建表。

所有操作先查元数据再执行，每次启动可重复运行；历史行回填逐行 try/except，
失败跳过并记日志，不中断启动（§4.4）。不搬任何历史文件。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from sqlalchemy import text

from app.config import DATA_DIR
from app.db.database import engine
from app.utils.logger import logger
from app.utils.paths import date_key_of

# 三张业务表：旧绝对路径列 → 新 rel 字段
_TABLE_COLUMNS = {
    "detection_tasks": ("result_dir_path", "log_rel_path"),
    "slam_sessions": ("output_dir_path", "log_rel_path"),
    "imu_calibration_tasks": ("result_dir_path", "log_rel_path"),
}
_NEW_COLUMNS = ["date_key", "rel_path", "log_rel_path", "artifacts_json"]


async def _ensure_columns(conn) -> None:
    """幂等 ADD COLUMN（SQLite 无 IF NOT EXISTS for ADD，需先查 PRAGMA）"""
    for table, (abs_col, _log_col) in _TABLE_COLUMNS.items():
        existing = {
            row[1]
            for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        }
        for col in _NEW_COLUMNS:
            if col not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} TEXT"))


async def _ensure_screenshots_table(conn) -> None:
    """S1：screenshots 幂等建表 + 索引（无回填，供截图索引复用）"""
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS screenshots ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts TEXT DEFAULT (datetime('now','localtime')),"
        " sn TEXT, topic TEXT, date_key TEXT, rel_path TEXT, file_size INTEGER)"
    ))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_shot_date ON screenshots(date_key)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_shot_sn ON screenshots(sn)"))


async def _ensure_indexes(conn) -> None:
    """幂等建索引"""
    index_defs = [
        ("idx_det_date", "detection_tasks", "date_key"),
        ("idx_det_time", "detection_tasks", "start_time"),
        ("idx_det_sn", "detection_tasks", "devices_sn"),
        ("idx_slam_date", "slam_sessions", "date_key"),
        ("idx_slam_time", "slam_sessions", "start_time"),
        ("idx_slam_sn", "slam_sessions", "sn"),
        ("idx_imu_date", "imu_calibration_tasks", "date_key"),
        ("idx_imu_time", "imu_calibration_tasks", "start_time"),
        ("idx_imu_sn", "imu_calibration_tasks", "sn"),
    ]
    for idx_name, table, col in index_defs:
        await conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"
        ))


def _rel_from_abs(abs_path: Optional[str]) -> Optional[str]:
    """旧绝对路径以 DATA_DIR 开头 → 截取相对部分；否则 None（旧数据在旧位置，仅走加固后的 /api/files/download）"""
    if not abs_path:
        return None
    p = os.path.normpath(abs_path)
    root = os.path.normpath(DATA_DIR)
    if p == root:
        return ""
    if p.startswith(root + os.sep):
        return p[len(root) + 1:]
    return None


async def _backfill_rows(conn) -> None:
    """历史行回填：rel_path/date_key/artifacts_json/log_rel_path（逐行 try/except）"""
    for table, (abs_col, log_col) in _TABLE_COLUMNS.items():
        rows = (await conn.execute(text(
            f"SELECT id, {abs_col}, start_time FROM {table} WHERE rel_path IS NULL OR date_key IS NULL"
        ))).fetchall()
        for row in rows:
            try:
                rid, abs_path, start_time = row
                rel = _rel_from_abs(abs_path)
                date_key = None
                artifacts = []
                log_rel = None
                if rel is not None and rel != "":
                    # date_key 优先取 rel_path 前两段（{year}_{Month}/{Month}_{day}/...）
                    parts = rel.split(os.sep)
                    if len(parts) >= 2:
                        date_key = f"{parts[0]}/{parts[1]}"
                    # artifacts_json：任务目录存在则列出文件名
                    full = os.path.join(DATA_DIR, rel)
                    if os.path.isdir(full):
                        try:
                            artifacts = sorted(os.listdir(full))
                        except OSError:
                            artifacts = []
                        # log_rel_path：目录下存在 run.log / imu_calib_run.log 才填
                        for logname in ("run.log", "imu_calib_run.log"):
                            if os.path.isfile(os.path.join(full, logname)):
                                log_rel = os.path.join(rel, logname)
                                break
                if date_key is None:
                    # 由 start_time 经 date_key_of() 计算
                    dt = None
                    if start_time:
                        try:
                            dt = datetime.fromisoformat(str(start_time).replace(" ", "T"))
                        except Exception:  # noqa: BLE001
                            dt = None
                    date_key = date_key_of(dt) if dt else date_key_of()
                await conn.execute(text(
                    f"UPDATE {table} SET rel_path=:rel, date_key=:dk, "
                    f"artifacts_json=:arts, {log_col}=:logrel WHERE id=:id"
                ), {
                    "rel": rel, "dk": date_key,
                    "arts": json.dumps(artifacts, ensure_ascii=False),
                    "logrel": log_rel, "id": rid,
                })
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[migrate] 回填 {table} id={row[0]} 失败（跳过）: {e}")


async def run_migrations() -> None:
    """幂等迁移入口（main.py lifespan 调用）"""
    async with engine.begin() as conn:
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _ensure_screenshots_table(conn)
        await _backfill_rows(conn)
    logger.info("数据库迁移完成（幂等，可重复启动）")