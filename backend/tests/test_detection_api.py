# -*- coding: utf-8 -*-
"""检测任务接口测试：参数校验 / 单任务互斥 / 停止语义（api/detection.py）。

为什么值得测：
    "同一时间只允许一个检测任务"是产线硬规则：两个检测并发会争抢同一台
    设备与同一个数据目录。这类互斥逻辑没有数据库约束兜底，只存在于
    模块级 _running_task 里 —— 回归时最容易悄悄失守。

注意接口契约：参数非法 / 忙 都返回 200 + {"error": ...}（不是 4xx，
前端按 error 字段提示），唯一 raise HTTPException 的是 stop 未匹配。

做法：monkeypatch 掉真正跑子进程的 _run_detection_task 与走 WS 的 broadcast，
只验证状态机与落库结果。
"""
from __future__ import annotations

import asyncio

import pytest

from app.api import detection
from app.db import crud
from app.db.database import AsyncSessionLocal


def _req(**kwargs) -> detection.DetectionStartRequest:
    return detection.DetectionStartRequest(**kwargs)


async def _noop(*args, **kwargs):
    return None


@pytest.fixture
def stub_side_effects(monkeypatch):
    """隔离子进程与 WS：只测状态机"""
    monkeypatch.setattr(detection, "_run_detection_task", _noop)
    monkeypatch.setattr(detection, "audit", _noop)
    monkeypatch.setattr(detection.manager, "broadcast", _noop)


class TestStartValidation:
    def test_invalid_mode(self):
        out = asyncio.run(detection.start_detection(
            _req(mode="超高精度", devices=["VS1"])))

        assert "error" in out
        assert "非法检测模式" in out["error"]

    def test_invalid_device_type(self):
        out = asyncio.run(detection.start_detection(
            _req(device_type="外星设备", devices=["VS1"])))

        assert "error" in out
        assert "非法设备类型" in out["error"]

    def test_empty_devices(self):
        out = asyncio.run(detection.start_detection(_req(devices=[])))

        assert "error" in out
        assert "至少选择一个设备" in out["error"]

    def test_busy_when_task_running(self):
        """单任务互斥：已有任务在跑 → 拒绝启动第二个"""
        detection._running_task = "someone-else-running"

        out = asyncio.run(detection.start_detection(
            _req(devices=["VS1"])))

        assert "error" in out
        assert "已有检测任务" in out["error"]
        # 被拒绝时不得创建新任务
        async def _count():
            async with AsyncSessionLocal() as s:
                return await crud.get_detection_task(s, "someone-else-running")
        assert asyncio.run(_count()) is None


class TestStartSuccess:
    def test_creates_task_row_and_marks_running(self, stub_side_effects):
        """合法请求 → 落库(running) + 占用互斥位 + 返回 task_uuid"""

        async def _go():
            out = await detection.start_detection(
                _req(devices=["VS1000000001", "VS2000000002"], mode="仅相机"))
            async with AsyncSessionLocal() as s:
                row = await crud.get_detection_task(s, out["task_uuid"])
            return out, row

        out, row = asyncio.run(_go())

        assert out["status"] == "running"
        assert out["mode"] == "仅相机"
        assert detection._running_task == out["task_uuid"]
        assert row is not None
        assert row.status == "running"
        assert row.devices_sn == "VS1000000001,VS2000000002"
        assert row.test_mode == "仅相机"

    def test_times_passed_through(self, monkeypatch):
        """自定义时长原样进入任务（映射在 runner 内做，不在接口层）"""
        captured = {}

        async def _fake_run(task_uuid, devices, mode, device_type, times):
            captured["times"] = times

        monkeypatch.setattr(detection, "_run_detection_task", _fake_run)
        monkeypatch.setattr(detection, "audit", _noop)

        async def _go():
            await detection.start_detection(
                _req(devices=["VS1"], times={"color": 5, "slam": 12}))
            # create_task 调度后让出一轮，让 fake 协程跑完
            # （不能分两次 asyncio.run：run 结束会取消 pending task）
            await asyncio.sleep(0)

        asyncio.run(_go())

        assert captured.get("times") == {"color": 5, "slam": 12}


class TestStop:
    def test_stop_unknown_task_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as ei:
            asyncio.run(detection.stop_detection("not-running"))

        assert ei.value.status_code == 404

    def test_stop_matching_task(self, monkeypatch, stub_side_effects):
        """停止匹配任务 → 发取消信号（不立即清理 _running_task，等 runner 收尾）"""
        calls = []
        monkeypatch.setattr(detection.detection_runner,
                            "request_cancel_detection", lambda: calls.append(1))
        detection._running_task = "task-abc"

        out = asyncio.run(detection.stop_detection("task-abc"))

        assert out == {"task_uuid": "task-abc", "status": "stopping"}
        assert calls == [1]
