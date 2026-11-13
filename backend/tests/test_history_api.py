# -*- coding: utf-8 -*-
"""历史记录 API 测试：详情 / 白名单单文件 / zip / 打印报告 / 轨迹 / 审计导出 / 存储统计。

为什么直接 await 路由函数而不是 TestClient：
    history 全部接口都要读写异步 sqlite；TestClient 每次请求自建事件循环，
    与 aiosqlite 连接池的 loop 绑定容易跨循环冲突。直接 await 更稳定，
    且 4xx 语义（HTTPException.status_code）与返回结构完全一致。
    纯 HTTP 层（路由匹配、参数校验）已由 test_files_download / test_snapshot 覆盖。

覆盖的安全/业务契约：
    - kind 白名单（非法 kind → 400，防动态路由任意取值）
    - 单文件下载必须命中 artifacts 白名单；含路径分隔符一律 403；
      realpath 后必须仍在任务目录内；目录不允许当文件下载（400）
    - zip 打包内容与桌面目录结构一致
    - 打印报告按 kind 聚合不同来源（detection 读 txt / slam 读 stats / imu 读 txt）
    - 轨迹接口：DB csv 列优先、目录回退、解析失败 422、无 CSV 404
"""
from __future__ import annotations

import asyncio
import os
import zipfile
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.api import history, operations, system
from app.config import DATA_DIR
from app.db import crud
from app.db.database import AsyncSessionLocal
from app.services.audit_service import audit
from app.utils.paths import abs_of

_DATE_KEY = "2019_Feb/Feb_1"


def _mk_files(rel_dir: str, files: dict[str, str | bytes]) -> str:
    d = os.path.join(DATA_DIR, rel_dir)
    os.makedirs(d, exist_ok=True)
    for name, content in files.items():
        p = os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(content.encode("utf-8") if isinstance(content, str) else content)
    return d


async def _seed_detection(uuid: str, sn: str,
                          files: dict[str, str | bytes] | None = None,
                          artifacts: list[str] | None = None) -> str:
    rel = f"{_DATE_KEY}/{sn}/test_result_{sn[-8:]}_143500"
    d = _mk_files(rel, files or {})
    async with AsyncSessionLocal() as s:
        await crud.create_detection_task(s, uuid, "平动", "全功能", sn)
        await crud.finish_detection_task(
            s, uuid, result_dir_path=d, overall_status="PASS", summary={},
            rel_path=rel, date_key=_DATE_KEY, artifacts=artifacts,
        )
    return d


async def _seed_slam(uuid: str, sn: str, stats_text: str = "统计文本",
                     png: str | None = None, csv: str | None = None) -> str:
    rel = f"{_DATE_KEY}/{sn}/{sn[-8:]}_output_slam_143500"
    files: dict[str, str] = {}
    if png:
        files[png] = b"\x89PNG-fake"
    if csv:
        files["traj.csv"] = csv
    d = _mk_files(rel, files)
    async with AsyncSessionLocal() as s:
        await crud.create_slam_session(s, uuid, sn, 10.0, d)
        await crud.finish_slam_session(
            s, uuid,
            csv_path=os.path.join(d, "traj.csv") if csv else "",
            png_path=os.path.join(d, png) if png else "",
            stats_text=stats_text, is_qualified=True,
            mean_mm=2.5, std_mm=0.5,
            rel_path=rel, date_key=_DATE_KEY,
        )
    return d


async def _seed_imu(uuid: str, sn: str, txt_content: str) -> str:
    rel = f"{_DATE_KEY}/imu_calib_{uuid[:8]}"
    d = _mk_files(rel, {"imu_calib_after.txt": txt_content})
    async with AsyncSessionLocal() as s:
        await crud.create_imu_calib_task(s, uuid, sn)
        await crud.finish_imu_calib_task(
            s, uuid, result_dir_path=d,
            txt_path=os.path.join(d, "imu_calib_after.txt"),
            summary={}, qualified=True, rel_path=rel, date_key=_DATE_KEY,
        )
    return d


def _status(fn, *args, **kwargs) -> int:
    """执行路由函数并返回 HTTPException 状态码（断言 4xx 语义用）"""
    with pytest.raises(HTTPException) as ei:
        asyncio.run(fn(*args, **kwargs))
    return ei.value.status_code


