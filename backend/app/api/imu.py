# -*- coding: utf-8 -*-
"""IMU 陀螺仪校准任务接口"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import DATA_DIR, DEMO_MODE
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.services.demo.demo_devices import DEMO_USB_DEVICES
from app.services.imu_calib_service import IMUCalibRunner
from app.utils.logger import logger
from app.utils.paths import imu_rel, date_key_of
from app.websocket.manager import manager

router = APIRouter(prefix="/api/imu", tags=["imu"])

# DemoVision vSLAM 的 USB VID:PID（lsusb 中显示为 "040e:f408 MCCI DemoVision vSLAM"）
_DEMOVISION_USB_ID = "040e:f408"


def _usb_serial(bus: str, dev: str) -> str:
    """通过 udevadm 尝试读取 USB 设备序列号，失败返回空串"""
    try:
        proc = subprocess.run(
            ["udevadm", "info", "--query=property", "--name=/dev/bus/usb/%s/%s" % (bus, dev)],
            capture_output=True, text=True, timeout=5,
        )
        for kv in proc.stdout.splitlines():
            if kv.startswith("ID_SERIAL_SHORT="):
                return kv.split("=", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _detect_usb_demovision() -> List[str]:
    """通过 lsusb 检测 DemoVision vSLAM 设备（无需 ROS/SDK），返回设备标识列表"""
    try:
        proc = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        lines = proc.stdout.splitlines()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[imu] lsusb 执行失败: {e}")
        return []
    devices: List[str] = []
    for line in lines:
        if _DEMOVISION_USB_ID not in line:
            continue
        m = re.search(r"Bus (\d+) Device (\d+):", line)
        if m:
            bus, dev = m.group(1), m.group(2)
            sn = _usb_serial(bus, dev)
            # 拿不到 SN 时使用 USB 位置作为设备标识（脚本本身无需 SN）
            devices.append(sn if sn else f"DemoVision-vSLAM-USB-B{bus}D{dev}")
        else:
            devices.append("DemoVision-vSLAM-USB")
    return devices


def get_date_dir() -> str:
    """兼容遗留：与 ship_out.get_date_dir() 一致的日期目录绝对路径"""
    return os.path.join(DATA_DIR, date_key_of())


class CalibrateRequest(BaseModel):
    devices: List[str] = Field(default_factory=list)
    duration: float = Field(default=5.0, ge=1.0, le=120.0)


@router.get("/devices")
async def imu_devices():
    """检测 DemoVision vSLAM USB 设备（demo 模式返回模拟 USB 列表）"""
    if DEMO_MODE:
        return {"devices": list(DEMO_USB_DEVICES), "count": len(DEMO_USB_DEVICES)}
    loop = asyncio.get_running_loop()
    devices = await loop.run_in_executor(None, _detect_usb_demovision)
    return {"devices": devices, "count": len(devices)}


@router.post("/calibrate")
async def calibrate(req: CalibrateRequest):
    """启动 IMU 陀螺仪校准（取第一个设备执行，产物落在日期目录下）"""
    if not req.devices:
        return {"error": "请选择设备 SN"}

    task_uuid = str(uuid.uuid4())
    sn = req.devices[0]

    # 落盘规则：日期根下的 imu_calib_{uuid8} 子目录（IMU 无法可靠获取 SN，不归入 SN 层，R3/目标1）
    date_key = date_key_of()
    rel_path = imu_rel(date_key, task_uuid[:8])
    result_dir = os.path.join(DATA_DIR, rel_path)
    os.makedirs(result_dir, exist_ok=True)

    async with AsyncSessionLocal() as session:
        await crud.create_imu_calib_task(session, task_uuid, sn)

    asyncio.create_task(_run_imu_calib(task_uuid, result_dir, req.duration))
    # 审计（T8）：start_imu
    asyncio.create_task(audit(
        action="start_imu", kind="imu_calib", task_uuid=task_uuid, sn=sn,
        params={"duration": req.duration, "devices": req.devices},
    ))
    return {
        "task_uuid": task_uuid, "sn": sn, "result_dir": result_dir,
        "rel_path": rel_path, "status": "running",
    }


async def _run_imu_calib(task_uuid: str, result_dir: str, duration: float) -> None:
    runner = IMUCalibRunner(task_uuid, result_dir, manager.broadcast)
    try:
        await runner.run(duration)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[imu] 校准任务异常: {e}")
        try:
            async with AsyncSessionLocal() as session:
                await crud.finish_imu_calib_task(
                    session, task_uuid, result_dir, failed=True
                )
        except Exception:  # noqa: BLE001
            pass
        await manager.broadcast({
            "type": "task_finished", "task_uuid": task_uuid,
            "kind": "imu_calib", "status": "failed", "error": str(e),
        })


@router.get("/status/{task_uuid}")
async def imu_status(task_uuid: str):
    """查询校准任务最新状态（含产物路径与偏置结果）"""
    async with AsyncSessionLocal() as session:
        t = await crud.get_imu_calib_task(session, task_uuid)
    if t is None:
        return {"error": "任务不存在"}
    return {
        "task_uuid": t.task_uuid,
        "sn": t.sn,
        "start_time": t.start_time.isoformat() if t.start_time else None,
        "end_time": t.end_time.isoformat() if t.end_time else None,
        "status": t.status,
        "result_dir_path": t.result_dir_path,
        "rel_path": t.rel_path,
        "txt_file_path": t.txt_file_path,
        "bin_file_path": t.bin_file_path,
        "summary_json": t.summary_json,
        "qualified": t.qualified,
    }
