# -*- coding: utf-8 -*-
"""SDK 一键启停控制路由"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.sdk_manager import SDKManager
from app.utils.logger import logger

router = APIRouter(prefix="/api/sdk", tags=["sdk"])

_sdk_manager: SDKManager = SDKManager.get_instance()


@router.get("/status")
async def sdk_status():
    """查询 SDK 运行状态（/dv_sdk 节点是否在线，兼容手动启动）"""
    try:
        return await _sdk_manager.get_status()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[sdk] 查询状态异常: {e}")
        return {"is_running": False, "managed": False}


@router.post("/start")
async def sdk_start():
    """一键启动 SDK（roscore + roslaunch dv_sdk）"""
    try:
        return await _sdk_manager.start_sdk()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[sdk] 启动异常: {e}")
        return {"status": "start_failed", "error": str(e)}


@router.post("/stop")
async def sdk_stop():
    """一键停止 SDK（SIGINT 优雅停止，超时 SIGKILL）"""
    try:
        return await _sdk_manager.stop_sdk()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[sdk] 停止异常: {e}")
        return {"status": "stop_failed", "error": str(e)}