class TestHistoryDetail:
    def test_unknown_kind_400(self):
        assert _status(history.history_detail, "bogus", "any") == 400

    def test_missing_task_404(self):
        assert _status(history.history_detail, "detection", "no-such-uuid") == 404

    def test_artifacts_meta(self):
        """artifacts 元信息：文件带 size/mtime，目录带递归 size（type=dir）"""
        asyncio.run(_seed_detection(
            "hist-d1", "VS9000000001",
            files={"00_summary_report.txt": "设备总数: 1",
                   "fps/00_summary_report.txt": "nested"},
            artifacts=["00_summary_report.txt", "fps"],
        ))

        data = asyncio.run(history.history_detail("detection", "hist-d1"))

        by_name = {a["name"]: a for a in data["artifacts"]}
        assert by_name["00_summary_report.txt"]["type"] == "file"
        assert by_name["00_summary_report.txt"]["size"] > 0
        assert "mtime" in by_name["00_summary_report.txt"]
        assert by_name["fps"]["type"] == "dir"
        assert by_name["fps"]["size"] > 0
        assert data["task"]["task_uuid"] == "hist-d1"

    def test_big_flag_threshold(self):
        """超过 50MB 标 big:true（用稀疏文件避免真写 50MB）"""
        d = asyncio.run(_seed_detection(
            "hist-d2", "VS9000000002",
            files={"huge.bin": b""}, artifacts=["huge.bin"]))
        os.truncate(os.path.join(d, "huge.bin"), 51 * 1024 * 1024)

        data = asyncio.run(history.history_detail("detection", "hist-d2"))

        assert data["artifacts"][0]["big"] is True


class TestHistoryFileWhitelist:
    def test_whitelist_hit_returns_file(self):
        d = asyncio.run(_seed_detection(
            "hist-f1", "VS9000000003",
            files={"00_summary_report.txt": "ok"},
            artifacts=["00_summary_report.txt"]))

        resp = asyncio.run(history.history_file(
            "detection", "hist-f1", "00_summary_report.txt"))

        assert isinstance(resp, FileResponse)
        assert os.path.realpath(resp.path) == os.path.realpath(
            os.path.join(d, "00_summary_report.txt"))

    def test_recursive_lookup_for_nested_file(self):
        """不在顶层白名单但在子目录中存在同名文件 → 递归命中（slam png 场景）"""
        asyncio.run(_seed_slam("hist-f2", "VS9000000004", png="plot.png"))

        resp = asyncio.run(history.history_file("slam", "hist-f2", "plot.png"))

        assert resp.path.endswith("plot.png")

    @pytest.mark.parametrize("name, idx", [
        ("fps/00_summary_report.txt", 1),   # 含路径分隔符
        ("..%2F..%2Fetc%2Fpasswd", 2),      # 编码穿越串（未解码时也只是个怪文件名）
        ("no_such_file.txt", 3),            # 不在白名单且不存在
    ], ids=["with-sep", "encoded-traversal", "unknown-name"])
    def test_reject_non_whitelist_names(self, name, idx):
        # 注意：parametrize 每组参数是独立用例、测试体整体重跑，
        # 造数据必须用随参数唯一的 task_uuid，否则第二组就撞 UNIQUE 约束。
        uuid = f"hist-f3-{idx}"
        asyncio.run(_seed_detection(
            uuid, "VS9000000005",
            files={"00_summary_report.txt": "ok"},
            artifacts=["00_summary_report.txt"]))

        assert _status(history.history_file, "detection", uuid, name) == 403

    def test_directory_rejected_400(self):
        """目录不能当文件下载（引导用户走 zip）"""
        asyncio.run(_seed_detection(
            "hist-f4", "VS9000000006",
            files={"fps/a.txt": "x"}, artifacts=["fps"]))

        assert _status(history.history_file, "detection", "hist-f4", "fps") == 400

    def test_symlink_traversal_rejected_403(self, tmp_path):
        """任务目录内放 symlink 指向外部 → realpath 校验拒绝（403）"""
        d = asyncio.run(_seed_detection(
            "hist-f5", "VS9000000007",
            files={"link.txt": "placeholder"}, artifacts=["link.txt"]))
        target = tmp_path / "outside.txt"
        target.write_text("outside")
        link = os.path.join(d, "link.txt")
        os.remove(link)
        os.symlink(str(target), link)

        assert _status(history.history_file, "detection", "hist-f5", "link.txt") == 403


