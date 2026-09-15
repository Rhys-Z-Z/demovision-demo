# -*- coding: utf-8 -*-
"""操作审计服务（T2）：所有 Web 变更操作写审计表，失败只记日志不阻断业务（R6）"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db.database import AsyncSessionLocal
from app.db.models import OperationLog
from app.utils.logger import logger


async def audit(
    action: str,
    kind: Optional[str] = None,
    task_uuid: Optional[str] = None,
    sn: Optional[str] = None,
    params: Any = None,
    result: str = "ok",
    detail: Optional[str] = None,
) -> None:
    """写入一条操作审计；任何异常只记 warning，绝不阻断主流程（R6）。"""
    try:
        params_json = None
        if params is not None:
            try:
                params_json = json.dumps(params, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                params_json = str(params)
        async with AsyncSessionLocal() as session:
            session.add(OperationLog(
                action=action,
                kind=kind,
                task_uuid=task_uuid,
                sn=sn,
                params_json=params_json,
                result=result,
                detail=detail,
            ))
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] 写入操作审计失败（不阻断）: {e}")