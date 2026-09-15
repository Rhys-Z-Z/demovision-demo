# -*- coding: utf-8 -*-
"""实时图像截图接口（S3）：web_video_server 抓帧 → 存 {DATA_DIR}/{日期}/{SN}/picture/ → 入库 + 审计。

接口前缀 /api 独立（严禁挂 /api/history/snapshots/*——会被 history 动态路由 /{kind}/{task_uuid}
抢匹配，operations 同坑先例）。截图走同步请求/响应，不走 task 流程、无需 WS。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import DATA_DIR, DEMO_MODE
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.services.demo.demo_frames import render_frame
from app.utils.logger import logger
from app.utils.paths import (date_key_of, is_under_data_dir, picture_rel)

router = APIRouter(prefix="/api", tags=["snapshot"])

# 与 video_streamer.WEB_VIDEO_SERVER_URL 同主机；/snapshot 抓单帧（原始分辨率 JPEG）
_SNAPSHOT_URL = "http://localhost:8080/snapshot?topic={topic}&type=ros_compressed"
_CAPTURE_TIMEOUT = 5.0


class SnapshotReq(BaseModel):
    sn: str = ""
    topic: str


def _validate_topic(topic: str) -> str:
    """SSRF 防护：仅允许 ROS 话题名（以单个 / 开头，且无 '..'、无 URL scheme/网络路径）"""
    t = (topic or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail="topic 不能为空")
    low = t.lower()
    if not t.startswith("/") or t.startswith("//") or ".." in t or any(
        s in low for s in ("http", "file:", "://")
    ):
        raise HTTPException(status_code=400, detail="topic 格式非法")
    return t


def _unique_screenshot_path(picture_dir: str, dt: datetime) -> tuple:
    """snapshot_{HHMMSSmmm}.jpg；同毫秒冲突追加 _1/_2 防覆盖"""
    base = f"snapshot_{dt:%H%M%S}{dt.microsecond // 1000:03d}"
    candidate = os.path.join(picture_dir, base + ".jpg")
    if not os.path.exists(candidate):
        return candidate, base + ".jpg"
    i = 1
    while True:
        name = f"{base}_{i}.jpg"
        candidate = os.path.join(picture_dir, name)
        if not os.path.exists(candidate):
            return candidate, name
        i += 1


@router.post("/snapshot")
async def capture_snapshot(req: SnapshotReq):
    """抓一帧存盘并入库；web_video_server 未运行 → 502 + 审计 failed"""
    topic = _validate_topic(req.topic)
    sn = (req.sn or "").strip()
    url = _SNAPSHOT_URL.format(topic=topic)

    # 1. 抓帧（真实模式：web_video_server /snapshot；demo 模式：本地渲染模拟帧）
    try:
        if DEMO_MODE:
            jpg = render_frame(topic)
            if not jpg:
                raise HTTPException(
                    status_code=502, detail="模拟图像渲染失败（缺少 Pillow）")
        else:
            async with httpx.AsyncClient(timeout=_CAPTURE_TIMEOUT) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502, detail=f"实时图像服务返回异常（{resp.status_code}）")
            jpg = resp.content
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"[snapshot] 抓帧失败: {e}")
        try:
            await audit(action="snapshot", kind="snapshot", sn=sn or None,
                        result="failed", detail="实时图像服务未运行或抓帧失败")
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(
            status_code=502, detail="实时图像服务（web_video_server）未运行，无法截图")

    # 2. 落盘 {DATA_DIR}/{date_key}/{sn}/picture/
    date_key = date_key_of()
    rel_dir = picture_rel(date_key, sn)
    abs_dir = os.path.join(DATA_DIR, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    full_path, filename = _unique_screenshot_path(abs_dir, datetime.now())
    try:
        with open(full_path, "wb") as f:
            f.write(jpg)
    except OSError as e:  # noqa: BLE001
        logger.error(f"[snapshot] 写盘失败: {e}")
        raise HTTPException(status_code=500, detail=f"截图写盘失败: {e}")
    file_size = os.path.getsize(full_path)
    rel_file = os.path.join(rel_dir, filename)

    # 3. 入库
    async with AsyncSessionLocal() as session:
        row = await crud.create_screenshot(
            session, sn=sn or None, topic=topic,
            date_key=date_key, rel_path=rel_file, file_size=file_size,
        )

    # 4. 审计
    try:
        await audit(action="snapshot", kind="snapshot", sn=sn or None,
                    params={"topic": topic, "filename": filename,
                            "rel_path": rel_file})
    except Exception:  # noqa: BLE001
        pass

    return {
        "id": row.id, "sn": row.sn, "rel_path": rel_file, "filename": filename,
        "ts": row.ts.isoformat() if row.ts else None, "file_size": file_size,
        "date_key": date_key,
    }


@router.get("/snapshots")
async def list_snapshots(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sn: Optional[str] = None,
):
    """分页 + 筛选（按 ts，非 date_key 字符串比较）"""
    async with AsyncSessionLocal() as session:
        rows, total = await crud.list_screenshots(
            session, page, size, date_from, date_to, sn)
    items = [{
        "id": r.id,
        "ts": r.ts.isoformat() if r.ts else None,
        "sn": r.sn,
        "topic": r.topic,
        "file_size": r.file_size,
        "date_key": r.date_key,
        "rel_path": r.rel_path,
        "filename": os.path.basename(r.rel_path) if r.rel_path else None,
    } for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/snapshots/{shot_id}/file")
async def snapshot_file(shot_id: int):
    """截图原图下载：realpath + is_under_data_dir 校验 + 审计"""
    async with AsyncSessionLocal() as session:
        row = await crud.get_screenshot(session, shot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="截图不存在")
    if not row.rel_path:
        raise HTTPException(status_code=404, detail="截图记录缺少路径")
    real = os.path.realpath(os.path.join(DATA_DIR, row.rel_path))
    if not is_under_data_dir(real):
        raise HTTPException(status_code=403, detail="路径越权")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="截图文件不存在")

    try:
        await audit(action="snapshot_download", kind="snapshot",
                    sn=row.sn or None,
                    params={"shot_id": shot_id,
                            "filename": os.path.basename(real)})
    except Exception:  # noqa: BLE001
        pass

    return FileResponse(
        path=real, filename=os.path.basename(real),
        media_type="image/jpeg",
        content_disposition_type="inline",  # 原图预览用 inline，浏览器内嵌显示而非下载
    )