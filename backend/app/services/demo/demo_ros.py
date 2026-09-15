# -*- coding: utf-8 -*-
"""Demo ROS 模拟：话题/服务列表 + echo/hz/service 行生成器。

消息结构与真实 rostopic/rosservice 输出一致（前端 ROS 终端页按行渲染）。
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime
from typing import AsyncIterator

from app.services.demo.demo_devices import DEMO_SERIALS


def _sn_topics(sn: str) -> list:
    return [
        f"/dv_sdk/{sn}/slam/pose",
        f"/dv_sdk/{sn}/slam/image",
        f"/dv_sdk/{sn}/color/image",
        f"/dv_sdk/{sn}/fisheye/image",
        f"/dv_sdk/{sn}/tof/image",
        f"/dv_sdk/{sn}/imu",
    ]


def demo_topic_list() -> list:
    """模拟 `rostopic list` 输出"""
    topics = ["/rosout", "/rosout_agg", "/clock"]
    for sn in DEMO_SERIALS:
        topics.extend(_sn_topics(sn))
    return sorted(topics)


def demo_image_topic_list() -> list:
    """模拟 rospy.get_published_topics 中图像话题"""
    names = []
    for sn in DEMO_SERIALS:
        names.extend(t for t in _sn_topics(sn) if "image" in t)
    return sorted(names)


def demo_service_list() -> list:
    """模拟 `rosservice list` 输出"""
    services = ["/rosout/get_loggers", "/rosout/set_logger_level"]
    for sn in DEMO_SERIALS:
        services.append(f"/dv_sdk/{sn}/get_version")
        services.append(f"/dv_sdk/{sn}/reset")
    return sorted(services)


def _fake_pose(sn: str, k: int) -> dict:
    t = k * 0.2
    return {
        "poseMsg": {
            "header": {
                "seq": k,
                "stamp": {"secs": int(datetime.now().timestamp()), "nsecs": k * 200_000_000},
                "frame_id": "odom",
            },
            "pose": {
                "position": {
                    "x": round(0.5 * math.sin(2 * math.pi * 0.2 * t), 6),
                    "y": round(0.5 * math.sin(2 * math.pi * 0.17 * t), 6),
                    "z": round(0.02 * math.sin(2 * math.pi * 0.11 * t), 6),
                },
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
        },
        "confidence": 0.98,
        "topic": f"/dv_sdk/{sn}/slam/pose",
    }


async def demo_echo_stream(topic: str) -> AsyncIterator[str]:
    """模拟 `rostopic echo <topic>` 行流（每 ~0.6s 一行 JSON）"""
    k = 0
    while True:
        sn = next((s for s in DEMO_SERIALS if s in topic), DEMO_SERIALS[0])
        if "slam/pose" in topic or "imu" in topic:
            payload = _fake_pose(sn, k) if "slam/pose" in topic else {
                "header": {"seq": k, "stamp": datetime.now().isoformat()},
                "gyro": [0.0012, -0.0008, 0.0003],
                "accel": [0.01, -0.02, 9.81],
            }
        else:
            payload = {
                "header": {"seq": k, "stamp": datetime.now().isoformat()},
                "width": 640, "height": 360,
                "encoding": "bgr8",
                "data": f"<demo frame {k}>",
            }
        yield json.dumps(payload, ensure_ascii=False)
        k += 1
        await asyncio.sleep(0.6)


async def demo_hz_stream(topic: str) -> AsyncIterator[str]:
    """模拟 `rostopic hz <topic>` 行流（average rate 行，供前端解析 rate）"""
    k = 0
    while True:
        base = 30.0 if "image" in topic else 5.0
        rate = round(base + 0.4 * math.sin(k * 0.7) + 0.05 * (k % 5), 3)
        yield (f"subscribed to [{topic}]\n"
               f"average rate: {rate}\n"
               f"\tmin: {rate - 0.1:.3f}s max: {rate + 0.2:.3f}s std dev: 0.051s window: {k + 1} samples")
        k += 1
        await asyncio.sleep(1.0)


async def demo_service_stream(service: str) -> AsyncIterator[str]:
    """模拟 `rosservice call <service>` 响应行（两条后结束）"""
    yield f"calling service [{service}]"
    yield "success: True"
    yield json.dumps({
        "version": "3.2.0-demo(a0985454)",
        "firmware": "V1.04P31||Reed_O_7251|V1.00|demo",
        "status": "ok",
    }, ensure_ascii=False)
    yield "--- 调用完成 ---"
