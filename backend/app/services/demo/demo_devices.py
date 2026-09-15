# -*- coding: utf-8 -*-
"""Demo 模拟设备（SN 与设备信息）。

⚠️ 与 scripts/ship_out.py、scripts/slam_plotter_final.py 内的 DEMO_SERIALS 保持同值，
否则检测/SLAM 任务与设备发现页会显示不同设备。
"""
from __future__ import annotations

# 模拟 SN（后 8 位用于目录命名/话题路径，如 /dv_sdk/DVSNDV000001/slam/pose）
DEMO_SERIALS = [
    "DVSNDV000001",
    "DVSNDV000002",
]

# 模拟固件/SDK 版本（喂给 sdk_manager._ingest_version 的正则，供前端展示）
DEMO_SDK_VERSION = "3.2.0-demo(a0985454)"
DEMO_FIRMWARE_VERSION = "V1.04P31||Reed_O_7251|V1.00|demo"

# 模拟 USB 设备标识（/api/imu/devices 返回）
DEMO_USB_DEVICES = [
    "DVSNDV000001",
    "DVSNDV000002",
]


def demo_devices() -> list:
    return list(DEMO_SERIALS)
