# -*- coding: utf-8 -*-
"""Demo 演示数据预置（幂等：逐表查空才播种）。

在 DEMO_MODE 启动时调用：为检测/SLAM/IMU/截图/审计各表预置演示记录，
并把对应产物（00_summary_report.txt / 轨迹 CSV / stats / PNG / 截图 / run.log）
落到 DEMOVISION_DATA_DIR，保证历史页、报告打印、下载在无硬件环境下开箱可用。

产物格式全部经 parser_service 回读生成 summary_json，口径与真实任务一致。
"""
from __future__ import annotations

import csv
import math
import os
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.config import DATA_DIR, DEMO_MODE
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.db.models import OperationLog
from app.services.demo.demo_devices import DEMO_SERIALS
from app.services.demo.demo_frames import plot_trajectory_png, render_frame
from app.services.parser_service import (parse_detection_summary,
                                         parse_imu_calibration_result,
                                         parse_slam_stats)
from app.utils.logger import logger
from app.utils.paths import (archive_slam_name, date_key_of, detection_rel,
                             imu_rel, picture_rel)

_SN = DEMO_SERIALS[0]
_SN8 = _SN[-8:]

# ============ 产物生成 ============

def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


def _write_detection_products(date_key: str, sn: str, suffix: str,
                              hhmmss: str, overall: str) -> str:
    """生成检测任务产物，返回 rel_path"""
    rel = detection_rel(date_key, [sn], suffix, hhmmss)
    abs_dir = os.path.join(DATA_DIR, rel)
    fps = os.path.join(abs_dir, "fps")
    os.makedirs(fps, exist_ok=True)

    if overall == "PASS":
        summary_lines = [
            "=" * 60,
            "DemoVision 设备检测汇总报告（DEMO 演示数据）",
            "=" * 60,
            f"生成时间: {hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]}",
            f"检测设备: {sn[-8:]}",
            "",
            "设备总数: 1",
            "Color相机通过: 1/1",
            "Fisheye通过: 1/1",
            "SLAM通过: 1/1",
            "Color通过率: 100.0%",
            "Fisheye通过率: 100.0%",
            "SLAM通过率: 100.0%",
            "",
            "整体检测状态: PASS",
            "=" * 60,
        ]
        color_txt = "Color 相机检测报告（DEMO）\n通过: 1/1    通过率: 100.0%"
        fish_txt = "Fisheye 检测报告（DEMO）\n通过: 1/1    通过率: 100.0%"
        slam_txt = "SLAM 检测报告（DEMO）\n通过: 1/1    通过率: 100.0%"
    else:
        summary_lines = [
            "=" * 60,
            "DemoVision 设备检测汇总报告（DEMO 演示数据）",
            "=" * 60,
            f"生成时间: {hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]}",
            f"检测设备: {sn[-8:]}",
            "",
            "设备总数: 1",
            "Color相机通过: 0/1",
            "Fisheye通过: 1/1",
            "SLAM通过: 1/1",
            "Color通过率: 0.0%",
            "Fisheye通过率: 100.0%",
            "SLAM通过率: 100.0%",
            "",
            "整体检测状态: FAIL",
            "=" * 60,
        ]
        color_txt = "Color 相机检测报告（DEMO）\n通过: 0/1    通过率: 0.0%"
        fish_txt = "Fisheye 检测报告（DEMO）\n通过: 1/1    通过率: 100.0%"
        slam_txt = "SLAM 检测报告（DEMO）\n通过: 1/1    通过率: 100.0%"

    _write(os.path.join(fps, "00_summary_report.txt"), "\n".join(summary_lines))
    _write(os.path.join(fps, "01_color_report.txt"), color_txt)
    _write(os.path.join(fps, "02_fisheye_report.txt"), fish_txt)
    _write(os.path.join(fps, "03_slam_report.txt"), slam_txt)
    _write(os.path.join(abs_dir, "run.log"),
           "\n".join([
               "[任务] 检测启动 | 模式: 全功能 | 设备类型: 测试",
               "[1/6] 检查环境...",
               "[2/6] 扫描在线设备...",
               f"参与检测设备: {sn[-8:]}",
               "[3/6] 加载设备版本信息...",
               "[4/6] 准备输出目录...",
               "[5/6] 开始检测...",
               "[Color相机] 完成: 1/1 通过" if overall == "PASS" else "[Color相机] 完成: 0/1 通过",
               "[Fisheye] 完成: 1/1 通过",
               "[SLAM] 完成: 1/1 通过",
               "[6/6] 检测完成，清理资源...",
               f"检测结束，整体状态: {overall}",
           ]))
    return rel


