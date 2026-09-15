# -*- coding: utf-8 -*-
"""历史记录查询接口（T6 扩展：筛选 / 详情 / zip 下载 / 白名单单文件 / 打印报告）"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.config import DATA_DIR
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.services.parser_service import find_latest_file, parse_slam_trajectory
from app.utils.logger import logger
from app.utils.paths import abs_of, date_key_of, is_under_data_dir

router = APIRouter(prefix="/api/history", tags=["history"])

_BIG_FILE = 50 * 1024 * 1024  # 50MB 标注 big


def _dir_size(p: str) -> int:
    """递归统计目录总字节数（Web 历史里让 fps 等目录能显示真实大小）"""
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total

_MEDIA_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
}


def _media_type_for(name: str) -> str:
    """按扩展名给可内嵌预览的 media_type；未知类型兜底 octet-stream"""
    ext = os.path.splitext(name or "")[1].lower()
    return _MEDIA_BY_EXT.get(ext, "application/octet-stream")


def _dt(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


def _date_to_key(s: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DD' → date_key 前缀 'YYYY_Mon'（date_to 当日含尾在 SQL 用 date_from<=dk AND dk<=date_to 处理）"""
    if not s:
        return None
    try:
        d = date.fromisoformat(s)
    except ValueError:
        return None
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{d.year}_{months[d.month]}"


def _detection_to_dict(t) -> dict:
    return {
        "id": t.id,
        "task_uuid": t.task_uuid,
        "start_time": _dt(t.start_time),
        "end_time": _dt(t.end_time),
        "status": t.status,
        "device_type": t.device_type,
        "test_mode": t.test_mode,
        "devices_sn": t.devices_sn,
        "result_dir_path": t.result_dir_path,
        "rel_path": t.rel_path,
        "date_key": t.date_key,
        "overall_status": t.overall_status,
        "summary_json": t.summary_json,
        "artifacts_json": t.artifacts_json,
    }


def _slam_to_dict(s) -> dict:
    return {
        "id": s.id,
        "task_uuid": s.task_uuid,
        "sn": s.sn,
        "start_time": _dt(s.start_time),
        "end_time": _dt(s.end_time),
        "status": s.status,
        "duration_sec": s.duration_sec,
        "output_dir_path": s.output_dir_path,
        "rel_path": s.rel_path,
        "date_key": s.date_key,
        "csv_file_path": s.csv_file_path,
        "png_file_path": s.png_file_path,
        "stats_text": s.stats_text,
        "is_qualified": s.is_qualified,
        "mean_dist_mm": s.mean_dist_mm,
        "std_dist_mm": s.std_dist_mm,
        "artifacts_json": s.artifacts_json,
    }


def _imu_to_dict(t) -> dict:
    return {
        "id": t.id,
        "task_uuid": t.task_uuid,
        "sn": t.sn,
        "start_time": _dt(t.start_time),
        "end_time": _dt(t.end_time),
        "status": t.status,
        "result_dir_path": t.result_dir_path,
        "rel_path": t.rel_path,
        "date_key": t.date_key,
        "txt_file_path": t.txt_file_path,
        "bin_file_path": t.bin_file_path,
        "summary_json": t.summary_json,
        "qualified": t.qualified,
        "artifacts_json": t.artifacts_json,
    }


async def _get_task(kind: str, task_uuid: str):
    """按 kind 取任务记录，不存在返回 None"""
    async with AsyncSessionLocal() as session:
        if kind == "detection":
            return await crud.get_detection_task(session, task_uuid)
        if kind == "slam":
            return await crud.get_slam_session(session, task_uuid)
        if kind == "imu":
            return await crud.get_imu_calib_task(session, task_uuid)
    return None


def _task_dir(t) -> Optional[str]:
    """任务绝对目录（优先 rel_path，旧数据回退绝对列）"""
    if getattr(t, "rel_path", None):
        return str(abs_of(t.rel_path))
    for attr in ("result_dir_path", "output_dir_path"):
        v = getattr(t, attr, None)
        if v:
            return v
    return None


def _task_dir_under(t) -> Optional[str]:
    """任务目录绝对路径，且必须位于 DATA_DIR 之下（R5 白名单前提）"""
    d = _task_dir(t)
    if d and is_under_data_dir(d):
        return d
    return None


async def _artifacts_list(t) -> list:
    """详情/下载白名单：优先 DB artifacts_json，否则实时扫描任务目录"""
    arts = getattr(t, "artifacts_json", None)
    if arts:
        try:
            parsed = json.loads(arts)
            if isinstance(parsed, list):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    d = _task_dir_under(t)
    if d and os.path.isdir(d):
        return sorted(n for n in os.listdir(d) if not n.startswith("."))
    return []


# ============ 列表（带筛选） ============

@router.get("/detection")
async def detection_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sn: Optional[str] = None,
    status: Optional[str] = None,
):
    async with AsyncSessionLocal() as session:
        rows, total = await crud.list_detection_tasks(
            session, page, size, date_from, date_to, sn, status
        )
    return {"items": [_detection_to_dict(r) for r in rows],
            "total": total, "page": page, "size": size}


