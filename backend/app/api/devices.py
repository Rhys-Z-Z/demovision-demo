# -*- coding: utf-8 -*-
"""设备 SN 列表接口"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter

from app.config import SCRIPT_DIR

router = APIRouter(prefix="/api", tags=["devices"])


def _discover_devices() -> list:
    """在 executor 中调用 ship_out 的 ROS 设备发现逻辑"""
    sys.path.insert(0, str(SCRIPT_DIR))
    from ship_out import ROSInterface  # 依赖 ROS 环境
    return ROSInterface.get_devices()


@router.get("/devices")
async def list_devices():
    loop = asyncio.get_running_loop()
    try:
        devices = await loop.run_in_executor(None, _discover_devices)
        return {"devices": devices, "count": len(devices)}
    except Exception as e:  # noqa: BLE001
        return {"devices": [], "count": 0, "error": str(e)}