def _write_slam_products(date_key: str, sn: str, hhmmss: str,
                         qualified: bool) -> str:
    """生成 SLAM 任务产物（csv + stats + png + run.log），返回 rel_path"""
    sn8 = sn[-8:]
    name = archive_slam_name(sn8, datetime.strptime(hhmmss, "%H%M%S"))
    rel = f"{date_key}/{sn}/{name}"
    abs_dir = os.path.join(DATA_DIR, rel)
    os.makedirs(abs_dir, exist_ok=True)

    stem = f"{sn8}_{hhmmss}"
    csv_path = os.path.join(abs_dir, f"{stem}.csv")
    rng = random.Random(7 if qualified else 8)
    n = 600
    dist_mean = 0.0 if qualified else 2.8
    dist_std = 0.8 if qualified else 1.6
    dists: list = []
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_since_start_s", "absolute_time",
                         "x_m", "y_m", "z_m", "distance_mm"])
        base_ts = datetime.now()
        for i in range(n):
            t = i * 0.02
            x = 0.6 * math.sin(2 * math.pi * 0.2 * t) + rng.gauss(0, 0.004)
            y = 0.6 * math.sin(2 * math.pi * 0.17 * t + 0.6) + rng.gauss(0, 0.004)
            z = rng.gauss(0, 0.003)
            d = rng.gauss(dist_mean, dist_std)
            dists.append(d)
            ts = base_ts + timedelta(seconds=t)
            writer.writerow([
                f"{t:.3f}", ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                f"{x:.6f}", f"{y:.6f}", f"{z:.6f}", f"{d:.3f}",
            ])
    mean = sum(dists) / n
    std = (sum((d - mean) ** 2 for d in dists) / n) ** 0.5
    low, high = mean - 3 * std, mean + 3 * std
    is_q = low >= -4.0 and high <= 4.0
    _write(os.path.join(abs_dir, f"{stem}_stats.txt"), "\n".join([
        "=" * 50,
        "DemoVision SLAM 统计报告（DEMO 演示数据）",
        "=" * 50,
        f"平均欧式距离 (Mean): {mean:.2f} mm",
        f"标准差 (Std): {std:.2f} mm",
        f"3σ 区间: [{low:.2f}, {high:.2f}] mm",
        f"合格性判断: {'合格' if is_q else '不合格'}",
        f"有效数据点数: {n}",
        "=" * 50,
    ]))
    plot_trajectory_png(csv_path, os.path.join(abs_dir, f"{stem}.png"))
    _write(os.path.join(abs_dir, "run.log"), "\n".join([
        "[SLAM] DemoVision SLAM 录制启动（DEMO）",
        f"[SLAM] 设备 {sn8} 开始录制...",
        f"[SLAM] {sn8} 录制完成，共 {n} 点",
        "[SLAM] 录制结束",
    ]))
    return rel


def _write_imu_products(date_key: str, uuid8: str) -> str:
    """生成 IMU 校准任务产物（imu_calib_after.txt/.bin + run.log），返回 rel_path"""
    rel = imu_rel(date_key, uuid8)
    abs_dir = os.path.join(DATA_DIR, rel)
    os.makedirs(abs_dir, exist_ok=True)
    _write(os.path.join(abs_dir, "imu_calib_before.txt"),
           "DemoVision IMU calibration (DEMO)\nStage: before\nGyroBias= 0.0000 0.0000 0.0000")
    _write(os.path.join(abs_dir, "imu_calib_after.txt"),
           "DemoVision IMU calibration (DEMO)\nStage: after\nGyroBias= 0.0012 -0.0008 0.0003\nResult: pass")
    with open(os.path.join(abs_dir, "imu_calib_after.bin"), "wb") as f:
        f.write(b"DEMO-BIAS-0.0012--0.0008-0.0003\n")
    _write(os.path.join(abs_dir, "imu_calib_run.log"), "\n".join([
        "[1/3] reset: 重置陀螺仪偏置...",
        "[2/3] calib: 采集陀螺仪数据并计算偏置...",
        "[3/3] verify: 校验校准结果...",
        "      GyroBias= 0.0012 -0.0008 0.0003",
        "DemoVision IMU 校准完成",
    ]))
    return rel


# ============ 播种 ============

async def _table_empty(session, model) -> bool:
    total = (await session.execute(select(func.count()).select_from(model))).scalar() or 0
    return total == 0


