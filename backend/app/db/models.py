# -*- coding: utf-8 -*-
"""SQLAlchemy ORM 模型"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Float, Integer, String, Text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OperationLog(Base):
    """操作审计表（§4.2）"""
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    task_uuid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DetectionTask(Base):
    __tablename__ = "detection_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/finished/failed
    device_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # 平动/非平动/测试/头箍式/简易式
    test_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # 仅相机/仅ToF/全功能
    devices_sn: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # SN1,SN2
    result_dir_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    overall_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # PASS/FAIL
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ---- §4.1 新增：rel_path/date_key/log_rel_path/artifacts_json（迁移幂等 ADD） ----
    date_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    log_rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    artifacts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SlamSession(Base):
    __tablename__ = "slam_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sn: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/finished/failed
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output_dir_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    csv_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    png_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    stats_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_qualified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # 3σ区间 ⊆ [-4,4] mm
    mean_dist_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    std_dist_mm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # ---- §4.1 ----
    date_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    log_rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    artifacts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Screenshot(Base):
    """实时图像截图索引（S1）：{DATA_DIR}/{日期}/{SN}/picture/ 下的截图元数据"""
    __tablename__ = "screenshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    sn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    date_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # 相对 DATA_DIR 的 jpg
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ImuCalibTask(Base):
    __tablename__ = "imu_calibration_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sn: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # 设备 SN
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/finished/failed
    result_dir_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    txt_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # imu_calib_*.txt
    bin_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # imu_calib_*.bin
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # gyro_bias_x/y/z 等
    qualified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # 校准是否合格
    # ---- §4.1 ----
    date_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    log_rel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    artifacts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
