# -*- coding: utf-8 -*-
"""SLAM 任务接口：轨道A 子进程落盘 + 轨道C 停止解析 + 归档搬运（T5）"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import DATA_DIR, SCRIPT_DIR, SLAM_LAUNCHER, DEMO_MODE
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.services.parser_service import (find_latest_file,
                                         find_latest_stats_file,
                                         parse_slam_stats)
from app.utils.logger import logger
from app.utils.paths import (abs_of, archive_slam_name, date_key_of,
                             is_under_data_dir)
from app.websocket.manager import manager

router = APIRouter(prefix="/api/slam", tags=["slam"])

# 运行中的 SLAM 子进程与任务信息（进程外模块持有）
_processes: Dict[str, asyncio.subprocess.Process] = {}
_tasks: Dict[str, dict] = {}
_finalized: set = set()


class SlamStartRequest(BaseModel):
    devices: List[str] = Field(default_factory=list)
    duration: float = Field(default=120.0, ge=1.0)


def set_slam_monitor(monitor) -> None:
    """由 main.py 注入轨道 B 的 rospy 监控器"""
    global _monitor
    _monitor = monitor


_monitor = None


def _discover_devices() -> list:
    sys.path.insert(0, str(SCRIPT_DIR))
    from ship_out import ROSInterface
    return ROSInterface.get_devices()


def _sn8(sn: str) -> str:
    return sn[-8:] if len(sn) >= 8 else sn


# 用户从大屏保存的曲线截图统一用此前缀（见 POST /{task_uuid}/chart）
CHART_PREFIX = "slam_curve_"


def _find_trajectory_png(output_dir: str) -> Optional[str]:
    """轨迹图 PNG：递归取最新，但**排除用户保存的曲线截图**（CHART_PREFIX）。

    必要性：parser_service.find_latest_file 是递归取最新 .png，而大屏保存的曲线图
    比脚本产出的轨迹图更新，若不排除会把它误当成轨迹图写进 png_file_path
    （打印报告会贴错图）。
    """
    if not output_dir or not os.path.isdir(output_dir):
        return None
    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith(".png") and not name.startswith(CHART_PREFIX):
                candidates.append(os.path.join(root, name))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


async def _audit(action: str, task_uuid: str = None, sn: str = None,
                 params: dict = None, result: str = "ok",
                 detail: str = None) -> None:
    """SLAM 审计辅助（失败不阻断）"""
    try:
        await audit(action=action, kind="slam", task_uuid=task_uuid,
                    sn=sn, params=params, result=result, detail=detail)
    except Exception:  # noqa: BLE001
        pass


async def _pre_archive_stale(dir_date: str, sn8: str) -> None:
    """启动前预检查（T5）：若 {sn8}_output_slam 已存在且无运行中任务占用，按同规则归档旧目录。

    运行中任务的占用通过 _tasks 中同名 output_dir 判断（不会搬正在写入的目录）。
    """
    run_dir = os.path.join(dir_date, f"{sn8}_output_slam")
    if not os.path.isdir(run_dir):
        return
    # 是否被运行中任务占用
    in_use = any(
        info.get("output_dir") == run_dir for info in _tasks.values()
    )
    if in_use:
        return
    # 归档：{日期}/{SN}/{archive_slam_name(sn8, now)}
    date_key = date_key_of()
    # SN 层使用完整 sn（task 信息里有），预检查时用运行时目录里已存的命名取不到 SN，
    # 这里以 sn8 作为 SN 层（可接受：无更精确信息）
    arch_dir = os.path.join(DATA_DIR, date_key, sn8, archive_slam_name(sn8))
    # 只建父目录（勿建 arch_dir 本身）：shutil.move 在目标不存在时是 rename，
    # 若先 makedirs(arch_dir) 会把运行目录整体嵌套进归档目录一层（{name}/{name}/…）
    os.makedirs(os.path.dirname(arch_dir), exist_ok=True)
    try:
        shutil.move(run_dir, arch_dir)
        logger.info(f"[slam] 预检查归档旧目录: {run_dir} -> {arch_dir}")
    except OSError as e:
        logger.warning(f"[slam] 预检查归档失败（继续启动）: {e}")


async def _pre_archive_all(date_dir: str, sn_list: List[str]) -> None:
    """对本次参与设备的 sn8 逐个预检查归档"""
    for sn in sn_list:
        await _pre_archive_stale(date_dir, _sn8(sn))


@router.post("/start")
async def start_slam(req: SlamStartRequest):
    loop = asyncio.get_running_loop()

    # 设备发现
    if req.devices:
        sn_list = list(req.devices)
    else:
        try:
            sn_list = await loop.run_in_executor(None, _discover_devices)
        except Exception:  # noqa: BLE001
            sn_list = []
        if not sn_list:
            raise HTTPException(status_code=400, detail="未发现任何在线 SLAM 设备")

    task_uuid = str(uuid.uuid4())
    last8_list = [_sn8(sn) for sn in sn_list]
    suffix = "_".join(last8_list)
    date_key = date_key_of()
    date_dir = os.path.join(DATA_DIR, date_key)

    # 预检查：归档遗留的规范名目录（避免与本次运行冲突）
    await _pre_archive_all(date_dir, sn_list)

    # 运行时目录：{日期根}/{suffix}_output_slam
    run_dir = os.path.join(date_dir, f"{suffix}_output_slam")
    os.makedirs(run_dir, exist_ok=True)

    # 轨道 A：无头落盘脚本（注入 MPLBACKEND=Agg 与 DEMOVISION_DATA_DIR=日期目录）
    # 关键修复：slam_plotter_final.py 用 DEMOVISION_DATA_DIR 作输出根（否则 os.getcwd()），
    # 故必须注入 date_dir，使脚本产物直接落在 {日期根}/{suffix}_output_slam，
    # 与后端 run_dir 完全一致（避免产物落在 DATA_DIR 根导致解析失败）。
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUNBUFFERED"] = "1"
    env["DEMOVISION_DATA_DIR"] = date_dir
    if DEMO_MODE:
        # demo 模式：把请求设备集注入脚本，保证 mock 输出目录与 run_dir 命名一致
        env["DEMOVISION_SLAM_DEVICES"] = ",".join(sn_list)

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, SLAM_LAUNCHER, "--duration", str(req.duration),
            cwd=date_dir, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"启动 SLAM 脚本失败: {e}")

    _processes[task_uuid] = proc
    _tasks[task_uuid] = {
        "uuid": task_uuid, "sns": sn_list, "output_dir": run_dir,
        "date_key": date_key, "duration": req.duration,
    }
    _finalized.discard(task_uuid)

    # 轨道 B：注册实时订阅
    if _monitor is not None:
        for sn in sn_list:
            _monitor.subscribe(sn)

    # 入库
    async with AsyncSessionLocal() as session:
        await crud.create_slam_session(
            session, task_uuid, ",".join(sn_list), req.duration, run_dir
        )

    # 审计（T8）：start_slam
    await _audit("start_slam", task_uuid=task_uuid, sn=",".join(sn_list),
                 params={"devices": sn_list, "duration": req.duration})

    # 日志转发 + 自动完成监听
    asyncio.create_task(_drain_output(proc, task_uuid))
    asyncio.create_task(_wait_exit(proc, task_uuid))

    return {
        "task_uuid": task_uuid, "devices": sn_list,
        "output_dir": run_dir, "rel_path": os.path.relpath(run_dir, DATA_DIR),
        "duration": req.duration, "status": "running",
    }


@router.post("/stop/{task_uuid}")
async def stop_slam(task_uuid: str):
    if task_uuid not in _processes and task_uuid in _finalized:
        return {"task_uuid": task_uuid, "status": "finished"}
    if task_uuid not in _processes:
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    await _finalize(task_uuid, source="manual")
    await _audit("stop_slam", task_uuid=task_uuid)
    return {"task_uuid": task_uuid, "status": "finished"}


class SlamChartRequest(BaseModel):
    sn: str = ""
    image_base64: str = Field(..., description="data:image/png;base64,... 或裸 base64")
    caption: str = ""


@router.post("/{task_uuid}/chart")
async def save_slam_chart(task_uuid: str, req: SlamChartRequest):
    """把大屏画出的实时曲线存成 PNG，落进该任务的产物目录（随任务归档 + 历史页可下载）。

    设计约束（勿随手改）：
    - 文件**平铺在任务目录根**：单文件下载端点是 `/{kind}/{uuid}/files/{name}`，
      路径参数不匹配斜杠，放子目录会导致下载 404；
    - 命名前缀 `slam_curve_` 会被 `_find_trajectory_png` 排除，避免污染 png_file_path；
    - 写入后同步刷新 artifacts_json，使详情/下载白名单立即生效；
    - 允许对已结束（已归档）任务补存，此时目录已是归档目录（走 rel_path 解析）。
    """
    async with AsyncSessionLocal() as session:
        t = await crud.get_slam_session(session, task_uuid)
        if t is None:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 任务目录：优先 rel_path（新代码唯一路径来源），旧数据回退绝对列
        if getattr(t, "rel_path", None):
            task_dir = str(abs_of(t.rel_path))
        else:
            task_dir = t.output_dir_path or ""
        if not task_dir or not os.path.isdir(task_dir) or not is_under_data_dir(task_dir):
            raise HTTPException(status_code=400, detail="任务目录不存在或不在数据根目录下")

        # 解码 + 基本校验
        raw_b64 = (req.image_base64 or "").split(",", 1)[-1].strip()
        try:
            raw = base64.b64decode(raw_b64, validate=True)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="图片数据不是合法 base64")
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="仅接受 PNG 图片")
        if len(raw) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片过大（上限 8MB）")

        sn8 = req.sn.strip()[-8:] if len(req.sn.strip()) >= 8 else req.sn.strip()
        stem = f"{CHART_PREFIX}{sn8 + '_' if sn8 else ''}{datetime.now():%H%M%S}"
        path = os.path.join(task_dir, f"{stem}.png")
        n = 1
        while os.path.exists(path):  # 同秒连续保存防覆盖
            path = os.path.join(task_dir, f"{stem}_{n}.png")
            n += 1
        try:
            with open(path, "wb") as f:
                f.write(raw)
        except OSError as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"写入失败: {e}")

        name = os.path.basename(path)
        # 同步 artifacts_json（顶层文件名列表），下载白名单立即生效
        try:
            arts = json.loads(t.artifacts_json) if t.artifacts_json else []
            if not isinstance(arts, list):
                arts = []
        except Exception:  # noqa: BLE001
            arts = []
        if name not in arts:
            arts = sorted(arts + [name])
        t.artifacts_json = json.dumps(arts, ensure_ascii=False)
        await session.commit()

    rel = os.path.relpath(path, DATA_DIR)
    await _audit("save_slam_chart", task_uuid=task_uuid, sn=req.sn or None,
                 params={"name": name, "bytes": len(raw)}, detail=rel)
    await manager.broadcast({
        "type": "chart_saved", "task_uuid": task_uuid,
        "sn": req.sn or "", "name": name, "rel_path": rel,
    })
    return {"saved": True, "name": name, "rel_path": rel,
            "size": len(raw), "artifacts": arts}


async def _drain_output(proc: asyncio.subprocess.Process, task_uuid: str) -> None:
    """读取子进程 stdout 并实时广播，同时 tee 落盘 run.log（T5，写进运行时目录随目录搬走）"""
    info = _tasks.get(task_uuid, {})
    run_dir = info.get("output_dir", "")
    log_path = os.path.join(run_dir, "run.log") if run_dir else None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip("\n")
        if text.strip():
            if log_path:
                try:
                    with open(log_path, "a", encoding="utf-8", errors="replace") as f:
                        f.write(text + "\n")
                except OSError:
                    pass
            await manager.broadcast({
                "type": "log_message", "task_uuid": task_uuid, "line": text,
            })


async def _wait_exit(proc: asyncio.subprocess.Process, task_uuid: str) -> None:
    """子进程自然退出（录制完成）时自动收尾"""
    await proc.wait()
    if task_uuid in _finalized:
        return
    await _finalize(task_uuid, source="auto")


async def _finalize(task_uuid: str, source: str = "manual") -> None:
    """轨道 C：终止子进程、注销订阅、解析统计并入库、归档搬运（T5）"""
    if task_uuid in _finalized:
        return
    _finalized.add(task_uuid)

    proc = _processes.pop(task_uuid, None)
    if proc is not None and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

    info = _tasks.pop(task_uuid, {})
    run_dir = info.get("output_dir", "")
    sn_list = info.get("sns", [])
    date_key = info.get("date_key", date_key_of())

    if _monitor is not None:
        for sn in sn_list:
            _monitor.unsubscribe(sn)

    # 1) 用运行时路径解析（先解析后搬运，无反向依赖）
    stats_file = find_latest_stats_file(run_dir) if run_dir else None
    stats = parse_slam_stats(stats_file) if stats_file else None
    csv_path = find_latest_file(run_dir, ".csv") if run_dir else None
    png_path = _find_trajectory_png(run_dir)

    # 2) 尝试归档：{日期根}/{sn8}_output_slam -> {日期}/{SN}/{archive_slam_name}
    archived = False
    new_run_dir = run_dir
    if run_dir and os.path.isdir(run_dir) and sn_list:
        sn8 = _sn8(sn_list[0])  # 以首设备 SN 归档（SLAM 产线目录名以全部 sn8 拼接）
        sn_seg = sn_list[0]
        arch_rel = f"{date_key}/{sn_seg}/{archive_slam_name(sn8)}"
        arch_dir = os.path.join(DATA_DIR, arch_rel)
        try:
            os.makedirs(os.path.dirname(arch_dir), exist_ok=True)
            shutil.move(run_dir, arch_dir)
            new_run_dir = arch_dir
            archived = True
        except OSError as e:
            logger.warning(f"[slam] 归档失败，保留运行时位置（入库正确性不受影响）: {e}")
            await _audit("finish_slam", task_uuid=task_uuid,
                         sn=",".join(sn_list), result="failed",
                         detail=f"归档失败: {e}")

    # 重新定位产物路径（若已归档，路径更新为归档后新路径）
    if archived:
        stats_file = find_latest_stats_file(new_run_dir) or stats_file
        stats = parse_slam_stats(stats_file) if stats_file else None
        csv_path = find_latest_file(new_run_dir, ".csv") if new_run_dir else None
        png_path = _find_trajectory_png(new_run_dir) or png_path

    # artifacts_json（相对任务目录的文件名列表，含 run.log）
    artifacts = sorted(
        n for n in os.listdir(new_run_dir) if not n.startswith(".")
    ) if os.path.isdir(new_run_dir) else []
    rel_path = os.path.relpath(new_run_dir, DATA_DIR)
    log_rel = os.path.join(rel_path, "run.log") \
        if os.path.isfile(os.path.join(new_run_dir, "run.log")) else None

    async with AsyncSessionLocal() as session:
        await crud.finish_slam_session(
            session, task_uuid,
            csv_path=csv_path or "",
            png_path=png_path or "",
            stats_text=stats["raw_text"] if stats else "",
            is_qualified=stats.get("is_qualified") if stats else None,
            mean_mm=stats.get("mean_mm") if stats else None,
            std_mm=stats.get("std_mm") if stats else None,
            failed=(stats is None),
            rel_path=rel_path,
            date_key=date_key,
            log_rel_path=log_rel,
            artifacts=artifacts,
            output_dir_path=new_run_dir,
        )

    await manager.broadcast({
        "type": "task_finished", "task_uuid": task_uuid,
        "kind": "slam", "status": "finished", "source": source,
        "rel_path": rel_path,
    })