async def seed_demo_data() -> None:
    if not DEMO_MODE:
        return
    date_key = date_key_of()

    async with AsyncSessionLocal() as session:
        # 1. 检测任务 ×2（PASS / FAIL）
        if await _table_empty(session, crud.DetectionTask):
            for i, (overall, hh) in enumerate([("PASS", "093012"), ("FAIL", "101512")], 1):
                task_uuid = str(uuid.uuid4())
                await crud.create_detection_task(
                    session, task_uuid, "测试", "全功能", _SN)
                rel = _write_detection_products(date_key, _SN, _SN8, hh, overall)
                abs_dir = os.path.join(DATA_DIR, rel)
                summary = parse_detection_summary(
                    os.path.join(abs_dir, "fps", "00_summary_report.txt")) or {}
                artifacts = sorted(n for n in os.listdir(abs_dir)
                                   if not n.startswith("."))
                await crud.finish_detection_task(
                    session, task_uuid, abs_dir, overall, summary,
                    failed=False, rel_path=rel, date_key=date_key,
                    log_rel_path=os.path.join(rel, "run.log"),
                    artifacts=artifacts)
            logger.info(f"[seed] detection_tasks 已播种 2 条（PASS/FAIL）")

        # 2. SLAM 会话 ×2（合格 / 不合格）
        if await _table_empty(session, crud.SlamSession):
            for i, (qualified, hh) in enumerate([(True, "110202"), (False, "115622")], 1):
                task_uuid = str(uuid.uuid4())
                await crud.create_slam_session(
                    session, task_uuid, _SN, 60.0,
                    os.path.join(DATA_DIR, date_key, _SN))
                rel = _write_slam_products(date_key, _SN, hh, qualified)
                abs_dir = os.path.join(DATA_DIR, rel)
                stats_file = os.path.join(abs_dir, f"{_SN8}_{hh}_stats.txt")
                stats = parse_slam_stats(stats_file) or {}
                csv_path = os.path.join(abs_dir, f"{_SN8}_{hh}.csv")
                png_path = os.path.join(abs_dir, f"{_SN8}_{hh}.png")
                artifacts = sorted(n for n in os.listdir(abs_dir)
                                   if not n.startswith("."))
                await crud.finish_slam_session(
                    session, task_uuid,
                    csv_path=csv_path, png_path=png_path,
                    stats_text=stats.get("raw_text", ""),
                    is_qualified=stats.get("is_qualified"),
                    mean_mm=stats.get("mean_mm"),
                    std_mm=stats.get("std_mm"),
                    failed=False, rel_path=rel, date_key=date_key,
                    log_rel_path=os.path.join(rel, "run.log"),
                    artifacts=artifacts, output_dir_path=abs_dir)
            logger.info("[seed] slam_sessions 已播种 2 条（合格/不合格）")

        # 3. IMU 校准 ×1（合格）
        if await _table_empty(session, crud.ImuCalibTask):
            task_uuid = str(uuid.uuid4())
            uuid8 = task_uuid[:8]
            await crud.create_imu_calib_task(session, task_uuid, _SN)
            rel = _write_imu_products(date_key, uuid8)
            abs_dir = os.path.join(DATA_DIR, rel)
            summary = parse_imu_calibration_result(abs_dir) or {}
            artifacts = sorted(n for n in os.listdir(abs_dir)
                               if not n.startswith("."))
            await crud.finish_imu_calib_task(
                session, task_uuid, abs_dir,
                txt_path=os.path.join(abs_dir, "imu_calib_after.txt"),
                bin_path=os.path.join(abs_dir, "imu_calib_after.bin"),
                summary=summary, qualified=True, failed=False,
                rel_path=rel, date_key=date_key,
                log_rel_path=os.path.join(rel, "imu_calib_run.log"),
                artifacts=artifacts)
            logger.info("[seed] imu_calibration_tasks 已播种 1 条（合格）")

        # 4. 截图 ×2
        if await _table_empty(session, crud.Screenshot):
            for i, hh in enumerate(["094512", "123044"], 1):
                rel_dir = picture_rel(date_key, _SN)
                abs_dir = os.path.join(DATA_DIR, rel_dir)
                os.makedirs(abs_dir, exist_ok=True)
                name = f"snapshot_{hh}000{i}.jpg"
                jpg = render_frame(f"/dv_sdk/{_SN}/color/image")
                if jpg:
                    with open(os.path.join(abs_dir, name), "wb") as f:
                        f.write(jpg)
                rel_file = os.path.join(rel_dir, name)
                await crud.create_screenshot(
                    session, sn=_SN,
                    topic=f"/dv_sdk/{_SN}/color/image",
                    date_key=date_key, rel_path=rel_file,
                    file_size=len(jpg or b""))
            logger.info("[seed] screenshots 已播种 2 条")

        # 5. 操作审计 ×9
        if await _table_empty(session, OperationLog):
            now = datetime.now()
            ops = [
                ("start_detection", "detection", _SN, {"mode": "全功能"}, "ok", "检测任务启动（DEMO）"),
                ("finish_detection", "detection", _SN, {}, "ok", "整体检测状态: PASS"),
                ("start_slam", "slam", _SN, {"duration": 60}, "ok", "SLAM 录制启动（DEMO）"),
                ("finish_slam", "slam", _SN, {}, "ok", "SLAM 归档完成，合格"),
                ("start_imu", "imu_calib", _SN, {"duration": 5}, "ok", "IMU 校准启动（DEMO）"),
                ("finish_imu", "imu_calib", _SN, {}, "ok", "校准合格"),
                ("snapshot", "snapshot", _SN, {"topic": "/dv_sdk/" + _SN + "/color/image"}, "ok", "实时截图（DEMO）"),
                ("snapshot_download", "snapshot", _SN, {}, "ok", "下载截图文件"),
                ("download_file", "detection", _SN, {}, "ok", "下载检测报告"),
            ]
            for i, (action, kind, sn, params, result, detail) in enumerate(ops):
                session.add(OperationLog(
                    ts=now - timedelta(minutes=13 * (len(ops) - i)),
                    action=action, kind=kind, sn=sn,
                    params_json=__import__("json").dumps(params, ensure_ascii=False),
                    result=result, detail=detail,
                ))
            await session.commit()
            logger.info("[seed] operation_logs 已播种 9 条")
