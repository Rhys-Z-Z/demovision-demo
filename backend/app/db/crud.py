# -*- coding: utf-8 -*-
"""数据库增删改查"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (DetectionTask, ImuCalibTask, OperationLog,
                           Screenshot, SlamSession)


def _date_input(s: Optional[str]) -> Optional[datetime]:
    """'YYYY-MM-DD' → datetime；非法输入返回 None（调用方忽略该筛选条件）"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


# ============ 操作审计 ============
async def list_operation_logs(session: AsyncSession, page: int = 1,
                              size: int = 20, action: str = None,
                              kind: str = None, date_from: str = None,
                              date_to: str = None) -> tuple[List[OperationLog], int]:
    filters = []
    if action:
        filters.append(OperationLog.action == action)
    if kind:
        filters.append(OperationLog.kind == kind)
    if date_from:
        filters.append(OperationLog.ts >= date_from + " 00:00:00")
    if date_to:
        filters.append(OperationLog.ts <= date_to + " 23:59:59")
    total = (await session.execute(
        select(func.count()).select_from(OperationLog).where(*filters)
    )).scalar() or 0
    rows = (await session.execute(
        select(OperationLog).where(*filters)
        .order_by(OperationLog.id.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return list(rows), int(total)


# ============ 实时截图 ============
async def create_screenshot(session: AsyncSession, sn: str = None,
                            topic: str = None, date_key: str = None,
                            rel_path: str = None,
                            file_size: int = None) -> Screenshot:
    """登记一条截图索引（S1）"""
    shot = Screenshot(
        sn=sn, topic=topic, date_key=date_key,
        rel_path=rel_path, file_size=file_size,
    )
    session.add(shot)
    await session.commit()
    await session.refresh(shot)
    return shot


async def list_screenshots(session: AsyncSession, page: int = 1, size: int = 20,
                           date_from: str = None, date_to: str = None,
                           sn: str = None) -> tuple[List[Screenshot], int]:
    """分页 + 筛选（按 ts 而非 date_key 字符串，坑 #19 同理）"""
    filters = []
    if date_from:
        filters.append(Screenshot.ts >= _date_input(date_from))
    if date_to:
        filters.append(Screenshot.ts < _date_input(date_to) + timedelta(days=1))
    if sn:
        filters.append(Screenshot.sn.contains(sn))
    total = (await session.execute(
        select(func.count()).select_from(Screenshot).where(*filters)
    )).scalar() or 0
    rows = (await session.execute(
        select(Screenshot).where(*filters)
        .order_by(Screenshot.id.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return list(rows), int(total)


async def get_screenshot(session: AsyncSession,
                         shot_id: int) -> Optional[Screenshot]:
    return (await session.execute(
        select(Screenshot).where(Screenshot.id == shot_id)
    )).scalar_one_or_none()


# ============ 检测任务 ============
async def create_detection_task(session: AsyncSession, task_uuid: str,
                                device_type: str, test_mode: str,
                                devices_sn: str) -> DetectionTask:
    task = DetectionTask(
        task_uuid=task_uuid,
        start_time=datetime.now(),
        device_type=device_type,
        test_mode=test_mode,
        devices_sn=devices_sn,
        status="running",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def finish_detection_task(session: AsyncSession, task_uuid: str,
                                result_dir_path: str, overall_status: str,
                                summary: dict, failed: bool = False,
                                rel_path: str = None, date_key: str = None,
                                log_rel_path: str = None,
                                artifacts: list = None) -> None:
    task = (await session.execute(
        select(DetectionTask).where(DetectionTask.task_uuid == task_uuid)
    )).scalar_one_or_none()
    if task is None:
        return
    task.end_time = datetime.now()
    task.status = "failed" if failed else "finished"
    task.result_dir_path = result_dir_path
    task.overall_status = overall_status
    task.summary_json = json.dumps(summary, ensure_ascii=False)
    # §4.1 新字段
    if rel_path is not None:
        task.rel_path = rel_path
    if date_key is not None:
        task.date_key = date_key
    if log_rel_path is not None:
        task.log_rel_path = log_rel_path
    if artifacts is not None:
        task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    await session.commit()


async def get_detection_task(session: AsyncSession, task_uuid: str) -> Optional[DetectionTask]:
    return (await session.execute(
        select(DetectionTask).where(DetectionTask.task_uuid == task_uuid)
    )).scalar_one_or_none()


async def list_detection_tasks(session: AsyncSession, page: int = 1,
                               size: int = 20, date_from: str = None,
                               date_to: str = None, sn: str = None,
                               status: str = None) -> tuple[List[DetectionTask], int]:
    filters = []
    if date_from:
        filters.append(DetectionTask.start_time >= _date_input(date_from))
    if date_to:
        filters.append(DetectionTask.start_time < _date_input(date_to) + timedelta(days=1))
    if sn:
        filters.append(DetectionTask.devices_sn.contains(sn))
    if status:
        filters.append(DetectionTask.status == status)
    total = (await session.execute(
        select(func.count()).select_from(DetectionTask).where(*filters)
    )).scalar() or 0
    rows = (await session.execute(
        select(DetectionTask).where(*filters)
        .order_by(DetectionTask.id.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return list(rows), int(total)


# ============ SLAM 会话 ============
async def create_slam_session(session: AsyncSession, task_uuid: str, sn: str,
                              duration_sec: float, output_dir_path: str) -> SlamSession:
    sess = SlamSession(
        task_uuid=task_uuid,
        sn=sn,
        start_time=datetime.now(),
        status="running",
        duration_sec=duration_sec,
        output_dir_path=output_dir_path,
    )
    session.add(sess)
    await session.commit()
    await session.refresh(sess)
    return sess


async def get_slam_session(session: AsyncSession, task_uuid: str) -> Optional[SlamSession]:
    return (await session.execute(
        select(SlamSession).where(SlamSession.task_uuid == task_uuid)
    )).scalar_one_or_none()


async def finish_slam_session(session: AsyncSession, task_uuid: str,
                              csv_path: str = "", png_path: str = "",
                              stats_text: str = "", is_qualified: bool = None,
                              mean_mm: float = None, std_mm: float = None,
                              failed: bool = False,
                              rel_path: str = None, date_key: str = None,
                              log_rel_path: str = None,
                              artifacts: list = None,
                              output_dir_path: str = None) -> None:
    sess = await get_slam_session(session, task_uuid)
    if sess is None:
        return
    sess.end_time = datetime.now()
    sess.status = "failed" if failed else "finished"
    if output_dir_path is not None:
        # 旧绝对路径列同步更新为归档后新路径（T5：归档 rename 后 DB 不残留失效绝对路径）
        sess.output_dir_path = output_dir_path
    if csv_path:
        sess.csv_file_path = csv_path
    if png_path:
        sess.png_file_path = png_path
    if stats_text:
        sess.stats_text = stats_text
    if is_qualified is not None:
        sess.is_qualified = is_qualified
    if mean_mm is not None:
        sess.mean_dist_mm = mean_mm
    if std_mm is not None:
        sess.std_dist_mm = std_mm
    # §4.1 新字段
    if rel_path is not None:
        sess.rel_path = rel_path
    if date_key is not None:
        sess.date_key = date_key
    if log_rel_path is not None:
        sess.log_rel_path = log_rel_path
    if artifacts is not None:
        sess.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    await session.commit()


async def list_slam_sessions(session: AsyncSession, page: int = 1,
                             size: int = 20, date_from: str = None,
                             date_to: str = None, sn: str = None,
                             status: str = None,
                             qualified: str = None) -> tuple[List[SlamSession], int]:
    filters = []
    if date_from:
        filters.append(SlamSession.start_time >= _date_input(date_from))
    if date_to:
        filters.append(SlamSession.start_time < _date_input(date_to) + timedelta(days=1))
    if sn:
        filters.append(SlamSession.sn.contains(sn))
    if status:
        filters.append(SlamSession.status == status)
    if qualified in ("true", "1"):
        filters.append(SlamSession.is_qualified.is_(True))
    elif qualified in ("false", "0"):
        filters.append(SlamSession.is_qualified.is_(False))
    total = (await session.execute(
        select(func.count()).select_from(SlamSession).where(*filters)
    )).scalar() or 0
    rows = (await session.execute(
        select(SlamSession).where(*filters)
        .order_by(SlamSession.id.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return list(rows), int(total)


# ============ IMU 校准任务 ============
async def create_imu_calib_task(session: AsyncSession, task_uuid: str,
                                sn: Optional[str] = None) -> ImuCalibTask:
    task = ImuCalibTask(
        task_uuid=task_uuid,
        sn=sn or None,
        start_time=datetime.now(),
        status="running",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_imu_calib_task(session: AsyncSession, task_uuid: str) -> Optional[ImuCalibTask]:
    return (await session.execute(
        select(ImuCalibTask).where(ImuCalibTask.task_uuid == task_uuid)
    )).scalar_one_or_none()


async def finish_imu_calib_task(session: AsyncSession, task_uuid: str,
                                result_dir_path: str, txt_path: str = "",
                                bin_path: str = "", summary: dict = None,
                                qualified: bool = None, failed: bool = False,
                                rel_path: str = None, date_key: str = None,
                                log_rel_path: str = None,
                                artifacts: list = None) -> None:
    task = await get_imu_calib_task(session, task_uuid)
    if task is None:
        return
    task.end_time = datetime.now()
    task.status = "failed" if failed else "finished"
    task.result_dir_path = result_dir_path
    if txt_path:
        task.txt_file_path = txt_path
    if bin_path:
        task.bin_file_path = bin_path
    if summary:
        task.summary_json = json.dumps(summary, ensure_ascii=False)
    if qualified is not None:
        task.qualified = qualified
    # §4.1 新字段
    if rel_path is not None:
        task.rel_path = rel_path
    if date_key is not None:
        task.date_key = date_key
    if log_rel_path is not None:
        task.log_rel_path = log_rel_path
    if artifacts is not None:
        task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    await session.commit()


async def list_imu_calib_tasks(session: AsyncSession, page: int = 1,
                               size: int = 20, date_from: str = None,
                               date_to: str = None, sn: str = None,
                               status: str = None,
                               qualified: str = None) -> tuple[List[ImuCalibTask], int]:
    filters = []
    if date_from:
        filters.append(ImuCalibTask.start_time >= _date_input(date_from))
    if date_to:
        filters.append(ImuCalibTask.start_time < _date_input(date_to) + timedelta(days=1))
    if sn:
        filters.append(ImuCalibTask.sn.contains(sn))
    if status:
        filters.append(ImuCalibTask.status == status)
    if qualified in ("true", "1"):
        filters.append(ImuCalibTask.qualified.is_(True))
    elif qualified in ("false", "0"):
        filters.append(ImuCalibTask.qualified.is_(False))
    total = (await session.execute(
        select(func.count()).select_from(ImuCalibTask).where(*filters)
    )).scalar() or 0
    rows = (await session.execute(
        select(ImuCalibTask).where(*filters)
        .order_by(ImuCalibTask.id.desc())
        .offset((page - 1) * size).limit(size)
    )).scalars().all()
    return list(rows), int(total)
