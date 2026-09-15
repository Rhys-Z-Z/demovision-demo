# -*- coding: utf-8 -*-
"""检测任务执行器：import ship_out.py 核心类，重定向日志，落盘入库"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
from datetime import datetime
from typing import Callable, List, Optional

from app.config import DATA_DIR
from app.utils.paths import detection_rel, date_key_of

# 重要：detection_runner 通过 import 方式执行 ship_out，须在执行前注入数据根目录，
# 使 ship_out.Config.BASE_DIR 读取到 FHS 数据目录（开发态由 start.sh 覆盖为 work_t）。
os.environ["DEMOVISION_DATA_DIR"] = DATA_DIR


# 检测时长自定义项（映射到 ship_out.Config 的字段）
TIME_FIELDS = {
    "color": "TIME_COLOR",
    "fisheye": "TIME_FISHEYE",
    "slam": "TIME_SLAM",
    "tof": "TIME_TOF",
}


def request_cancel_detection() -> None:
    """请求停止当前检测（由 /api/detection/stop 调用）"""
    import ship_out
    ship_out.cancel_detection()


def reset_detection_cancel() -> None:
    import ship_out
    ship_out.reset_detection_cancel()


def is_detection_cancelled() -> bool:
    import ship_out
    return ship_out.is_detection_cancelled()


class LogRedirect:
    """把子线程中的 stdout/stderr 输出按行/进度条实时转发给回调"""

    def __init__(self, on_message: Callable[[str], None]) -> None:
        self._on_message = on_message
        self._buf = ""
        self._tee_lock = threading.Lock()
        self._tee_fh = None

    def set_tee(self, filepath: str) -> None:
        """开启 tee：每行在回调广播的同时追加写入任务目录 run.log（线程安全）"""
        with self._tee_lock:
            if self._tee_fh is not None:
                self._tee_fh.close()
            self._tee_fh = open(filepath, "a", encoding="utf-8", errors="replace")

    def close_tee(self) -> None:
        with self._tee_lock:
            if self._tee_fh is not None:
                self._tee_fh.close()
                self._tee_fh = None

    def _emit(self, line: str) -> None:
        self._on_message(line)
        with self._tee_lock:
            if self._tee_fh is not None:
                try:
                    self._tee_fh.write(line + "\n")
                    self._tee_fh.flush()
                except OSError:
                    pass

    def write(self, text: str) -> None:
        if not text:
            return
        text = re.sub(r"\033\[[0-9;]*m", "", text)
        # 进度条：\r 刷新且无换行，直接取最新一段
        if "\r" in text and "\n" not in text:
            line = text.split("\r")[-1].strip()
            if line:
                self._emit(line)
            return
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip("\r").strip()
            if line:
                self._emit(line)

    def flush(self) -> None:
        pass

    @property
    def encoding(self) -> str:
        return "utf-8"

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return -1

    def read(self, *args, **kwargs):
        raise OSError("redirected stdout is not readable")


class DetectionRunner:
    """在 executor 线程中运行 ship_out 检测流程，日志实时广播到 WebSocket"""

    def __init__(self, loop: asyncio.AbstractEventLoop,
                 broadcast: Callable[[dict], None]) -> None:
        self.loop = loop
        self.broadcast = broadcast
        self._orig_stdout: Optional[object] = None
        self._orig_stderr: Optional[object] = None

    def _log(self, line: str, task_uuid: str = "") -> None:
        try:
            payload = {"type": "log_message", "line": line}
            if task_uuid:
                payload["task_uuid"] = task_uuid
            asyncio.run_coroutine_threadsafe(
                self.broadcast(payload),
                self.loop,
            )
        except Exception:
            pass

    def run(self, task_uuid: str, devices: List[str],
            mode: str, device_type: str,
            times: Optional[dict] = None) -> dict:
        """入口：屏蔽 clear、重定向输出、执行检测"""
        import ship_out  # 延迟导入：依赖 ROS 环境

        # 屏蔽 os.system('clear') 效果
        ship_out.os.system = lambda cmd: None

        # 重置取消标记（各项目时长在 _execute 中应用到具体 Config 实例）
        ship_out.reset_detection_cancel()

        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._redirect = LogRedirect(lambda l: self._log(l, task_uuid))
        sys.stdout = self._redirect
        sys.stderr = LogRedirect(lambda l: self._log(f"[ERR] {l}", task_uuid))
        try:
            return self._execute(ship_out, task_uuid, devices, mode, device_type, times)
        finally:
            self._redirect.close_tee()
            sys.stdout = self._orig_stdout
            sys.stderr = self._orig_stderr

    def _execute(self, ship_out, task_uuid: str, devices: List[str],
                 mode: str, device_type: str, times: Optional[dict] = None) -> dict:
        # 初始化日志系统（不启动终端窗口，仅落 /tmp 日志文件）
        ship_out.LogManager.init(use_log_terminal=False)

        detector = ship_out.DemoVisionDetector(use_log_terminal=False)
        detector.test_type = device_type

        # 应用自定义各项目时长（单位：秒）。
        # 注意：必须写在 detector.config 实例上（tester/report_gen 与它共享同一对象），
        # 不能只改 ship_out.Config 类属性——dataclass 的 __init__ 会烘焙默认值，新实例读不到类属性改动。
        cfg = detector.config
        for key, field in TIME_FIELDS.items():
            t = (times or {}).get(key)
            if isinstance(t, (int, float)) and t > 0:
                setattr(cfg, field, int(t))
                self._log(f"[时长] 项目 {key} = {int(t)}s")

        self._log("=" * 60)
        self._log(f"[任务 {task_uuid[:8]}] 检测启动 | 模式: {mode} | 设备类型: {device_type}")

        # 1. 环境检查
        self._log("[1/6] 检查 ROS 环境...")
        if not detector.tester.ros.roscore_running():
            raise RuntimeError("roscore 未运行，请先启动 ROS 环境")

        # 2. 设备发现与校验
        self._log("[2/6] 扫描在线设备...")
        online = detector.tester.ros.get_devices()
        if devices:
            missing = [d for d in devices if d not in online]
            if missing:
                raise RuntimeError(f"以下设备离线: {', '.join(m[-8:] for m in missing)}")
            sn_list = devices
        else:
            if not online:
                raise RuntimeError("未发现任何在线设备")
            sn_list = online
        self._log(f"参与检测设备: {', '.join(s[-8:] for s in sn_list)}")

        # 3. 加载设备版本信息（回退方案自动处理）
        self._log("[3/6] 加载设备版本信息...")
        detector._load_device_info()

        # 4. 创建输出目录（A1：一运行一目录，时间戳防撞名；单设备进 SN 层，多设备落日期根）
        self._log("[4/6] 准备输出目录...")
        date_key = date_key_of()
        date_dir = detector.get_date_dir()          # 与 ship_out 完全一致（绝对路径）
        os.makedirs(date_dir, exist_ok=True)
        dir_suffix = detector.generate_normalized_suffix(sn_list)
        rel_path = detection_rel(date_key, sn_list, dir_suffix,
                                 datetime.now().strftime("%H%M%S"))
        result_dir = os.path.join(DATA_DIR, rel_path)
        os.makedirs(result_dir, exist_ok=True)
        fps_dir = os.path.join(result_dir, "fps")
        os.makedirs(fps_dir, exist_ok=True)
        # tee run.log（与广播同源）
        self._redirect.set_tee(os.path.join(result_dir, "run.log"))
        self._log(f"输出目录: {result_dir}")

        # 5. 执行检测
        self._log("[5/6] 开始检测...")
        run_cam = mode in ("仅相机", "全功能")
        run_tof = mode in ("仅ToF", "全功能")

        summary: dict = {}
        overall_status = "FAIL"
        if run_cam and not ship_out.is_detection_cancelled():
            report = detector.run_camera_test(fps_dir, sn_list)
            # 即使中途被手动停止，也把“到此为止”的报告文件生成到 fps 目录，
            # 避免只留原始数据、缺 00/01/02/03 报告（报告文件与已采集数据一同留存）
            try:
                detector.report_gen.generate_reports(report, fps_dir, sn_list)
            except Exception as e:  # noqa: BLE001
                self._log(f"生成报告文件失败（已采集数据不影响落盘）: {e}")
            if not ship_out.is_detection_cancelled():
                try:
                    detector.update_clamp_list(date_dir, sn_list, report)
                except Exception:  # noqa: BLE001
                    pass
            summary_file = os.path.join(fps_dir, "00_summary_report.txt")
            from app.services.parser_service import parse_detection_summary
            parsed = parse_detection_summary(summary_file)
            if parsed:
                summary = parsed
                overall_status = parsed.get("overall_status", report.overall_status)
            else:
                overall_status = report.overall_status
        if run_tof and not ship_out.is_detection_cancelled():
            detector.run_tof_detection(fps_dir, sn_list)

        # 被手动停止时，整体状态标记为 STOPPED（区别于异常 FAIL）
        if ship_out.is_detection_cancelled():
            overall_status = "STOPPED"

        # 6. 收尾
        self._log("[6/6] 检测完成，清理资源...")
        ship_out.LogManager.cleanup()

        # 扫描任务目录生成 artifacts_json（相对任务目录的文件名列表，T3）
        artifacts = sorted(
            n for n in os.listdir(result_dir) if not n.startswith(".")
        ) if os.path.isdir(result_dir) else []

        self._log(f"检测结束，整体状态: {overall_status}")
        return {
            "result_dir_path": result_dir,
            "rel_path": rel_path,
            "date_key": date_key,
            "log_rel_path": os.path.join(rel_path, "run.log"),
            "artifacts": artifacts,
            "overall_status": overall_status,
            "summary": summary,
        }
