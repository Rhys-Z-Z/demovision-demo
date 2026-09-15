#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DemoVision Device Detection Tool - DEMO SIMULATOR
=============================================================================
公开 Demo 版：本文件是产线检测脚本的**模拟实现**，不包含任何真实产线逻辑、
不依赖 ROS / dv_sdk / 硬件。它与原始脚本保持相同文件名与公共接口，
backend 的「import / 子进程 → 解析 → 落盘 → 入库」管线原样复用。

提供的公共接口（与 backend 调用契约一致）：
    - 模块级：os / reset_detection_cancel / cancel_detection / is_detection_cancelled / LogManager
    - Config：BASE_DIR / TIME_COLOR / TIME_FISHEYE / TIME_SLAM / TIME_TOF / TOPIC_PREFIX
    - ROSInterface.get_devices()（设备发现唯一入口，demo 返回模拟 SN）
    - DemoVisionDetector（test_type / config / tester.ros / report_gen /
      _load_device_info / get_date_dir / generate_normalized_suffix /
      run_camera_test / run_tof_detection / update_clamp_list）
    - DetectionReport / ReportGenerator（落盘 00_summary_report.txt 等，
      格式与 backend/app/services/parser_service.py 的 SUMMARY_PATTERNS 兼容）

模拟行为：
    - 设备：固定返回两台模拟 SN（与 backend demo 包 demo_devices 保持一致）
    - 检测：随机生成通过/失败结果（高通过率），打印阶段日志与 \r 进度条，
      支持真实可中断（cancel_detection 后优雅收尾）
    - 时长：每子项约 0.4s（忽略配置的 TIME_*，demo 节奏优先）
