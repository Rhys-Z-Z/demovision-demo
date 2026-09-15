# -*- coding: utf-8 -*-
"""全局配置常量（FHS 标准，支持环境变量覆盖）

路径策略（代码/数据解耦，跨机器部署）：
    - 程序本体（脚本/工具/后端）：/opt/demovision_web
    - 业务数据（测试产物落盘区）：/var/lib/demovision_web/data
    - 系统数据库：/var/lib/demovision_web/db

以上为 FHS 标准默认值；可通过环境变量覆盖，以便在开发/测试机使用本地落盘位置
（例如 $HOME/demovision_data）。相应地：
    - ship_out.py / slam_plotter_final.py 通过 %DEMOVISION_DATA_DIR% 读取数据根目录
      （demo 版默认 $HOME/demovision_data 兜底）。
    - 后端各子进程启动任务时注入 %DEMOVISION_DATA_DIR%（见 detection_runner / slam.py / imu_calib_service.py）。

Demo 模式：
    - DEMOVISION_DEMO_MODE != "0" 即开启（默认开）。demo 模式下用模拟数据源替换
      实时/系统状态类服务（SLAM pose、视频帧、ROS 话题、SDK 状态、USB 检测），
      并在启动时预置演示数据（seed_demo_data），无硬件/ROS 也能完整演示全部页面。
    - 设 DEMOVISION_DEMO_MODE=0 可切回真实模式（需要 ROS/SDK/硬件环境）。
"""
from __future__ import annotations

import os
from pathlib import Path

# ===== Demo 模式开关（默认开启；显式设为 "0" 关闭） =====
DEMO_MODE = os.environ.get("DEMOVISION_DEMO_MODE", "1") != "0"

# ===== FHS 标准目录（可用环境变量覆盖以兼容开发环境） =====
APP_DIR = os.environ.get("DEMOVISION_APP_DIR", "/opt/demovision_web")
DATA_DIR = os.environ.get("DEMOVISION_DATA_DIR", "/var/lib/demovision_web/data")
DB_DIR = os.environ.get("DEMOVISION_DB_DIR", "/var/lib/demovision_web/db")

# 确保目录存在（尽力而为：无写权限时不在此报错，避免未部署环境 import 崩溃）
for _d in (DATA_DIR, DB_DIR):
    try:
        Path(_d).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# 数据库路径
DB_PATH = os.path.join(DB_DIR, "demovision_meta.db")

# ===== 脚本与工具路径 =====
# 优先使用部署目录 /opt/demovision_web（install.sh 会拷贝脚本/工具进去）；
# 若当前是代码树环境（未部署），回退到自动探测脚本所在目录，保证开发可用。
# L2 源码保护：镜像内 scripts/ 为编译后 .so，故存在性探测要兼容 .py（开发）与 .so（镜像）。
def _has_slam_module(p: Path) -> bool:
    return (
        (p / "slam_plotter_final.py").exists()
        or bool(list(p.glob("slam_plotter_final*.so")))
    )

_script_candidates = [
    Path(__file__).resolve().parents[2] / "scripts",  # 代码树：demovision_web_system/scripts（自包含）
    Path(APP_DIR),                                    # 部署/容器：/opt/demovision_web
    Path(__file__).resolve().parents[3],              # 兜底：仓库根
]
SCRIPT_DIR = next(
    (p for p in _script_candidates if _has_slam_module(p)),
    Path(APP_DIR),
)

# SLAM 薄启动器（L2 源码保护：slam_plotter_final.so 不能脚本直跑，经其 import + main()）
# 与 slam_runner.py 同处 backend/ 根（= config.py 的 parents[1]）
SLAM_LAUNCHER = str(Path(__file__).resolve().parents[1] / "slam_runner.py")

# 检测核心脚本（通过 import 调用，严禁修改其逻辑）
SHIP_OUT_PATH = str(SCRIPT_DIR / "ship_out.py")

# SLAM 子进程超时保护（默认录制时长上限，秒）
SLAM_MAX_DURATION = 3600

# IMU 陀螺仪校准工具目录与执行脚本（无需 ROS，但需设备已连接 USB）
IMU_RUN_SCRIPT = "run_update_gyro_bias.sh"
_imu_candidates = [
    Path(APP_DIR) / "imu_tool",
    Path(__file__).resolve().parents[2] / "imu_tool",
]
IMU_TOOL_DIR = str(next(
    (p for p in _imu_candidates if (p / IMU_RUN_SCRIPT).exists()),
    _imu_candidates[0],
))