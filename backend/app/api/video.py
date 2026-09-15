# -*- coding: utf-8 -*-
"""实时图像相关接口：扫描 ROS 图像话题"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.config import DEMO_MODE
from app.services.demo.demo_ros import demo_image_topic_list

router = APIRouter(prefix="/api", tags=["video"])


def _scan_image_topics() -> list:
    """扫描 ROS 已发布话题，过滤包含 /image 的话题名"""
    try:
        import rospy
        # get_published_topics 返回 [(name, type), ...]
        topics = rospy.get_published_topics()
        return sorted({name for name, _ in topics if "image" in name})
    except Exception:  # noqa: BLE001 无 ROS/roscore 时返回空列表
        return []


@router.get("/image_topics")
async def image_topics():
    """返回可用的图像话题列表（供实时图像页选择）"""
    if DEMO_MODE:
        topics = demo_image_topic_list()
        return {"topics": topics, "count": len(topics)}
    loop = asyncio.get_running_loop()
    try:
        topics = await loop.run_in_executor(None, _scan_image_topics)
        return {"topics": topics, "count": len(topics)}
    except Exception as e:  # noqa: BLE001
        return {"topics": [], "count": 0, "error": str(e)}