@router.get("/slam")
async def slam_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sn: Optional[str] = None,
    status: Optional[str] = None,
    qualified: Optional[str] = None,
):
    async with AsyncSessionLocal() as session:
        rows, total = await crud.list_slam_sessions(
            session, page, size, date_from, date_to, sn, status, qualified
        )
    return {"items": [_slam_to_dict(r) for r in rows],
            "total": total, "page": page, "size": size}


@router.get("/imu")
async def imu_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sn: Optional[str] = None,
    status: Optional[str] = None,
    qualified: Optional[str] = None,
):
    async with AsyncSessionLocal() as session:
        rows, total = await crud.list_imu_calib_tasks(
            session, page, size, date_from, date_to, sn, status, qualified
        )
    return {"items": [_imu_to_dict(r) for r in rows],
            "total": total, "page": page, "size": size}


# ============ 详情 / 下载 / 报告 ============

@router.get("/slam/{task_uuid}/trajectory")
async def slam_trajectory(task_uuid: str, max_points: int = 2000):
    """把该 SLAM 任务的轨迹 CSV 解析成绘图序列 —— 让曲线**直接在网页里渲染**。

    为什么不复用 png_file_path：`slam_plotter_final.py` 的轨迹图依赖 GUI 动画窗口，
    后端以 MPLBACKEND=Agg 无头运行时不落 PNG（实测历史 37 个任务 png 数为 0），
    故曲线一律由 CSV 数据在前端 ECharts 里画，不依赖任何图片产物。

    声明在 `/{kind}/{task_uuid}` 之前，避免被动态路由抢匹配（同 README 坑 19）。
    """
    t = await _get_task("slam", task_uuid)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = _task_dir_under(t)
    if not d:
        raise HTTPException(status_code=404, detail="任务目录不存在")

    # 优先 DB 里记录的 csv 列（归档后仍有效）；回退任务目录内最新的 .csv
    csv_path = None
    v = getattr(t, "csv_file_path", None)
    if v and os.path.isfile(v) and is_under_data_dir(v):
        csv_path = v
    if not csv_path:
        cand = find_latest_file(d, ".csv")
        if cand and is_under_data_dir(cand):
            csv_path = cand
    if not csv_path:
        raise HTTPException(status_code=404, detail="该任务没有轨迹 CSV")

    n = max(200, min(int(max_points or 2000), 20000))
    data = parse_slam_trajectory(csv_path, max_points=n)
    if data is None:
        raise HTTPException(status_code=422, detail="轨迹 CSV 解析失败（列名或内容不符）")

    data["csv_name"] = os.path.basename(csv_path)
    data["task_uuid"] = task_uuid
    try:
        await audit(action="trajectory", kind="slam", task_uuid=task_uuid,
                    sn=getattr(t, "sn", None), params={"max_points": n})
    except Exception:  # noqa: BLE001
        pass
    return data


@router.get("/{kind}/{task_uuid}")
async def history_detail(kind: str, task_uuid: str):
    """详情 + artifacts 数组（文件名/大小/mtime，大小超 50MB 标 big:true）"""
    if kind not in ("detection", "slam", "imu"):
        raise HTTPException(status_code=400, detail="kind 非法")
    t = await _get_task(kind, task_uuid)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = _task_dir_under(t)
    artifacts = []
    for name in await _artifacts_list(t):
        p = os.path.join(d, name) if d else None
        entry = {"name": name, "big": False}
        if p and os.path.isdir(p):
            entry["type"] = "dir"
            entry["size"] = _dir_size(p)          # 目录也显示真实大小（fps 等不再为空）
        else:
            entry["type"] = "file"
        if p and os.path.isfile(p):
            entry["size"] = os.path.getsize(p)
            entry["mtime"] = datetime.fromtimestamp(
                os.path.getmtime(p)).isoformat()
            entry["big"] = entry["size"] > _BIG_FILE
        artifacts.append(entry)
    base = (_detection_to_dict if kind == "detection"
            else _slam_to_dict if kind == "slam" else _imu_to_dict)(t)
    return {"task": base, "artifacts": artifacts}


