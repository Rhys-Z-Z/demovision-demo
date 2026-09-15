# -*- coding: utf-8 -*-
"""检测任务接口"""
from __future__ import annotations

import asyncio
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.services import detection_runner
from app.services.detection_runner import DetectionRunner
from app.websocket.manager import manager

router = APIRouter(prefix="/api/detection", tags=["detection"])

VALID_MODES = {"仅相机", "仅ToF", "全功能"}
VALID_TYPES = {"平动", "非平动", "测试", "头箍式", "简易式"}

# 当前正在运行的检测任务（同一时间仅允许一个检测任务）
_running_task: Optional[str] = None


class DetectionStartRequest(BaseModel):
    devices: List[str] = Field(default_factory=list)
    mode: str = "全功能"
    device_type: str = "平动"
    # 各检测项目时长（秒），缺省则用 ship_out 默认值
    times: Dict[str, int] = Field(default_factory=dict)


@router.post("/start")
async def start_detection(req: DetectionStartRequest):
    global _running_task
    if req.mode not in VALID_MODES:
        return {"error": f"非法检测模式: {req.mode}，可选 {sorted(VALID_MODES)}"}
    if req.device_type not in VALID_TYPES:
        return {"error": f"非法设备类型: {req.device_type}，可选 {sorted(VALID_TYPES)}"}
    if _running_task:
        return {"error": "已有检测任务在运行，请先停止当前任务"}
    if not req.devices:
        return {"error": "请至少选择一个设备"}

    task_uuid = str(uuid.uuid4())
    devices_sn = ",".join(req.devices)

    async with AsyncSessionLocal() as session:
        await crud.create_detection_task(
            session, task_uuid, req.device_type, req.mode, devices_sn
        )

    _running_task = task_uuid

    asyncio.create_task(
        _run_detection_task(task_uuid, req.devices, req.mode, req.device_type, req.times)
    )
    # 审计（T8）：start_detection
    asyncio.create_task(audit(
        action="start_detection", kind="detection", task_uuid=task_uuid,
        sn=",".join(req.devices) or None,
        params={"mode": req.mode, "device_type": req.device_type,
                "devices": req.devices, "times": req.times},
    ))
    return {"task_uuid": task_uuid, "status": "running", "mode": req.mode}


@router.post("/stop/{task_uuid}")
async def stop_detection(task_uuid: str):
    """手动停止正在运行的检测任务（尽力中断当前检测项，尽快返回）"""
    if task_uuid != _running_task:
        raise HTTPException(status_code=404, detail="没有匹配的运行中检测任务")
    detection_runner.request_cancel_detection()
    # 审计（T8）：stop_detection
    asyncio.create_task(audit(
        action="stop_detection", kind="detection", task_uuid=task_uuid,
        params={"source": "manual"},
    ))
    await manager.broadcast({
        "type": "log_message", "task_uuid": task_uuid,
        "line": ">>> 收到停止指令，正在中断检测...",
    })
    return {"task_uuid": task_uuid, "status": "stopping"}


async def _run_detection_task(task_uuid: str, devices: List[str],
                              mode: str, device_type: str,
                              times: Optional[dict] = None) -> None:
    global _running_task
    loop = asyncio.get_running_loop()
    runner = DetectionRunner(loop, manager.broadcast)
    try:
        result = await loop.run_in_executor(
            None, runner.run, task_uuid, devices, mode, device_type, times
        )
        async with AsyncSessionLocal() as session:
            await crud.finish_detection_task(
                session, task_uuid,
                result["result_dir_path"], result["overall_status"],
                result["summary"],
                rel_path=result.get("rel_path"),
                date_key=result.get("date_key"),
                log_rel_path=result.get("log_rel_path"),
                artifacts=result.get("artifacts"),
            )
        await manager.broadcast({
            "type": "task_finished", "task_uuid": task_uuid,
            "kind": "detection", "status": "finished",
            "overall_status": result["overall_status"],
            "stopped": result["overall_status"] == "STOPPED",
        })
    except Exception as e:  # noqa: BLE001
        async with AsyncSessionLocal() as session:
            await crud.finish_detection_task(
                session, task_uuid, "", "FAIL", {}, failed=True
            )
        await manager.broadcast({
            "type": "task_finished", "task_uuid": task_uuid,
            "kind": "detection", "status": "failed", "error": str(e),
        })
    finally:
        if _running_task == task_uuid:
            _running_task = None
