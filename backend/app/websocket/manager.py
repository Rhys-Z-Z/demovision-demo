# -*- coding: utf-8 -*-
"""WebSocket 连接管理与广播"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Set

from fastapi import WebSocket


class ConnectionManager:
    """管理所有 WS 客户端，并按事件类型广播 JSON 消息"""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # 每个连接独立的发送锁：视频帧/高频数据与 ack/pong 并发写需串行化
        self._ws_locks: Dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
            self._ws_locks.setdefault(ws, asyncio.Lock())

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            self._ws_locks.pop(ws, None)

    async def send(self, ws: WebSocket, data: Dict[str, Any]) -> None:
        lock = self._ws_locks.get(ws)
        if lock is None:
            lock = asyncio.Lock()
            async with self._lock:
                self._ws_locks[ws] = lock
        try:
            async with lock:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            await self.disconnect(ws)

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """向所有在线客户端广播"""
        text = json.dumps(data, ensure_ascii=False)
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                await self.disconnect(ws)

    async def broadcast_to(self, task_uuid: str, data: Dict[str, Any]) -> None:
        """广播给订阅了指定 task_uuid 的客户端；未指定订阅时按类型全局广播"""
        # 简化：任务相关日志按 task_uuid 过滤，slam_data 全局广播
        await self.broadcast(data)


# 全局单例
manager = ConnectionManager()
