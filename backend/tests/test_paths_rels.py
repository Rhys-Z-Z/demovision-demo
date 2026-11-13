# -*- coding: utf-8 -*-
"""路径构造函数测试：date_key / rel_path / 归档命名的唯一来源（utils/paths.py）。

为什么值得测：
    这些函数产出的是"落盘目录"与"数据库 rel_path"的唯一来源。它们错了，
    产物会写到错误位置、历史页下载 404、迁移回填报废，且没有任何异常提示。
    纯函数、零 IO、零副作用 —— 测试成本最低、回归收益最高。

覆盖：
    date_key_of         月份英文名映射（Jan/Dec 边界）、指定时间
    detection_rel       单设备进 SN 层 / 多设备落日期根 / SN 缺失兜底
    imu_rel             固定日期根 + uuid8
    picture_rel         SN 层 / 空 SN / 首尾空格
    archive_slam_name   时间戳后缀（HHMMSS）
    abs_of              相对路径解析、绝对路径不得逃逸数据根
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from app.config import DATA_DIR
from app.utils.paths import (abs_of, archive_slam_name, date_key_of,
                             detection_rel, imu_rel, picture_rel)


# ============ date_key_of ============

@pytest.mark.parametrize("dt, expected", [
    (datetime(2026, 1, 5), "2026_Jan/Jan_5"),      # 年初 + 个位数日
    (datetime(2026, 9, 10), "2026_Sep/Sep_10"),    # 项目演示常用日期
    (datetime(2026, 12, 31), "2026_Dec/Dec_31"),   # 年末
], ids=["jan", "sep", "dec"])
def test_date_key_of(dt, expected):
    """date_key 必须与 ship_out.get_date_dir() 的相对部分逐字符一致（另有一致性测试兜底）"""
    assert date_key_of(dt) == expected


def test_date_key_of_defaults_to_now():
    assert date_key_of() == date_key_of(datetime.now())


# ============ detection_rel ============

_DATE_KEY = "2026_Sep/Sep_10"


@pytest.mark.parametrize("devices, expected", [
    # 单设备 → 进 SN 层，目录名含全部 SN 后缀
    (["VS1234567890"],
     f"{_DATE_KEY}/VS1234567890/test_result_34567890_143500"),
    # 多设备 → 落日期根（目录名已含全部 SN，避免在 SN 层下再嵌套）
    (["VS1111111111", "VS2222222222"],
     f"{_DATE_KEY}/test_result_11111111_22222222_143500"),
    # SN 缺失兜底（预期不发生，但必须不崩）
    ([""], f"{_DATE_KEY}/_unknown/test_result__143500"),
], ids=["single", "multi", "missing-sn"])
def test_detection_rel(devices, expected):
    assert detection_rel(_DATE_KEY, devices, "_".join(
        d[-8:] if len(d) >= 8 else d for d in devices), "143500") == expected


def test_detection_rel_is_under_data_root():
    """所有产物路径都必须是可解析到 DATA_DIR 之下的相对路径"""
    rel = detection_rel(_DATE_KEY, ["VS1234567890"], "34567890", "143500")
    assert not os.path.isabs(rel)
    assert Path(DATA_DIR) in abs_of(rel).parents


# ============ imu_rel / picture_rel ============

def test_imu_rel():
    """IMU 无法可靠获取 SN，固定在日期根"""
    assert imu_rel(_DATE_KEY, "abcdef12") == f"{_DATE_KEY}/imu_calib_abcdef12"


@pytest.mark.parametrize("sn, expected", [
    ("VS1234567890", f"{_DATE_KEY}/VS1234567890/picture"),
    ("", f"{_DATE_KEY}/_unknown/picture"),          # SN 缺失
    ("  VS1234567890  ", f"{_DATE_KEY}/VS1234567890/picture"),  # 首尾空格被 strip
], ids=["normal", "empty", "strip"])
def test_picture_rel(sn, expected):
    assert picture_rel(_DATE_KEY, sn) == expected


# ============ archive_slam_name ============

def test_archive_slam_name_with_fixed_time():
    """归档目录名 = {sn8}_output_slam_{HHMMSS}，时间戳保证同日同设备不撞名"""
    assert archive_slam_name("11111111", datetime(2026, 9, 10, 14, 35, 0)) \
        == "11111111_output_slam_143500"


def test_archive_slam_name_defaults_to_now():
    name = archive_slam_name("11111111")
    assert name.startswith("11111111_output_slam_")
    assert len(name.rsplit("_", 1)[-1]) == 6      # HHMMSS 六位


# ============ abs_of ============

def test_abs_of_resolves_under_data_root():
    assert abs_of("2026_Sep/Sep_10/f.txt") == Path(DATA_DIR) / "2026_Sep/Sep_10/f.txt"


def test_abs_of_strips_leading_slash():
    """前导 / 被 lstrip：绝对路径不得借此逃逸数据根"""
    assert abs_of("/etc/passwd") == Path(DATA_DIR) / "etc/passwd"
