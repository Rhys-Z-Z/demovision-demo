# -*- coding: utf-8 -*-
"""ROS 话题与服务监控相关接口"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.config import DEMO_MODE
from app.services.demo.demo_ros import demo_service_list, demo_topic_list

router = APIRouter(prefix="/api", tags=["ros_monitor"])


async def _run_list(cmd: str) -> list:
    """执行 `rostopic list` / `rosservice list`，返回按行分割的字符串列表"""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                cmd, "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            ),
            timeout=10,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return [ln.strip() for ln in out.decode("utf-8", errors="ignore").splitlines() if ln.strip()]
    except asyncio.TimeoutError:
        return []
    except Exception:  # noqa: BLE001
        return []


@router.get("/ros/topics")
async def ros_topics():
    """获取当前 ROS 网络中的所有话题（demo 模式返回模拟列表）"""
    if DEMO_MODE:
        topics = demo_topic_list()
        return {"topics": topics, "count": len(topics)}
    topics = await _run_list("rostopic")
    return {"topics": topics, "count": len(topics)}


@router.get("/ros/services")
async def ros_services():
    """获取当前 ROS 网络中的所有服务（demo 模式返回模拟列表）"""
    if DEMO_MODE:
        services = demo_service_list()
        return {"services": services, "count": len(services)}
    services = await _run_list("rosservice")
    return {"services": services, "count": len(services)}
