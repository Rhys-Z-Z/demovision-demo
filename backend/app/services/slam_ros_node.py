# -*- coding: utf-8 -*-
"""轨道 B：独立 rospy 订阅节点，推送实时坐标到 WebSocket

🔴 本文件有两个必须保留的实现要点（都是实测踩出来的，改动前先读）：
1. `rospy.init_node(..., disable_signals=True)` —— **不可省略**。
   rospy 默认会注册 signal handler，而从**非主线程**调用 init_node 会抛
   `ValueError: signal only works in main thread`。本监控节点跑在后台线程里，
   不加这个参数就永远初始化失败，且原实现把异常吞掉，导致轨道 B（实时大屏）
   **从来没有工作过** —— 页面表现是「订阅返回 ack，但一条曲线数据都收不到」。
2. **节点初始化必须可重试、失败必须留日志**。
   后端常先于 roscore 启动（页面上的「启动 SDK」按钮就是让后端去拉 roscore），
   此时 init_node 连不上 master。故 subscribe() 先把 SN 记入 `_wanted` 待订阅，
   后台线程每秒重试初始化，一旦就绪立即补建全部订阅（自愈，无需重启后端）。
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Dict, Optional, Set

from app.config import DEMO_MODE
from app.services.demo.demo_pose import DemoPoseSimulator
from app.utils.logger import logger


class SlamRosMonitor:
    """后台节点：订阅 /dv_sdk/<sn>/slam/pose，回调中计算 dist 并推送

    Demo 模式（DEMO_MODE）下不依赖 rospy：以 DemoPoseSimulator 产生同构
    slam_data 消息（sn/t/x/y/z/dist），对外行为与真实订阅完全一致。
    """

    def __init__(self, on_data: Callable[[dict], None]) -> None:
        self.on_data = on_data
        self._subs: Dict[str, object] = {}      # 已建立的真实订阅
        self._wanted: Set[str] = set()          # 期望订阅（节点未就绪时先记账）
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._available = False
        self._node_ready = False
        self._handle_errors = 0
        self._demo = DemoPoseSimulator() if DEMO_MODE else None

        try:
            import rospy
            from dv_sdk.msg import PoseStampedConfidence
            self.rospy = rospy
            self.PoseStampedConfidence = PoseStampedConfidence
            self._available = True
        except Exception as e:  # noqa: BLE001 无 ROS 环境时仅降级
            self.rospy = None
            self.PoseStampedConfidence = None
            logger.warning(f"[slam] rospy/dv_sdk 消息不可用，实时大屏降级: {e}")

        if DEMO_MODE:
            # Demo 模式：无视 rospy 可用性，直接用模拟数据源
            self.rospy = None
            self.PoseStampedConfidence = None
            self._available = True

    @property
    def available(self) -> bool:
        """依赖包是否可用（≠ 节点已就绪，见 node_ready）"""
        return self._available

    @property
    def node_ready(self) -> bool:
        """rospy 节点是否真的初始化成功（实时链路是否激活）"""
        if DEMO_MODE:
            return True
        return self._node_ready

    # ---------- 节点生命周期 ----------
    def _ensure_node(self) -> bool:
        """确保 rospy 节点已初始化：幂等、可重试、线程安全（要点见模块 docstring）"""
        if not self._available:
            return False
        if self._node_ready:
            return True
        rospy = self.rospy
        if rospy is None:  # 与 _available 同源，仅为类型收窄
            return False
        with self._init_lock:
            if self._node_ready:
                return True
            try:
                if not rospy.core.is_initialized():
                    rospy.init_node(
                        "web_slam_monitor", anonymous=True, disable_signals=True,
                    )
                self._node_ready = True
                logger.info("[slam] rospy 节点就绪，轨道 B 实时链路已激活")
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[slam] rospy 节点初始化失败（roscore 可能未就绪），1s 后重试: {e}")
                return False

    def start(self) -> None:
        """FastAPI 启动时调用：拉起后台线程（内部自愈重试）"""
        if not self._available or self._thread is not None:
            return
        if DEMO_MODE:
            self._thread = threading.Thread(target=self._demo_spin, daemon=True)
            self._thread.start()
            return
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _demo_spin(self) -> None:
        """Demo 模式：按 ~5Hz 为已订阅设备生成模拟 pose 点并推送"""
        while True:
            try:
                with self._lock:
                    sns = [sn for sn in self._wanted if self._demo.has(sn)]
                for sn in sns:
                    point = self._demo.next_point(sn)
                    if point is not None:
                        self.on_data(point)
            except Exception as e:  # noqa: BLE001 线程绝不允许因异常退出
                logger.warning(f"[slam] demo 实时监控线程异常: {e}")
            time.sleep(0.2)

    def _spin(self) -> None:
        while True:
            try:
                if not self._node_ready and self._ensure_node():
                    self._resubscribe_all()
            except Exception as e:  # noqa: BLE001 线程绝不允许因异常退出
                logger.warning(f"[slam] 实时监控线程异常（继续重试）: {e}")
            time.sleep(1.0)

    # ---------- 订阅管理 ----------
    def _create_sub(self, sn: str) -> Optional[object]:
        topic = f"/dv_sdk/{sn}/slam/pose"

        def callback(msg, _sn=sn):
            self._handle(msg, _sn)

        try:
            sub = self.rospy.Subscriber(topic, self.PoseStampedConfidence,
                                        callback, queue_size=100)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[slam] 订阅 {topic} 失败: {e}")
            return None
        with self._lock:
            self._subs[sn] = sub
        logger.info(f"[slam] 已订阅 {topic}")
        return sub

    def subscribe(self, sn: str) -> Optional[object]:
        """订阅指定设备的 pose 话题；节点未就绪时只登记，就绪后由 _spin 自动补建"""
        if not self._available or not sn:
            return None
        with self._lock:
            self._wanted.add(sn)
            if sn in self._subs:
                return self._subs[sn]
        if DEMO_MODE:
            self._demo.subscribe(sn)
            logger.info(f"[slam] demo 已登记订阅: {sn}")
            return None
        if not self._ensure_node():
            logger.info(f"[slam] 节点未就绪，已登记待订阅: {sn}")
            return None
        return self._create_sub(sn)

    def _resubscribe_all(self) -> None:
        """节点就绪后，把所有登记过的 SN 补建订阅"""
        with self._lock:
            pending = [sn for sn in self._wanted if sn not in self._subs]
        for sn in pending:
            self._create_sub(sn)

    def unsubscribe(self, sn: str) -> None:
        with self._lock:
            self._wanted.discard(sn)
            sub = self._subs.pop(sn, None)
        if DEMO_MODE:
            self._demo.unsubscribe(sn)
        if sub is not None:
            try:
                sub.unregister()
            except Exception:  # noqa: BLE001
                pass

    def unsubscribe_all(self) -> None:
        with self._lock:
            subs = list(self._subs.values())
            self._subs.clear()
            self._wanted.clear()
        for sub in subs:
            try:
                sub.unregister()
            except Exception:  # noqa: BLE001
                pass

    # ---------- 数据回调 ----------
    def _handle(self, msg, sn: str) -> None:
        try:
            pos = msg.poseMsg.pose.position
            x, y, z = pos.x, pos.y, pos.z
            dist = math.sqrt(x * x + y * y + z * z)
            stamp = msg.poseMsg.header.stamp
            t = stamp.to_sec() if stamp is not None and stamp.secs > 0 \
                else self.rospy.get_time()
            self.on_data({
                "type": "slam_data",
                "sn": sn, "t": t,
                "x": x, "y": y, "z": z, "dist": dist,
            })
        except Exception as e:  # noqa: BLE001
            # 不再静默：前几次留痕，避免字段结构变化时无声失效
            self._handle_errors += 1
            if self._handle_errors <= 3:
                logger.warning(f"[slam] 解析 pose 消息失败（{sn}）: {e}")
