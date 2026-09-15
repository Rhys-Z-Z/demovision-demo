# -*- coding: utf-8 -*-
"""Demo SDK 假状态机：模拟 dv_sdk 启停与日志流。

与真实 SDKManager 行为一致：
    - start：running=True，后台流式广播 sdk_log 行（含版本行喂 _ingest_version）；
    - stop：running=False；
    - status：is_running / managed / video_server_running / sdk_version / firmware_version。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.services.demo.demo_devices import (DEMO_FIRMWARE_VERSION,
                                            DEMO_SDK_VERSION, DEMO_SERIALS)

_LOG_LINES = [
    "[dv_sdk] node started (demo)",
    f"DemoVision SDK version: {DEMO_SDK_VERSION}",
    f"Device Version: {DEMO_FIRMWARE_VERSION}",
    "[dv_sdk] device online: " + DEMO_SERIALS[0],
    "[dv_sdk] device online: " + DEMO_SERIALS[1],
    "[dv_sdk] SLAM engine ready (demo)",
    "[dv_sdk] image topics published (demo)",
]


class DemoSDK:
    """Demo 模式下 SDK 状态的唯一来源（单例）"""

    _instance: Optional["DemoSDK"] = None

    def __init__(self) -> None:
        self.running = False
        self.sdk_version: str = DEMO_SDK_VERSION
        self.firmware_version: str = DEMO_FIRMWARE_VERSION
        self._log_task: Optional[asyncio.Task] = None
        self._broadcast = None

    @classmethod
    def get_instance(cls) -> "DemoSDK":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_broadcast(self, fn) -> None:
        self._broadcast = fn

    async def start(self) -> dict:
        if self.running:
            return {"status": "already_running"}
        self.running = True
        if self._log_task is None or self._log_task.done():
            self._log_task = asyncio.create_task(self._stream_logs())
        return {"status": "started"}

    async def stop(self) -> dict:
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        self._log_task = None
        self.running = False
        if self._broadcast:
            try:
                await self._broadcast({"type": "sdk_status", "is_running": False})
            except Exception:  # noqa: BLE001
                pass
        return {"status": "stopped"}

    async def _stream_logs(self) -> None:
        for line in _LOG_LINES:
            if not self.running:
                break
            if self._broadcast:
                try:
                    await self._broadcast({"type": "sdk_log", "line": line})
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(0.5)
        if self.running:
            self.running = True  # 保持运行态，日志流播完即止

    def status(self) -> dict:
        return {
            "is_running": self.running,
            "managed": self.running,
            "video_server_running": True,  # demo 图像帧始终可用
            "sdk_version": self.sdk_version,
            "firmware_version": self.firmware_version,
        }
