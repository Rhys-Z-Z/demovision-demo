# -*- coding: utf-8 -*-
"""SDK 一键启停控制：管理 roscore / roslaunch dv_sdk 子进程生命周期（单例）"""
from __future__ import annotations

import asyncio
import os
import re
import socket
from typing import Optional

from app.config import DEMO_MODE
from app.services.demo.demo_sdk import DemoSDK
from app.utils.logger import logger

# dv_sdk.launch 中的节点名（rosnode list 检测用）
_SDK_NODE = "/dv_sdk"

# 从 dv_sdk stdout 中提取版本号的正则（demo 日志打印 DemoVision SDK version:）
_SDK_VER_RE = re.compile(r'(?:DemoVision|XV) SDK version:\s*([\S]+)')
_FW_VER_RE = re.compile(r'Device [Vv]ersion\s*:\s*([\S]+)')


class SDKManager:
    """维护 SDK 运行状态与子进程生命周期，互斥锁防止重复拉起"""

    _instance: Optional["SDKManager"] = None

    def __init__(self) -> None:
        self.master_proc: Optional[asyncio.subprocess.Process] = None  # roscore
        self.launch_proc: Optional[asyncio.subprocess.Process] = None  # roslaunch dv_sdk
        self.video_server_proc: Optional[asyncio.subprocess.Process] = None  # web_video_server
        self.task_lock = asyncio.Lock()
        self._broadcast = None  # 可选 WS 广播回调（用于 sdk_log）
        self.sdk_version: str = ""       # 从 dv_sdk stdout 提取（如 3.2.0-20260625_500hz(a0985454)）
        self.firmware_version: str = ""  # 设备固件（如 V1.04P31||Reed_O_7251|V1.00|...|2c62598）
        self._demo = DemoSDK.get_instance() if DEMO_MODE else None

    @classmethod
    def get_instance(cls) -> "SDKManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_broadcast(self, fn) -> None:
        self._broadcast = fn
        if self._demo is not None:
            self._demo.set_broadcast(fn)

    def _spawn_env(self) -> dict:
        """继承后端环境变量；若默认 ROS 日志目录不可写（如沙箱环境）则回退到 /tmp/ros_log"""
        env = os.environ.copy()
        if env.get("ROS_LOG_DIR"):
            return env
        default_log = os.path.expanduser("~/.ros/log")
        try:
            os.makedirs(default_log, exist_ok=True)
            probe = os.path.join(default_log, ".sdk_write_probe")
            with open(probe, "w"):
                pass
            os.remove(probe)
        except OSError:
            fallback = "/tmp/ros_log"
            os.makedirs(fallback, exist_ok=True)
            env["ROS_LOG_DIR"] = fallback
            logger.warning(f"[sdk] ~/.ros/log 不可写，ROS_LOG_DIR 回退到 {fallback}")
        return env

    async def _rosnode_list(self) -> list:
        """异步执行 rosnode list，返回节点名列表；master 不可达返回空列表"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "rosnode", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=6)
            text = out.decode("utf-8", errors="ignore")
            return [line.strip() for line in text.splitlines() if line.strip()]
        except Exception:  # noqa: BLE001
            return []

    async def _master_online(self) -> bool:
        """roscore / ROS master 是否可达（rosnode list 能列出节点）"""
        nodes = await self._rosnode_list()
        return len(nodes) > 0

    async def _sdk_online(self) -> bool:
        """dv_sdk 节点是否在线"""
        nodes = await self._rosnode_list()
        return _SDK_NODE in nodes

    # ---------- 启动 ----------
    async def start_sdk(self) -> dict:
        if self._demo is not None:
            return await self._demo.start()
        async with self.task_lock:
            # 已在线（无论谁启动）直接返回
            if await self._sdk_online():
                return {"status": "already_running"}

            # 1. master 不在线则先拉起 roscore
            if not await self._master_online():
                try:
                    self.master_proc = await asyncio.create_subprocess_exec(
                        "roscore",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env=self._spawn_env(),
                    )
                    logger.info("[sdk] roscore 已启动")
                    await asyncio.sleep(2)  # 等 master 就绪
                except Exception as e:  # noqa: BLE001
                    logger.error(f"[sdk] 启动 roscore 失败: {e}")
                    return {"status": "start_failed", "error": str(e)}

            # 2. 拉起 roslaunch dv_sdk（继承后端环境变量，含 ROS/catkin 注入）
            try:
                self.launch_proc = await asyncio.create_subprocess_exec(
                    "roslaunch", "dv_sdk", "dv_sdk.launch",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=self._spawn_env(),
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"[sdk] 启动 roslaunch 失败: {e}")
                return {"status": "start_failed", "error": str(e)}

            logger.info("[sdk] roslaunch dv_sdk 已启动，后台监控中")
            asyncio.create_task(self._monitor_process())
            return {"status": "started"}

    async def _monitor_process(self) -> None:
        """监控 roslaunch 进程：实时转发日志，退出时清理状态"""
        assert self.launch_proc is not None
        try:
            while self.launch_proc.returncode is None:
                line = await self.launch_proc.stdout.readline()
                if not line:
                    # 进程结束但管道未读完时避免空转
                    if self.launch_proc.returncode is not None:
                        break
                    await asyncio.sleep(0.05)
                    continue
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text.strip():
                    self._ingest_version(text)
                    logger.info(f"[sdk] {text}")
                    if self._broadcast:
                        try:
                            await self._broadcast({"type": "sdk_log", "line": text})
                        except Exception:  # noqa: BLE001
                            pass
            rc = self.launch_proc.returncode
            logger.warning(f"[sdk] roslaunch 进程退出，returncode={rc}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[sdk] 监控任务异常: {e}")
        finally:
            self.launch_proc = None
            if self._broadcast:
                try:
                    await self._broadcast({"type": "sdk_status", "is_running": False})
                except Exception:  # noqa: BLE001
                    pass

    # ---------- 停止 ----------
    async def stop_sdk(self) -> dict:
        if self._demo is not None:
            return await self._demo.stop()
        async with self.task_lock:
            # 1. 优雅停止 roslaunch：SIGINT → 5s 超时 → SIGKILL
            if self.launch_proc is not None and self.launch_proc.returncode is None:
                try:
                    self.launch_proc.send_signal(2)  # SIGINT (Ctrl+C)
                    await asyncio.wait_for(self.launch_proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.launch_proc.kill()
                    await self.launch_proc.wait()
                self.launch_proc = None

            # 2. 若 master 由本系统拉起，也一并关闭
            if self.master_proc is not None and self.master_proc.returncode is None:
                try:
                    self.master_proc.send_signal(2)
                    await asyncio.wait_for(self.master_proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.master_proc.kill()
                    await self.master_proc.wait()
                self.master_proc = None

            return {"status": "stopped"}

    # ---------- 底座服务：web_video_server 托管 ----------
    def is_port_in_use(self, port: int = 8080) -> bool:
        """检查端口是否被占用（占用说明服务已在运行，跳过拉起）"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:  # noqa: BLE001
            return False

    async def start_video_server(self) -> None:
        """随系统启动自动拉起 web_video_server（端口被占用则跳过，防止冲突）"""
        if self._demo is not None:
            logger.info("[sdk] Demo 模式：视频服务由模拟帧提供，跳过拉起 web_video_server")
            return
        if self.is_port_in_use(8080):
            logger.info("[sdk] web_video_server (8080) 已在运行，跳过启动")
            return
        try:
            self.video_server_proc = await asyncio.create_subprocess_exec(
                "rosrun", "web_video_server", "web_video_server",
                stdout=asyncio.subprocess.DEVNULL,  # 屏蔽无用输出
                stderr=asyncio.subprocess.DEVNULL,
                env=os.environ.copy(),
            )
            logger.info("[sdk] 已自动拉起 web_video_server (8080)")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[sdk] 拉起 web_video_server 失败: {e}")

    async def stop_video_server(self) -> None:
        """应用退出时关闭自管的 web_video_server（不影响外部手动启动的实例）"""
        if self._demo is not None:
            return
        proc = self.video_server_proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            logger.info("[sdk] web_video_server (8080) 已关闭")
        self.video_server_proc = None

    # ---------- 状态 ----------
    def _ingest_version(self, line: str) -> None:
        """从 dv_sdk stdout 行中提取 SDK 版本与固件版本并缓存"""
        m = _SDK_VER_RE.search(line)
        if m:
            self.sdk_version = m.group(1)
        m = _FW_VER_RE.search(line)
        if m:
            self.firmware_version = m.group(1)

    async def get_status(self) -> dict:
        """返回 SDK 与底座服务状态：/dv_sdk 在线即视为运行中（含手动启动场景）"""
        if self._demo is not None:
            return self._demo.status()
        return {
            "is_running": await self._sdk_online(),
            "managed": self.launch_proc is not None and self.launch_proc.returncode is None,
            "video_server_running": self.is_port_in_use(8080),
            "sdk_version": self.sdk_version,
            "firmware_version": self.firmware_version,
        }
