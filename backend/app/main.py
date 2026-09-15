# -*- coding: utf-8 -*-
"""FastAPI 入口：挂载路由、WebSocket、rospy 后台节点与前端静态文件"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (detection, devices, files, history, imu, operations,
                     ros_monitor, sdk_control, slam, snapshot, system, video)
from app.db.database import init_db
from app.db.migrate import run_migrations
from app.config import DB_PATH, DATA_DIR, DEMO_MODE
from app.services.ros_topic_monitor import ROSTopicMonitor
from app.services.sdk_manager import SDKManager
from app.services.slam_ros_node import SlamRosMonitor
from app.services.video_streamer import MJPEGProxy
from app.utils.logger import logger
from app.websocket.manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化 SQLite 表 + 幂等迁移（§4）
    await init_db()
    await run_migrations()
    logger.info(f"数据库初始化完成: {DB_PATH}")

    # 1.0 Demo 模式：预置演示数据（幂等：逐表查空才播种）
    if DEMO_MODE:
        from app.services.seed_demo_data import seed_demo_data
        await seed_demo_data()
        logger.info("Demo 模式：演示数据预置完成")

    # 1.1 启动自检：DATA_DIR 存在可写；容器内校验数据目录在 /var/lib/demovision_web/data（T11）
    import os as _os
    from pathlib import Path as _Path
    _data = _Path(DATA_DIR)
    if not _data.is_dir():
        logger.error(f"DATA_DIR 不存在或不可访问: {DATA_DIR}")
    elif not _os.access(str(_data), _os.W_OK):
        logger.error(f"DATA_DIR 不可写: {DATA_DIR}")
    if _os.environ.get("DEMOVISION_WEB_IN_CONTAINER") == "1":
        _expected = _Path("/var/lib/demovision_web/data").resolve()
        _actual = _data.resolve()
        if _actual != _expected:
            logger.error(
                "容器内 DATA_DIR 不在 /var/lib/demovision_web/data，数据可能落进容器可写层（容器销毁即丢失）: "
                f"actual={_actual} expected={_expected}"
            )
        else:
            logger.info("容器内 DATA_DIR 校验通过（位于宿主挂载区）")

    # 2. 启动轨道 B：后台 rospy 订阅节点
    loop = asyncio.get_running_loop()

    def _broadcast_from_thread(data: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)
        except Exception:  # noqa: BLE001
            pass

    app.state.slam_monitor = SlamRosMonitor(_broadcast_from_thread)
    app.state.slam_monitor.start()
    slam.set_slam_monitor(app.state.slam_monitor)
    if app.state.slam_monitor.available:
        logger.info("SLAM 实时监控节点已启动（rospy 后台线程；节点将在 roscore 就绪后自动建立订阅）")
    else:
        logger.warning("rospy 或 dv_sdk 消息包不可用，SLAM 实时大屏数据源降级（仅支持历史回放）")

    # 3. SDK 一键启停：注入 WS 广播回调（sdk_log / sdk_status 推送）
    sdk_mgr = SDKManager.get_instance()
    sdk_mgr.set_broadcast(manager.broadcast)
    app.state.sdk_manager = sdk_mgr

    # 4. 底座服务一键托管：随系统启动自动拉起 web_video_server（端口被占用则跳过）
    await sdk_mgr.start_video_server()

    yield

    # 关闭清理
    await sdk_mgr.stop_video_server()
    app.state.slam_monitor.unsubscribe_all()
    logger.info("服务关闭，已注销全部订阅")


app = FastAPI(title="DemoVision 设备检测与 SLAM 监控系统", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(devices.router)
app.include_router(detection.router)
app.include_router(slam.router)
app.include_router(history.router)
app.include_router(files.router)
app.include_router(video.router)
app.include_router(ros_monitor.router)
app.include_router(imu.router)
app.include_router(sdk_control.router)
app.include_router(operations.router)
app.include_router(system.router)
app.include_router(snapshot.router)


# 每个 WS 客户端活跃的视频代理（断开即清理）
_video_proxies: dict = {}

# 每个 WS 客户端绑定的 ROS 话题监控（echo/hz 子进程）
_ros_monitors: dict = {}


async def _stop_video_proxy(ws) -> None:
    proxy = _video_proxies.pop(ws, None)
    if proxy is not None:
        proxy.stop()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    ros_monitor = ROSTopicMonitor(ws)
    _ros_monitors[ws] = ros_monitor
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "subscribe_slam":
                sn = msg.get("sn")
                if sn:
                    app.state.slam_monitor.subscribe(sn)
                    await manager.send(ws, {"type": "ack", "action": "subscribe_slam", "sn": sn})
            elif mtype == "unsubscribe_slam":
                sn = msg.get("sn")
                if sn:
                    app.state.slam_monitor.unsubscribe(sn)
                    await manager.send(ws, {"type": "ack", "action": "unsubscribe_slam", "sn": sn})
            elif mtype == "start_video_stream":
                topic = msg.get("topic")
                if topic:
                    await _stop_video_proxy(ws)
                    proxy = MJPEGProxy(ws, topic)
                    _video_proxies[ws] = proxy
                    proxy.start()
                    await manager.send(ws, {"type": "ack", "action": "start_video_stream", "topic": topic})
            elif mtype == "stop_video_stream":
                await _stop_video_proxy(ws)
                await manager.send(ws, {"type": "ack", "action": "stop_video_stream"})
            elif mtype == "start_echo":
                topic = msg.get("topic")
                if topic:
                    await ros_monitor.start_echo(topic)
                    await manager.send(ws, {"type": "ack", "action": "start_echo", "topic": topic})
            elif mtype == "stop_echo":
                await ros_monitor.stop_echo()
                await manager.send(ws, {"type": "ack", "action": "stop_echo"})
            elif mtype == "start_hz":
                topic = msg.get("topic")
                if topic:
                    await ros_monitor.start_hz(topic)
                    await manager.send(ws, {"type": "ack", "action": "start_hz", "topic": topic})
            elif mtype == "stop_hz":
                await ros_monitor.stop_hz()
                await manager.send(ws, {"type": "ack", "action": "stop_hz"})
            elif mtype == "start_service_call":
                service = msg.get("service")
                if service:
                    await ros_monitor.start_service_call(service)
                    await manager.send(ws, {"type": "ack", "action": "start_service_call", "service": service})
            elif mtype == "stop_service_call":
                await ros_monitor.stop_service_call()
                await manager.send(ws, {"type": "ack", "action": "stop_service_call"})
            elif mtype == "ping":
                await manager.send(ws, {"type": "pong"})
    except WebSocketDisconnect:
        await _stop_video_proxy(ws)
        _ros_monitors.pop(ws, None)
        await ros_monitor.cleanup()
        await manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        await _stop_video_proxy(ws)
        _ros_monitors.pop(ws, None)
        await ros_monitor.cleanup()
        await manager.disconnect(ws)


# 挂载前端构建产物（可选）
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info(f"已挂载前端静态文件: {_frontend_dist}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000,
                access_log=False, reload=False)
