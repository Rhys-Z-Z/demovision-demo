# -*- coding: utf-8 -*-
"""通用 ROS 话题监控：rostopic echo / hz 子进程管理，实时推送 WebSocket"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Optional

from app.config import DEMO_MODE
from app.services.demo import demo_ros
from app.websocket.manager import manager

_RATE_RE = re.compile(r"average rate:\s*([\d.]+)")

# rostopic 输出到管道时块缓冲，readline 收不到实时数据；
# 用 stdbuf -oL 强制行缓冲（实测 PYTHONUNBUFFERED 对 rostopic 无效）
ROSTOPIC_PREFIX = ("stdbuf", "-oL")


def _subprocess_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return env


class ROSTopicMonitor:
    """管理与单个 WebSocket 连接绑定的 rostopic 子进程

    - start_echo: 启动 `rostopic echo <topic>`，逐行推送 echo_data
    - start_hz:   启动 `rostopic hz <topic>`，解析 average rate 推送 hz_data
    - stop_*/cleanup: terminate 子进程并等待回收，防止孤儿进程
    """

    def __init__(self, ws) -> None:
        self.ws = ws
        self.echo_process: Optional[asyncio.subprocess.Process] = None
        self.hz_process: Optional[asyncio.subprocess.Process] = None
        self.service_process: Optional[asyncio.subprocess.Process] = None
        self._echo_task: Optional[asyncio.Task] = None
        self._hz_task: Optional[asyncio.Task] = None
        self._service_task: Optional[asyncio.Task] = None

    # ---------- Echo ----------
    async def start_echo(self, topic: str) -> None:
        await self.stop_echo()  # 确保旧的已停止
        if DEMO_MODE:
            self._echo_task = asyncio.ensure_future(
                self._demo_echo_stream(topic))
            return
        self.echo_process = await asyncio.create_subprocess_exec(
            *ROSTOPIC_PREFIX, "rostopic", "echo", topic,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subprocess_env(),
        )
        self._echo_task = asyncio.ensure_future(self._read_echo_stream())

    async def _read_echo_stream(self) -> None:
        while self.echo_process and self.echo_process.returncode is None:
            try:
                line = await self.echo_process.stdout.readline()
            except Exception:  # noqa: BLE001
                break
            if line:
                msg = {
                    "type": "echo_data",
                    "line": line.decode("utf-8", errors="ignore").rstrip("\n"),
                }
                try:
                    await manager.send(self.ws, msg)
                except Exception:  # noqa: BLE001
                    break
            else:
                break

    async def stop_echo(self) -> None:
        if self._echo_task is not None:
            self._echo_task.cancel()
            self._echo_task = None
        if self.echo_process and self.echo_process.returncode is None:
            try:
                self.echo_process.terminate()
                await asyncio.wait_for(self.echo_process.wait(), timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self.echo_process.kill()
                    await self.echo_process.wait()
                except Exception:  # noqa: BLE001
                    pass
        self.echo_process = None

    # ---------- Hz ----------
    async def start_hz(self, topic: str) -> None:
        await self.stop_hz()
        if DEMO_MODE:
            self._hz_task = asyncio.ensure_future(
                self._demo_hz_stream(topic))
            return
        self.hz_process = await asyncio.create_subprocess_exec(
            *ROSTOPIC_PREFIX, "rostopic", "hz", topic,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subprocess_env(),
        )
        self._hz_task = asyncio.ensure_future(self._read_hz_stream())

    async def _read_hz_stream(self) -> None:
        while self.hz_process and self.hz_process.returncode is None:
            try:
                line = await self.hz_process.stdout.readline()
            except Exception:  # noqa: BLE001
                break
            if line:
                line_str = line.decode("utf-8", errors="ignore")
                match = _RATE_RE.search(line_str)
                if match:
                    try:
                        rate = float(match.group(1))
                    except ValueError:
                        continue
                    await manager.send(self.ws, {
                        "type": "hz_data",
                        "rate": rate,
                        "t": datetime.now().isoformat(),
                    })
            else:
                break

    async def stop_hz(self) -> None:
        if self._hz_task is not None:
            self._hz_task.cancel()
            self._hz_task = None
        if self.hz_process and self.hz_process.returncode is None:
            try:
                self.hz_process.terminate()
                await asyncio.wait_for(self.hz_process.wait(), timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self.hz_process.kill()
                    await self.hz_process.wait()
                except Exception:  # noqa: BLE001
                    pass
        self.hz_process = None

    # ---------- Service Call ----------
    async def start_service_call(self, service: str) -> None:
        await self.stop_service_call()
        if DEMO_MODE:
            self._service_task = asyncio.ensure_future(
                self._demo_service_stream(service))
            return
        self.service_process = await asyncio.create_subprocess_exec(
            *ROSTOPIC_PREFIX, "rosservice", "call", service,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subprocess_env(),
        )
        self._service_task = asyncio.ensure_future(self._read_service_stream())

    async def _read_service_stream(self) -> None:
        while self.service_process and self.service_process.returncode is None:
            try:
                line = await self.service_process.stdout.readline()
            except Exception:  # noqa: BLE001
                break
            if line:
                msg = {
                    "type": "service_data",
                    "line": line.decode("utf-8", errors="ignore").rstrip("\n"),
                }
                try:
                    await manager.send(self.ws, msg)
                except Exception:  # noqa: BLE001
                    break
            else:
                break
        # 调用结束后，若有 stderr 错误信息一并推送（如服务不存在）
        if self.service_process and self.service_process.returncode not in (None, 0):
            try:
                err = await asyncio.wait_for(self.service_process.stderr.read(), timeout=1)
                if err:
                    await manager.send(self.ws, {
                        "type": "service_data",
                        "line": "[stderr] " + err.decode("utf-8", errors="ignore").strip(),
                    })
            except Exception:  # noqa: BLE001
                pass
        # 通知前端本次调用已结束
        await manager.send(self.ws, {"type": "service_done"})

    async def stop_service_call(self) -> None:
        if self._service_task is not None:
            self._service_task.cancel()
            self._service_task = None
        if self.service_process and self.service_process.returncode is None:
            try:
                self.service_process.terminate()
                await asyncio.wait_for(self.service_process.wait(), timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self.service_process.kill()
                    await self.service_process.wait()
                except Exception:  # noqa: BLE001
                    pass
        self.service_process = None

    # ---------- Demo 模式：生成式数据流替代子进程 ----------
    async def _demo_echo_stream(self, topic: str) -> None:
        try:
            async for line in demo_ros.demo_echo_stream(topic):
                await manager.send(self.ws, {"type": "echo_data", "line": line})
        except Exception:  # noqa: BLE001
            pass

    async def _demo_hz_stream(self, topic: str) -> None:
        try:
            async for chunk in demo_ros.demo_hz_stream(topic):
                for line in chunk.splitlines():
                    m = _RATE_RE.search(line)
                    if m:
                        try:
                            rate = float(m.group(1))
                        except ValueError:
                            continue
                        await manager.send(self.ws, {
                            "type": "hz_data",
                            "rate": rate,
                            "t": datetime.now().isoformat(),
                        })
        except Exception:  # noqa: BLE001
            pass

    async def _demo_service_stream(self, service: str) -> None:
        try:
            async for line in demo_ros.demo_service_stream(service):
                await manager.send(self.ws, {
                    "type": "service_data", "line": line})
            await manager.send(self.ws, {"type": "service_done"})
        except Exception:  # noqa: BLE001
            pass

    async def cleanup(self) -> None:
        await self.stop_echo()
        await self.stop_hz()
        await self.stop_service_call()