@router.get("/{kind}/{task_uuid}/download")
async def history_download(kind: str, task_uuid: str):
    """整目录 zip 下载：写入 {DATA_DIR}/.tmp/{uuid}.zip → FileResponse(background 删除) → finally 必删"""
    if kind not in ("detection", "slam", "imu"):
        raise HTTPException(status_code=400, detail="kind 非法")
    t = await _get_task(kind, task_uuid)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = _task_dir_under(t)
    if not d or not os.path.isdir(d):
        raise HTTPException(status_code=404, detail="任务目录不存在")

    tmp_dir = os.path.join(DATA_DIR, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    zip_path = os.path.join(tmp_dir, f"{task_uuid}.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            base = os.path.basename(d.rstrip(os.sep))
            for root, _, files in os.walk(d):
                for name in files:
                    full = os.path.join(root, name)
                    arc = os.path.join(base, os.path.relpath(full, d))
                    zf.write(full, arc)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[history] zip 打包失败: {e}")
        raise HTTPException(status_code=500, detail=f"打包失败: {e}")
    finally:
        # 无论打包成功与否，清理残留（发送后由 background 再删一次）
        if not os.path.exists(zip_path):
            pass

    async def _del():
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except OSError:
            pass

    # 审计（T8）：download_zip
    try:
        await audit(action="download_zip", kind=kind, task_uuid=task_uuid)
    except Exception:  # noqa: BLE001
        pass

    return FileResponse(
        path=zip_path,
        filename=f"{kind}_{task_uuid[:8]}.zip",
        media_type="application/zip",
        background=BackgroundTask(_del),
    )


@router.get("/{kind}/{task_uuid}/files/{name}")
async def history_file(kind: str, task_uuid: str, name: str):
    """白名单单文件下载：name 必须在 artifacts_json 白名单内；realpath 校验仍在任务目录内"""
    if kind not in ("detection", "slam", "imu"):
        raise HTTPException(status_code=400, detail="kind 非法")
    t = await _get_task(kind, task_uuid)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = _task_dir_under(t)
    if not d:
        raise HTTPException(status_code=404, detail="任务目录不存在")
    # 白名单：顶层文件名必须在 artifacts_json 白名单内；若未命中则递归查找同名文件
    # （兼容产物落在子目录，如 slam_plotter 输出的 png），随后仍有 realpath 越权校验兜底。
    whitelist = await _artifacts_list(t)
    target = os.path.join(d, name)
    if name not in whitelist:
        if os.sep in name:
            raise HTTPException(status_code=403, detail="文件名不在白名单内")
        found = None
        for root, _, files in os.walk(d):
            if name in files:
                found = os.path.join(root, name)
                break
        if found is None:
            raise HTTPException(status_code=403, detail="文件名不在白名单内")
        target = found
    real = os.path.realpath(target)
    # realpath 后必须恰好位于任务目录内（含子目录，防穿越）
    real_d = os.path.realpath(d)
    if not is_under_data_dir(real) or not (
        os.path.dirname(real) == real_d or os.path.dirname(real).startswith(real_d + os.sep)
    ):
        raise HTTPException(status_code=403, detail="路径越权")
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="文件不存在")
    # A5：单文件接口拒绝目录（如 fps/），整目录下载请用 zip 接口
    if os.path.isdir(real):
        raise HTTPException(status_code=400, detail="目标为目录，不允许直接下载目录，请使用 zip 打包下载")
    if not os.path.isfile(real):
        raise HTTPException(status_code=400, detail="目标不是普通文件")

    try:
        await audit(action="download_file", kind=kind, task_uuid=task_uuid,
                    params={"name": name})
    except Exception:  # noqa: BLE001
        pass

    return FileResponse(
        path=real, filename=name,
        media_type=_media_type_for(name),
        content_disposition_type="inline",  # 报告图片/文本内嵌预览；显式下载走前端 downloadBlob，不受此影响
    )


@router.get("/{kind}/{task_uuid}/report")
async def history_report(kind: str, task_uuid: str):
    """打印聚合 JSON：任务全字段 + 报告文本（截断 512KB 标 truncated）+ 图片文件名"""
    if kind not in ("detection", "slam", "imu"):
        raise HTTPException(status_code=400, detail="kind 非法")
    t = await _get_task(kind, task_uuid)
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = _task_dir_under(t)
    if not d:
        raise HTTPException(status_code=404, detail="任务目录不存在")

    report_text = ""
    truncated = False
    image_names = []

    if kind == "detection":
        # 00_summary_report.txt（在 fps 子目录或任务根）
        candidates = [
            os.path.join(d, "fps", "00_summary_report.txt"),
            os.path.join(d, "00_summary_report.txt"),
        ]
        target = next((c for c in candidates if os.path.isfile(c)), None)
        if target:
            report_text = _read_truncated(target)
            truncated = len(report_text) >= 512 * 1024
    elif kind == "slam":
        # stats 文本 + png 文件名
        stats_file = getattr(t, "stats_text", None)
        if stats_file:
            report_text = stats_file
        png = getattr(t, "png_file_path", None)
        if png and os.path.isfile(png):
            image_names = [os.path.basename(png)]
    else:  # imu
        txt = getattr(t, "txt_file_path", None)
        if txt and os.path.isfile(txt):
            report_text = _read_truncated(txt)
            truncated = len(report_text) >= 512 * 1024

    base = (_detection_to_dict if kind == "detection"
            else _slam_to_dict if kind == "slam" else _imu_to_dict)(t)

    try:
        await audit(action="report", kind=kind, task_uuid=task_uuid)
    except Exception:  # noqa: BLE001
        pass

    return {
        "kind": kind,
        "task": base,
        "report_text": report_text,
        "truncated": truncated,
        "image_names": image_names,
        "generated_at": datetime.now().isoformat(),
    }


def _read_truncated(path: str, limit: int = 512 * 1024) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""

