# -*- coding: utf-8 -*-
"""操作记录（审计）查询与导出（T9）"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import DATA_DIR
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.utils.logger import logger

# 注意：prefix 必须与 /api/history 分开，否则 /operations/export 会被
# history 的 /{kind}/{task_uuid} 动态路由抢先匹配（kind="operations" → 400）
router = APIRouter(prefix="/api/operations", tags=["history"])


def _op_to_dict(o) -> dict:
    return {
        "id": o.id,
        "ts": o.ts.isoformat() if o.ts else None,
        "action": o.action,
        "kind": o.kind,
        "task_uuid": o.task_uuid,
        "sn": o.sn,
        "params_json": o.params_json,
        "result": o.result,
        "detail": o.detail,
    }


@router.get("")
async def operations_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    action: Optional[str] = None,
    kind: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    async with AsyncSessionLocal() as session:
        rows, total = await crud.list_operation_logs(
            session, page, size, action, kind, date_from, date_to
        )
    return {"items": [_op_to_dict(r) for r in rows],
            "total": total, "page": page, "size": size}


@router.get("/export")
async def operations_export(
    action: Optional[str] = None,
    kind: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """按当前筛选导出 CSV：落 {DATA_DIR}/exports/operation_logs_{ts}.csv 后 FileResponse；导出本身也写审计"""
    async with AsyncSessionLocal() as session:
        rows, _ = await crud.list_operation_logs(
            session, 1, 100000, action, kind, date_from, date_to
        )

    export_dir = os.path.join(DATA_DIR, "exports")
    os.makedirs(export_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(export_dir, f"operation_logs_{ts}.csv")

    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["时间", "操作", "类型", "任务UUID", "SN", "结果", "详情"])
            for o in rows:
                writer.writerow([
                    o.ts.isoformat() if o.ts else "",
                    o.action or "",
                    o.kind or "",
                    o.task_uuid or "",
                    o.sn or "",
                    o.result or "",
                    o.detail or "",
                ])
    except OSError as e:
        logger.error(f"[ops] 导出 CSV 失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

    # 导出本身写审计（T8/T9）
    try:
        await audit(action="export_operations", kind="system",
                    params={"action": action, "kind": kind,
                            "date_from": date_from, "date_to": date_to})
    except Exception:  # noqa: BLE001
        pass

    return FileResponse(
        path=csv_path,
        filename=os.path.basename(csv_path),
        media_type="text/csv",
    )
