# -*- coding: utf-8 -*-
"""Demo SLAM pose 模拟器：每 SN 独立轨迹状态机（Lissajous + 噪声 + 漂移）。

与真实 rospy 回调推送同构：
    on_data({"type": "slam_data", "sn": sn, "t": t, "x": x, "y": y, "z": z, "dist": dist})
单位：x/y/z 为米，t 单调递增（秒）。
"""
from __future__ import annotations

import math
import threading
import time
from typing import Dict, Optional

_DT = 0.2  # 模拟推进间隔（秒），与 slam_ros_node 的 demo 线程节拍一致


class DemoPoseSimulator:
    """为已订阅 SN 生成模拟 SLAM 位姿点"""

    def __init__(self) -> None:
        self._state: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._base = time.monotonic()

    def subscribe(self, sn: str) -> None:
        if not sn:
            return
        with self._lock:
            if sn in self._state:
                return
            # 每台设备独立相位，轨迹互不相同
            seed = sum(ord(c) for c in sn[-8:]) % 10
            self._state[sn] = {
                "t": 0.0,
                "phase": seed * 0.37,
                "x0": (seed % 3 - 1) * 0.05,
                "y0": ((seed // 3) % 3 - 1) * 0.05,
            }

    def unsubscribe(self, sn: str) -> None:
        with self._lock:
            self._state.pop(sn, None)

    def has(self, sn: str) -> bool:
        with self._lock:
            return sn in self._state

    def next_point(self, sn: str, dt: float = _DT) -> Optional[dict]:
        """推进一个采样点；未订阅返回 None。t 严格单调、单位米。"""
        with self._lock:
            st = self._state.get(sn)
            if st is None:
                return None
            st["t"] = round(st["t"] + dt, 4)
            t = st["t"]
            phase = st["phase"]
            x = 0.5 * math.sin(2 * math.pi * 0.20 * t + phase) + 0.02 * t + st["x0"]
            y = 0.5 * math.sin(2 * math.pi * 0.17 * t + phase * 1.7) - 0.015 * t + st["y0"]
            z = 0.02 * math.sin(2 * math.pi * 0.11 * t + phase)
        dist = math.sqrt(x * x + y * y + z * z)
        return {
            "type": "slam_data",
            "sn": sn,
            "t": t,
            "x": round(x, 6),
            "y": round(y, 6),
            "z": round(z, 6),
            "dist": round(dist, 6),
        }
