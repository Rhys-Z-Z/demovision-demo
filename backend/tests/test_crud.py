# -*- coding: utf-8 -*-
"""查询层测试：日期边界 / 筛选 / 分页 / 排序（db/crud.py）。

为什么值得测：
    历史页"按日期筛选"是最高频操作，日期边界又是经典 off-by-one 高发区：
    date_to 必须包含当日 23:59:59，但必须排除次日 00:00:00。这类 bug
    不抛异常、不报错，只让用户"少看到一条记录"。SQL 过滤逻辑只有真库能验，
    因此直接用临时 sqlite（conftest 已隔离 DATA_DIR/DB_DIR）。

独立性约定：每个用例自造自己的数据、使用唯一 SN 前缀，既避免共享临时库
互相干扰，也保证"单跑某个用例"同样通过（用例不依赖执行顺序）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.db import crud
from app.db.database import AsyncSessionLocal
from app.db.models import (DetectionTask, ImuCalibTask, Screenshot,
                           SlamSession)

_DATE_KEY = "2019_Jan/Jan_1"
_SN = "C0DEX"


async def _add_all(rows) -> None:
    async with AsyncSessionLocal() as session:
        session.add_all(rows)
        await session.commit()


def _det(uuid: str, start: datetime, sn: str, status: str = "finished") -> DetectionTask:
    return DetectionTask(
        task_uuid=uuid, start_time=start, status=status,
        device_type="平动", test_mode="全功能",
        devices_sn=sn, date_key=_DATE_KEY,
    )


def _query(coro_fn):
    """把 async 查询函数包装成同步调用（沿用项目现有 asyncio.run 风格）"""
    async def _inner():
        async with AsyncSessionLocal() as session:
            return await coro_fn(session)
    return asyncio.run(_inner())


class TestDetectionDateBoundary:
    def test_date_to_includes_whole_day(self):
        """date_to=当日 → 必须包含 00:00:00 与 23:59:59，排除次日 00:00:00"""
        sn = f"{_SN}DAY"
        asyncio.run(_add_all([
            _det("crud-d1", datetime(2019, 1, 1, 0, 0, 0), sn),
            _det("crud-d2", datetime(2019, 1, 1, 23, 59, 59), sn),
            _det("crud-d3", datetime(2019, 1, 2, 0, 0, 0), sn),
        ]))

        rows, total = _query(lambda s: crud.list_detection_tasks(
            s, date_from="2019-01-01", date_to="2019-01-01", sn=sn))

        assert total == 2
        assert {r.task_uuid for r in rows} == {"crud-d1", "crud-d2"}

    def test_date_from_is_inclusive(self):
        """date_from=当日 → 含 00:00:00（边界另一侧）"""
        sn = f"{_SN}FROM"
        asyncio.run(_add_all([
            _det("crud-d4", datetime(2019, 1, 1, 0, 0, 0), sn),
            _det("crud-d5", datetime(2019, 1, 1, 12, 0, 0), sn),
        ]))

        _, total = _query(lambda s: crud.list_detection_tasks(
            s, date_from="2019-01-01", sn=sn))

        assert total == 2

    def test_sn_partial_match(self):
        """SN 筛选是包含匹配（用户只记得后 8 位也能搜到）"""
        sn = f"{_SN}SNMATCH"
        asyncio.run(_add_all([
            _det("crud-d6", datetime(2019, 1, 3, 9), sn + "ZZ"),
            _det("crud-d7", datetime(2019, 1, 3, 10), f"{_SN}OTHER"),
        ]))

        rows, total = _query(lambda s: crud.list_detection_tasks(
            s, sn=f"{_SN}SNMATCH"))

        assert total == 1
        assert rows[0].task_uuid == "crud-d6"

    def test_status_filter(self):
        sn = f"{_SN}STATUS"
        asyncio.run(_add_all([
            _det("crud-d8", datetime(2019, 1, 4, 9), sn, status="failed"),
            _det("crud-d9", datetime(2019, 1, 4, 10), sn, status="finished"),
        ]))

        rows, total = _query(lambda s: crud.list_detection_tasks(
            s, sn=sn, status="failed"))

        assert total == 1
        assert rows[0].task_uuid == "crud-d8"

    def test_pagination_newest_first(self):
        """分页按 id 倒序（最新在前），第二页拿到最旧一条"""
        sn = f"{_SN}PAGE"
        asyncio.run(_add_all([
            _det("crud-p1", datetime(2019, 1, 8, 9), sn),
            _det("crud-p2", datetime(2019, 1, 8, 10), sn),
            _det("crud-p3", datetime(2019, 1, 8, 11), sn),
        ]))

        rows1, total = _query(lambda s: crud.list_detection_tasks(
            s, page=1, size=2, sn=sn))
        rows2, _ = _query(lambda s: crud.list_detection_tasks(
            s, page=2, size=2, sn=sn))

        assert total == 3
        assert [r.task_uuid for r in rows1] == ["crud-p3", "crud-p2"]
        assert [r.task_uuid for r in rows2] == ["crud-p1"]


class TestSlamFilter:
    def test_qualified_filter(self):
        sn = f"{_SN}SLAMQ"
        asyncio.run(_add_all([
            SlamSession(task_uuid="crud-s1", sn=sn, start_time=datetime(2019, 1, 4, 9),
                        status="finished", duration_sec=10.0, output_dir_path="/tmp/a",
                        date_key=_DATE_KEY, is_qualified=True),
            SlamSession(task_uuid="crud-s2", sn=sn, start_time=datetime(2019, 1, 4, 10),
                        status="finished", duration_sec=10.0, output_dir_path="/tmp/b",
                        date_key=_DATE_KEY, is_qualified=False),
            SlamSession(task_uuid="crud-s3", sn=sn, start_time=datetime(2019, 1, 4, 11),
                        status="finished", duration_sec=10.0, output_dir_path="/tmp/c",
                        date_key=_DATE_KEY, is_qualified=None),
        ]))

        rows_t, total_t = _query(lambda s: crud.list_slam_sessions(
            s, sn=sn, qualified="true"))
        rows_f, total_f = _query(lambda s: crud.list_slam_sessions(
            s, sn=sn, qualified="false"))

        assert total_t == 1 and rows_t[0].task_uuid == "crud-s1"
        # None（未判定）不得混入"不合格"结果
        assert total_f == 1 and rows_f[0].task_uuid == "crud-s2"


class TestImuFilter:
    def test_qualified_filter(self):
        sn = f"{_SN}IMUQ"
        asyncio.run(_add_all([
            ImuCalibTask(task_uuid="crud-i1", sn=sn, start_time=datetime(2019, 1, 5, 9),
                         status="finished", result_dir_path="/tmp/i1",
                         date_key=_DATE_KEY, qualified=True),
            ImuCalibTask(task_uuid="crud-i2", sn=sn, start_time=datetime(2019, 1, 5, 10),
                         status="finished", result_dir_path="/tmp/i2",
                         date_key=_DATE_KEY, qualified=False),
        ]))

        rows, total = _query(lambda s: crud.list_imu_calib_tasks(
            s, sn=sn, qualified="false"))

        assert total == 1
        assert rows[0].task_uuid == "crud-i2"


class TestScreenshotFilter:
    def test_ts_date_boundary(self):
        """截图按 ts 过滤（不是 date_key 字符串比较）—— 与检测任务同一边界语义"""
        sn = f"{_SN}SHOT"
        asyncio.run(_add_all([
            Screenshot(sn=sn, ts=datetime(2019, 1, 6, 23, 59, 59),
                       date_key="2019_Jan/Jan_6", rel_path="a.png", file_size=10),
            Screenshot(sn=sn, ts=datetime(2019, 1, 7, 0, 0, 0),
                       date_key="2019_Jan/Jan_7", rel_path="b.png", file_size=20),
        ]))

        rows, total = _query(lambda s: crud.list_screenshots(
            s, date_from="2019-01-06", date_to="2019-01-06", sn=sn))

        assert total == 1
        assert rows[0].rel_path == "a.png"
