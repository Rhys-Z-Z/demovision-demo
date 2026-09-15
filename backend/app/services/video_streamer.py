# -*- coding: utf-8 -*-
"""MJPEG 代理：异步拉取 web_video_server 流，提取 JPEG 帧，Base64 推送 WebSocket"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Optional

from app.config import DEMO_MODE
from app.services.demo.demo_frames import render_frame
from app.websocket.manager import manager

# web_video_server 默认端口（start.sh 会提示用户自行启动）
WEB_VIDEO_SERVER_URL = "http://localhost:8080/stream?topic={topic}"

# JPEG 边界符
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"

# 后端限帧
MAX_FPS = 30

# 缓冲区保护
GARBAGE_LIMIT = 1 * 1024 * 1024      # 1MB：丢弃前导垃圾数据
INCOMPLETE_LIMIT = 10 * 1024 * 1024  # 10MB：清空不完整帧

# 断线重连指数退避（秒，封顶 15s）
BACKOFF_BASE = 1
BACKOFF_MAX = 15


class MJPEGProxy:
    """为单个 WS 客户端拉取指定 topic 的 MJPEG 流并推送视频帧

    生命周期：start_video_stream 消息创建 start()，stop_video_stream 或
    WS 断开时调用 stop()。
    """

    def __init__(self, ws, topic: str, max_fps: int = MAX_FPS) -> None:
        self.ws = ws
        self.topic = topic
        self.url = WEB_VIDEO_SERVER_URL.format(topic=topic)
        self._min_interval = 1.0 / max_fps
        self._last_sent = 0.0
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _send_frame(self, frame: bytes) -> None:
        """限帧 + Base64 编码推送"""
        now = time.monotonic()
        if now - self._last_sent < self._min_interval:
            return  # 丢帧策略：超过帧率上限直接丢弃
        self._last_sent = now
        try:
            await manager.send(self.ws, {
                "type": "video_frame",
                "topic": self.topic,
                "data": base64.b64encode(frame).decode("ascii"),
            })
        except Exception:  # noqa: BLE001
            self.stop()

    async def _run(self) -> None:
        """主循环：连接 → 读流 → 提取帧 → 推送；异常时指数退避重连"""
        if DEMO_MODE:
            await self._run_demo()
            return
        import httpx

        backoff = BACKOFF_BASE
        while not self._stopped.is_set():
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    async with client.stream("GET", self.url) as resp:
                        if resp.status_code != 200:
                            raise ConnectionError(
                                f"web_video_server 返回 {resp.status_code}")
                        buffer = bytearray()
                        async for chunk in resp.aiter_bytes():
                            if self._stopped.is_set():
                                break
                            buffer.extend(chunk)
                            consumed = self._extract_frames(buffer)
                            del buffer[:consumed]
                            backoff = BACKOFF_BASE  # 读到数据即重置退避
                # 流正常结束（服务端断开）
                self._stopped.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 断线重连
                if self._stopped.is_set():
                    break
                await self._stopped.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def _run_demo(self) -> None:
        """Demo 模式：本地渲染模拟帧（demo_frames），结构与真实 video_frame 完全一致"""
        # 兼容 Python 3.8（无 asyncio.to_thread）与 3.9+：统一走线程池执行渲染
        loop = asyncio.get_running_loop()
        while not self._stopped.is_set():
            try:
                frame = await loop.run_in_executor(None, render_frame, self.topic)
                await self._send_frame(frame)
                await self._stopped.wait(0.1)  # ~10fps
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 渲染异常继续重试
                await self._stopped.wait(1.0)

    def _extract_frames(self, buffer: bytearray) -> int:
        """从缓冲提取完整 JPEG 帧并推送；返回已消费字节数"""
        consumed = 0
        while not self._stopped.is_set():
            start = buffer.find(_SOI, consumed)
            if start == -1:
                # 无起点：垃圾数据超过 1MB 直接清空
                if len(buffer) - consumed > GARBAGE_LIMIT:
                    return len(buffer)
                return consumed
            if start > consumed:
                # 丢弃起点前的垃圾
                consumed = start
                continue
            end = buffer.find(_EOI, start + 2)
            if end == -1:
                # 无完整帧：缓存超过 10MB 清空
                if len(buffer) - consumed > INCOMPLETE_LIMIT:
                    return len(buffer)
                return consumed
            frame = bytes(buffer[start:end + 2])
            consumed = end + 2
            # 限帧推送（协程化，避免阻塞读流）
            asyncio.ensure_future(self._send_frame(frame))
        return consumed
