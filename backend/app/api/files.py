# -*- coding: utf-8 -*-
"""文件下载代理（防目录穿越）——兜底接口，仅用于遗留页面。

⚠️ 新功能禁止使用本接口，一律走 /api/history/{kind}/{uuid}/files/{name}（白名单下载，T6）。
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import DATA_DIR
from app.utils.paths import is_under_data_dir

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/download")
async def download_file(path: str = Query(..., description="base64 编码的目标文件绝对路径")):
    """安全下载代理：仅允许数据根目录（DATA_DIR）前缀下的文件（realpath + DATA_DIR/ 前缀校验，R5）"""
    try:
        decoded = base64.b64decode(path.encode("utf-8")).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="路径解码失败")

    real_path = os.path.realpath(decoded)

    # 防目录穿越：realpath 后必须位于 DATA_DIR + os.sep 前缀之下（T7 加固）
    if not is_under_data_dir(real_path):
        raise HTTPException(status_code=403, detail="禁止访问该路径")

    if not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=real_path,
        filename=os.path.basename(real_path),
        media_type="application/octet-stream",
    )
