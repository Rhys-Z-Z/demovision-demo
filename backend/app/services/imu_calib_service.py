# -*- coding: utf-8 -*-
"""IMU 陀螺仪校准执行器：子进程运行 run_update_gyro_bias.sh，日志实时广播、产物解析与入库"""
from __future__ import annotations

import asyncio
import os
from typing import Callable, List, Optional

from app.config import DATA_DIR, DEMO_MODE, IMU_RUN_SCRIPT, IMU_TOOL_DIR
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.parser_service import find_latest_file, parse_imu_calibration_result
from app.utils.logger import logger
from app.utils.paths import date_key_of, imu_rel


class IMUCalibRunner:
    def __init__(self, task_uuid: str, result_dir: str,
                 broadcast: Callable[[dict], None]) -> None:
        self.task_uuid = task_uuid
        self.result_dir = result_dir
        self.broadcast = broadcast
        self.proc: Optional[asyncio.subprocess.Process] = None

    # ---------- 执行 ----------
    async def run(self, duration: float = 5.0) -> None:
        script_path = os.path.join(IMU_TOOL_DIR, IMU_RUN_SCRIPT)
        env = os.environ.copy()
        if not DEMO_MODE:
            # 真实模式注入动态库路径（demo 模拟脚本不依赖 libs/）
            env["LD_LIBRARY_PATH"] = f"{IMU_TOOL_DIR}/libs:{env.get('LD_LIBRARY_PATH', '')}"
        env["DEMOVISION_DATA_DIR"] = DATA_DIR

        try:
            self.proc = await asyncio.create_subprocess_exec(
                "bash", script_path, str(int(duration)),
                cwd=self.result_dir, env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[imu] 启动校准脚本失败: {e}")
            await self._finish(failed=True)
            return

        await self._drain_output()
        await self.proc.wait()

        # 子进程正常退出且有产物 => finished，否则 failed
        txt_path = find_latest_file(self.result_dir, ".txt")
        if self.proc.returncode == 0 and txt_path:
            await self._finish(failed=False)
        else:
            logger.warning(f"[imu] 校准结束 returncode={self.proc.returncode} txt={'有' if txt_path else '无'}")
            await self._finish(failed=True)

    async def _drain_output(self) -> None:
        """逐行读取 stdout（stderr 已合并）并实时广播，同时落盘日志供收尾解析判定"""
        log_path = os.path.join(self.result_dir, "imu_calib_run.log")
        log_fh = open(log_path, "a", encoding="utf-8", errors="replace")
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text.strip():
                    log_fh.write(text + "\n")
                    log_fh.flush()
                    await self.broadcast({
                        "type": "log_message",
                        "task_uuid": self.task_uuid,
                        "line": text,
                    })
        finally:
            log_fh.close()

    # ---------- 收尾 ----------
    async def _finish(self, failed: bool) -> None:
        txt_path = bin_path = ""
        summary: dict = {}
        qualified = None
        if not failed:
            txt_path = find_latest_file(self.result_dir, ".txt") or ""
            bin_path = find_latest_file(self.result_dir, ".bin") or ""
            parsed = parse_imu_calibration_result(self.result_dir)
            if parsed:
                summary = parsed
                qualified = parsed.get("qualified")

        # 扫描产物（相对任务目录的文件名列表，T4）
        artifacts = sorted(
            n for n in os.listdir(self.result_dir) if not n.startswith(".")
        ) if os.path.isdir(self.result_dir) else []
        # rel_path / date_key / log_rel_path
        rel_path = os.path.relpath(self.result_dir, DATA_DIR)
        log_rel = os.path.join(rel_path, "imu_calib_run.log") \
            if os.path.isfile(os.path.join(self.result_dir, "imu_calib_run.log")) else None

        try:
            async with AsyncSessionLocal() as session:
                await crud.finish_imu_calib_task(
                    session, self.task_uuid, self.result_dir,
                    txt_path=txt_path, bin_path=bin_path,
                    summary=summary, qualified=qualified, failed=failed,
                    rel_path=rel_path,
                    date_key=date_key_of(),
                    log_rel_path=log_rel,
                    artifacts=artifacts,
                )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[imu] 入库失败: {e}")

        await self.broadcast({
            "type": "task_finished", "task_uuid": self.task_uuid,
            "kind": "imu_calib",
            "status": "failed" if failed else "finished",
            "qualified": qualified,
            "error": None if not failed else "校准失败或未生成产物",
        })
