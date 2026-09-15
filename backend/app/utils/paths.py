# -*- coding: utf-8 -*-
"""统一路径层：date_key / 相对路径 / 归档命名的唯一来源（T1）

设计约束（见 expand_design_7）：
    - date_key 格式与 ship_out.get_date_dir() 的相对部分完全一致（R2）。
      get_date_dir() 不支持传时间，故此处复制其格式串，并在注释中指向源函数；
      一致性测试 tests/test_date_key_consistency.py 保证二者逐字符一致。
    - 代码零绝对路径（R4）：一切落盘路径由 DATA_DIR/rel_path 推导。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import DATA_DIR


def date_key_of(dt: Optional[datetime] = None) -> str:
    """日期键，格式与 ship_out.get_date_dir() 的相对部分逐字符一致。

    源函数：scripts/ship_out.py :: DemoVisionDetector.get_date_dir()
        返回绝对路径 f"{BASE_DIR}/{now.year}_{month_en}/{month_en}_{now.day}"
    此处仅截取其相对目录部分（去掉 BASE_DIR 前缀，即相对 DATA_DIR 的部分）。
    date_key 不含日期目录之外的多余分隔，供 abs_of(date_key, ...) 与模块内索引复用。
    """
    now = dt or datetime.now()
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_en = months[now.month]
    return f"{now.year}_{month_en}/{month_en}_{now.day}"


def abs_of(rel_path: str) -> Path:
    """将相对 DATA_DIR 的 rel_path 解析为绝对路径。"""
    return Path(DATA_DIR) / rel_path.lstrip("/")


def detection_rel(date_key: str, devices: List[str], suffix: str, hhmmss: str) -> str:
    """检测任务相对路径（A1：一运行一目录，时间戳保证同日复测不撞名）：
    - 单设备 → {date_key}/{sn}/test_result_{suffix}_{hhmmss}（SN 层）
    - 多设备 → {date_key}/test_result_{suffix}_{hhmmss}（日期根，目录名已含全部 SN）
    - SN 缺失 → {date_key}/_unknown/test_result_{suffix}_{hhmmss}（兜底，预期不发生）
    """
    leaf = f"test_result_{suffix}_{hhmmss}"
    if len(devices) == 1:
        sn = devices[0]
        if not sn:
            return f"{date_key}/_unknown/{leaf}"
        return f"{date_key}/{sn}/{leaf}"
    return f"{date_key}/{leaf}"


def imu_rel(date_key: str, uuid8: str) -> str:
    """IMU 任务相对路径：{date_key}/imu_calib_{uuid8}（IMU 无法可靠获取 SN，固定在日期根，R3/目标1）"""
    return f"{date_key}/imu_calib_{uuid8}"


def picture_rel(date_key: str, sn: str) -> str:
    """截图相对路径：{date_key}/{sn}/picture（截图属设备数据进 SN 层；SN 缺失兜底 _unknown/picture）"""
    sn = (sn or "").strip()
    if not sn:
        return f"{date_key}/_unknown/picture"
    return f"{date_key}/{sn}/picture"


def archive_slam_name(sn8: str, t: Optional[datetime] = None) -> str:
    """SLAM 归档目录名：{sn8}_output_slam_{HHMMSS}（时间戳保证同日同设备无碰撞）"""
    t = t or datetime.now()
    return f"{sn8}_output_slam_{t:%H%M%S}"


def is_under_data_dir(p: Path) -> bool:
    """rePath 后必须位于 DATA_DIR + os.sep 前缀之下（防目录穿越，R5）。

    同时拒绝指向 DATA_DIR 自身（is_under 语义为"之下"，不含根本身）。
    """
    try:
        real = Path(p).resolve()
        root = Path(DATA_DIR).resolve()
    except OSError:
        return False
    if real == root:
        # 根目录本身不算"下的文件"，按拒绝处理
        return False
    return str(real).startswith(str(root) + os.sep)