class TestHistoryZip:
    def test_zip_contains_nested_structure(self):
        asyncio.run(_seed_detection(
            "hist-z1", "VS9000000008",
            files={"00_summary_report.txt": "ok", "fps/a.jpg": "img"},
            artifacts=["00_summary_report.txt", "fps"]))

        resp = asyncio.run(history.history_download("detection", "hist-z1"))
        try:
            assert isinstance(resp, FileResponse)
            assert resp.media_type == "application/zip"
            with zipfile.ZipFile(resp.path) as zf:
                names = zf.namelist()
        finally:
            if os.path.exists(resp.path):
                os.remove(resp.path)

        base = "test_result_00000008_143500"
        assert any(n.endswith("00_summary_report.txt") for n in names)
        assert any(n.endswith(os.path.join("fps", "a.jpg")) for n in names)
        assert all(n.startswith(base + os.sep) for n in names)

    def test_missing_dir_404(self):
        asyncio.run(_seed_detection("hist-z2", "VS9000000009", artifacts=[]))
        # 删掉刚建的目录，模拟"库里有记录、磁盘产物已被清理"
        d = abs_of(f"{_DATE_KEY}/VS9000000009/test_result_00000009_143500")
        os.rmdir(d)

        assert _status(history.history_download, "detection", "hist-z2") == 404


class TestHistoryReport:
    def test_detection_report_reads_summary_txt(self):
        asyncio.run(_seed_detection(
            "hist-r1", "VS9000000010",
            files={"fps/00_summary_report.txt": "设备总数: 3\n整体检测状态: PASS"},
            artifacts=["fps"]))

        data = asyncio.run(history.history_report("detection", "hist-r1"))

        assert data["kind"] == "detection"
        assert "设备总数: 3" in data["report_text"]
        assert data["truncated"] is False

    def test_slam_report_uses_stats_text_and_png(self):
        asyncio.run(_seed_slam("hist-r2", "VS9000000011",
                               stats_text="平均欧式距离 (Mean): 2.50 mm",
                               png="plot.png"))

        data = asyncio.run(history.history_report("slam", "hist-r2"))

        assert "Mean" in data["report_text"]
        assert data["image_names"] == ["plot.png"]

    def test_imu_report_reads_txt(self):
        asyncio.run(_seed_imu("hist-r3", "VS9000000012",
                              "GyroBias= 0.001 0.002 0.003\n"))

        data = asyncio.run(history.history_report("imu", "hist-r3"))

        assert "GyroBias" in data["report_text"]


class TestSlamTrajectory:
    _CSV = "\n".join([
        "time_since_start_s,absolute_time,x_m,y_m,z_m,distance_mm",
        "0.0,2026-09-10T14:35:00,0.5,0.2,0.1,1.5",
        "0.02,2026-09-10T14:35:00.02,0.6,0.3,0.2,2.5",
    ]) + "\n"

    def test_returns_series(self):
        asyncio.run(_seed_slam("hist-t1", "VS9000000013", csv=self._CSV))

        data = asyncio.run(history.slam_trajectory("hist-t1"))

        assert data["total"] == 2 and data["sampled"] == 2
        assert data["x"] == [500.0, 600.0]
        assert data["csv_name"] == "traj.csv"
        assert data["task_uuid"] == "hist-t1"

    def test_no_csv_404(self):
        asyncio.run(_seed_slam("hist-t2", "VS9000000014"))

        assert _status(history.slam_trajectory, "hist-t2") == 404

    def test_bad_csv_422(self):
        """列名不符 → 解析失败 422（前端提示而不是后端 500）"""
        bad = "foo,bar\r\n1,2\r\n"
        asyncio.run(_seed_slam("hist-t3", "VS9000000015", csv=bad))

        assert _status(history.slam_trajectory, "hist-t3") == 422


class TestOperationsExport:
    def test_export_csv_contains_filtered_rows(self):
        async def _write_audit():
            await audit(action="export_probe", kind="system", detail="导出探针")

        asyncio.run(_write_audit())

        resp = asyncio.run(operations.operations_export(action="export_probe"))
        try:
            assert isinstance(resp, FileResponse)
            with open(resp.path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        finally:
            if os.path.exists(resp.path):
                os.remove(resp.path)

        assert "时间,操作,类型,任务UUID,SN,结果,详情" in text
        assert "export_probe" in text
        assert "导出探针" in text


class TestSystemStorage:
    def test_month_breakdown(self):
        """按月统计：月份目录含 '_'；只统计日期目录，exports/.tmp 单独列"""
        d = _mk_files("2027_Feb/Feb_1", {"blob.bin": "x" * 2048})

        data = asyncio.run(system.storage(month="2027_Feb"))

        assert data["data_dir"] == DATA_DIR
        assert len(data["months"]) == 1
        feb = data["months"][0]
        assert feb["month"] == "2027_Feb"
        assert feb["bytes"] >= 2048
        assert any(day["day"] == "Feb_1" and day["bytes"] >= 2048
                   for day in feb["days"])
        assert data["total_bytes"] >= feb["bytes"]
        assert os.path.isdir(d)