=============================================================================
"""

import os
import sys
import time
import random
from datetime import datetime
from pathlib import Path

# 数据根目录（与 backend config.DATA_DIR 同源，由 detection_runner 启动前注入）
BASE_DIR = os.environ.get("DEMOVISION_DATA_DIR") or os.path.expanduser("~/demovision_data")

# ===== 全局取消标记（线程安全） =====
_CANCEL_FLAG = False


def reset_detection_cancel() -> None:
    """重置取消标记（任务开始前调用）"""
    global _CANCEL_FLAG
    _CANCEL_FLAG = False


def cancel_detection() -> None:
    """请求取消当前检测（由 /api/detection/stop 触发）"""
    global _CANCEL_FLAG
    _CANCEL_FLAG = True


def is_detection_cancelled() -> bool:
    """是否收到取消请求"""
    return _CANCEL_FLAG


# ===== 日志管理（仅落 /tmp 文件，不启动终端窗口） =====
class LogManager:
    """日志管理器 - 模拟版：demo 模式下仅维护 /tmp 日志文件，无终端子进程"""

    _log_file_path = None

    @classmethod
    def init(cls, use_log_terminal: bool = True):
        """初始化日志管理器"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        cls._log_file_path = f"/tmp/demovision_detector_{timestamp}.log"
        try:
            Path(cls._log_file_path).write_text(
                f"[LogManager] demo 模拟器日志已初始化 {timestamp}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    @classmethod
    def cleanup(cls):
        cls._log_file_path = None


# ===== 配置 =====
class Config:
    """检测配置（支持实例 setattr：detection_runner 会按任务覆盖 TIME_* 字段）"""

    def __init__(self):
        self.BASE_DIR: str = BASE_DIR
        self.TIME_COLOR: int = 3
        self.TIME_FISHEYE: int = 3
        self.TIME_SLAM: int = 3
        self.TIME_TOF: int = 3
        self.TOPIC_PREFIX: str = "/dv_sdk"


# ===== 模拟设备（与 backend/app/services/demo/demo_devices.py 保持一致） =====
DEMO_SERIALS = [
    "DVSNDV000001",
    "DVSNDV000002",
]


class ROSInterface:
    """模拟 ROS 接口：demo 版不依赖 rospy，直接返回模拟设备"""

    @classmethod
    def get_devices(cls) -> list:
        return list(DEMO_SERIALS)

    @classmethod
    def roscore_running(cls) -> bool:
        """模拟环境检查：demo 模式恒为 True"""
        return True


# ===== 检测报告 =====
class DetectionReport:
    """单次检测结果汇总（字段与历史页展示口径一致）"""

    def __init__(self, sn_list, color_result, fisheye_result, slam_result):
        self.sn_list = list(sn_list)
        self.color_result = color_result        # {pass, total}
        self.fisheye_result = fisheye_result
        self.slam_result = slam_result
        self.passed = (color_result["pass"] == color_result["total"]
                       and fisheye_result["pass"] == fisheye_result["total"]
                       and slam_result["pass"] == slam_result["total"])
        self.overall_status = "PASS" if self.passed else "FAIL"


# ===== 报告生成器（格式对齐 parser_service.SUMMARY_PATTERNS） =====
class ReportGenerator:
    """把检测结果落盘为 00_summary_report.txt / 01/02/03 报告"""

    def _fmt_pass(self, r: dict) -> str:
        return f"{r['pass']}/{r['total']}"

    def _fmt_rate(self, r: dict) -> str:
        if not r["total"]:
            return "0.0"
        return f"{100.0 * r['pass'] / r['total']:.1f}"

    def generate_reports(self, report: DetectionReport, fps_dir: str, sn_list: list) -> None:
        os.makedirs(fps_dir, exist_ok=True)
        cr, fr_, sr = report.color_result, report.fisheye_result, report.slam_result
        total = len(sn_list)

        lines = [
            "=" * 60,
            "DemoVision 设备检测汇总报告（DEMO 模拟数据）",
            "=" * 60,
            f"生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"检测设备: {', '.join(s[-8:] for s in sn_list)}",
            "",
            f"设备总数: {total}",
            f"Color相机通过: {self._fmt_pass(cr)}",
            f"Fisheye通过: {self._fmt_pass(fr_)}",
            f"SLAM通过: {self._fmt_pass(sr)}",
            f"Color通过率: {self._fmt_rate(cr)}%",
            f"Fisheye通过率: {self._fmt_rate(fr_)}%",
            f"SLAM通过率: {self._fmt_rate(sr)}%",
            "",
            f"整体检测状态: {report.overall_status}",
            "=" * 60,
        ]
        _write_text(os.path.join(fps_dir, "00_summary_report.txt"), "\n".join(lines))

        # 01 Color 相机
        _write_text(os.path.join(fps_dir, "01_color_report.txt"),
                    "\n".join([
                        "Color 相机检测报告（DEMO）",
                        f"通过: {self._fmt_pass(cr)}    通过率: {self._fmt_rate(cr)}%",
                    ]))
        # 02 Fisheye
        _write_text(os.path.join(fps_dir, "02_fisheye_report.txt"),
                    "\n".join([
                        "Fisheye 检测报告（DEMO）",
                        f"通过: {self._fmt_pass(fr_)}    通过率: {self._fmt_rate(fr_)}%",
                    ]))
        # 03 SLAM
        _write_text(os.path.join(fps_dir, "03_slam_report.txt"),
                    "\n".join([
                        "SLAM 检测报告（DEMO）",
                        f"通过: {self._fmt_pass(sr)}    通过率: {self._fmt_rate(sr)}%",
                    ]))
        # 04 ToF（全功能模式补齐产物）
        _write_text(os.path.join(fps_dir, "04_tof_report.txt"),
                    "\n".join([
                        "ToF 检测报告（DEMO）",
                        "ToF 通过: 通过",
                    ]))


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


# ===== 检测器主类 =====
class DemoVisionDetector:
    """模拟产线检测器：随机生成结果、打印阶段日志、落盘报告"""

    def __init__(self, use_log_terminal: bool = True):
        self.use_log_terminal = use_log_terminal
        self.config = Config()
        self.test_type = "测试"
        self.tester = _Tester()
        self.report_gen = ReportGenerator()
        self._device_info = {}

    def _log(self, msg: str) -> None:
        print(msg, flush=True)

    # ---------- 设备信息 ----------
    def _load_device_info(self) -> None:
        """加载设备版本信息（demo：生成模拟固件/SDK 版本）"""
        fw = f"DV-Demo-{datetime.now():%y%m%d}"
        for sn in self.tester.ros.get_devices():
            self._device_info[sn] = {"firmware": fw, "sdk": "3.2.0-demo"}
        self._log(f"设备版本信息已加载: 固件 {fw} / SDK 3.2.0-demo")

    # ---------- 路径 ----------
    def get_date_dir(self) -> str:
        """日期目录绝对路径（与 backend utils/paths.date_key_of() 逐字符一致）"""
        now = datetime.now()
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        month_en = months[now.month]
        return os.path.join(self.config.BASE_DIR,
                            f"{now.year}_{month_en}", f"{month_en}_{now.day}")

    def generate_normalized_suffix(self, sn_list: list) -> str:
        """生成目录后缀：SN 后 8 位拼接（与产线命名一致）"""
        return "_".join(s[-8:] if len(s) >= 8 else s for s in sn_list)

    # ---------- 取消语义 ----------
    def _wait(self, seconds: float) -> bool:
        """按取消标记分段等待；返回是否被取消"""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if is_detection_cancelled():
                return True
            time.sleep(0.02)
        return is_detection_cancelled()

    # ---------- 检测 ----------
    def _gen_result(self, total: int, pass_rate: float) -> dict:
        """随机生成通过结果（可复现性无关，demo 每次运行略有差异）"""
        passed = sum(1 for _ in range(total) if random.random() < pass_rate)
        return {"pass": passed, "total": total}

    def _run_item(self, name: str, fps_dir: str, sn_list: list,
                  pass_rate: float, duration: float) -> dict:
        """单个检测项：进度条 + 随机结果；返回结果字典或 None（被取消）"""
        for i, sn in enumerate(sn_list, 1):
            if self._wait(duration):
                self._log(f"[{name}] 检测被取消（{sn[-8:]}），停止后续采集")
                return None
            pct = int(100.0 * i / len(sn_list))
            print(f"\r[{name}] {sn[-8:]} 采集中 {pct}% ...", end="", flush=True)
            time.sleep(0.05)
        print()
        result = self._gen_result(len(sn_list), pass_rate)
        self._log(f"[{name}] 完成: {result['pass']}/{result['total']} 通过")
        return result

    def run_camera_test(self, fps_dir: str, sn_list: list) -> DetectionReport:
        """执行相机相关检测（Color + Fisheye + SLAM），返回报告"""
        self._log("开始相机检测（Color / Fisheye / SLAM）...")
        cr = self._run_item("Color相机", fps_dir, sn_list, pass_rate=0.95, duration=0.4)
        if cr is None:
            cr = {"pass": 0, "total": len(sn_list)}
        fr_ = self._run_item("Fisheye", fps_dir, sn_list, pass_rate=0.95, duration=0.4)
        if fr_ is None:
            fr_ = {"pass": 0, "total": len(sn_list)}
        sr = self._run_item("SLAM", fps_dir, sn_list, pass_rate=0.9, duration=0.4)
        if sr is None:
            sr = {"pass": 0, "total": len(sn_list)}
        return DetectionReport(sn_list, cr, fr_, sr)

    def run_tof_detection(self, fps_dir: str, sn_list: list) -> None:
        """ToF 检测（demo：仅日志与进度）"""
        self._log("开始 ToF 检测...")
        if self._run_item("ToF", fps_dir, sn_list, pass_rate=0.98, duration=0.3) is not None:
            self._log("ToF 检测完成: 全部通过")

    def update_clamp_list(self, date_dir: str, sn_list: list, report: DetectionReport) -> None:
        """更新夹紧列表（demo：落一份 clamp_list.txt 占位产物）"""
        try:
            os.makedirs(date_dir, exist_ok=True)
            path = os.path.join(date_dir, "clamp_list.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | "
                        f"{', '.join(sn_list)} | {report.overall_status}\n")
        except OSError:
            pass


class _Tester:
    """容器对象：暴露 .ros（ROSInterface）"""

    def __init__(self):
        self.ros = ROSInterface


if __name__ == "__main__":
    # 独立运行冒烟：跑一次完整检测并落盘到 $HOME/demovision_data
    LogManager.init(use_log_terminal=False)
    det = DemoVisionDetector(use_log_terminal=False)
    online = ROSInterface.get_devices()
    print(f"在线设备: {online}")
    det._load_device_info()
    date_dir = det.get_date_dir()
    out_root = os.path.join(date_dir, "demo_standalone")
    os.makedirs(out_root, exist_ok=True)
    fps = os.path.join(out_root, "fps")
    rep = det.run_camera_test(fps, online)
    det.report_gen.generate_reports(rep, fps, online)
    det.run_tof_detection(fps, online)
    det.update_clamp_list(date_dir, online, rep)
    print(f"检测完成: {rep.overall_status} -> {out_root}")
    LogManager.cleanup()
