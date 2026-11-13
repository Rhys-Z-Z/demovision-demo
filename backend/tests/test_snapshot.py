# -*- coding: utf-8 -*-
"""截图接口测试（S3，无需硬件/web_video_server）：SSRF 防护 + 抓帧失败 502。

SSRF 校验与抓帧失败路径均在触碰数据库前短路返回，无需建表数据。

pytest 迁移要点（对照旧 unittest 版）：
  - 旧版需要 DEMOVISION_DEMO_MODE=0 + snapshot.DEMO_MODE = False 双重 hack，
    因为 import 顺序不受控；conftest.py 统一裁决后，import 时 DEMO_MODE
    天然就是 False，模块级覆写 hack 整段删除。
  - 4 个非法 topic 用例合并为 @pytest.mark.parametrize：一组测试代码跑四组
    数据；失败时 pytest 精确报告是哪一组（ids 让报告显示可读名称）。
  - mock.patch.object → monkeypatch.setattr（自动还原，不用 with 块）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import snapshot
from app.main import app

client = TestClient(app)


class _FailingClient:
    """AsyncClient 伪造：get 抛异常，模拟 web_video_server 未运行/抓帧失败"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):  # noqa: A003
        raise Exception("web_video_server not running")


class TestSnapshotSSRF:
    """topic 校验：仅允许 ROS 话题名，拒绝 URL scheme / 穿越（S4）"""

    @pytest.mark.parametrize("bad_topic", [
        "http://evil",    # URL scheme
        "//evil/x",       # 协议相对网络路径
        "/a/../../etc",   # 目录穿越
        "",               # 空串
    ], ids=["http-scheme", "double-slash", "traversal", "empty"])
    def test_reject_bad_topic(self, bad_topic):
        resp = client.post("/api/snapshot", json={"sn": "VS1", "topic": bad_topic})
        assert resp.status_code == 400

    def test_accept_ros_topic(self, monkeypatch):
        # 合法 ROS 话题名通过校验（此处仍会去抓帧失败 502，证明未被 400 拦截）
        monkeypatch.setattr(snapshot.httpx, "AsyncClient",
                            lambda *a, **kw: _FailingClient())
        resp = client.post("/api/snapshot",
                           json={"sn": "VS1",
                                 "topic": "/dv_sdk/VS123/camera/image"})
        assert resp.status_code == 502


class TestSnapshotCaptureFailure:
    """web_video_server 未运行 → 502 + 友好提示，不崩溃"""

    def test_server_down_returns_502(self, monkeypatch):
        monkeypatch.setattr(snapshot.httpx, "AsyncClient",
                            lambda *a, **kw: _FailingClient())
        resp = client.post("/api/snapshot",
                           json={"sn": "VS1",
                                 "topic": "/dv_sdk/VS123/camera/image"})
        assert resp.status_code == 502
        assert "实时图像服务" in resp.json()["detail"]

    def test_server_non_200_returns_502(self, monkeypatch):
        class _Resp:
            status_code = 503
            content = b""

        class _CM(_FailingClient):
            async def get(self, url):  # noqa: A003
                return _Resp()

        monkeypatch.setattr(snapshot.httpx, "AsyncClient",
                            lambda *a, **kw: _CM())
        resp = client.post("/api/snapshot",
                           json={"sn": "VS1",
                                 "topic": "/dv_sdk/VS123/camera/image"})
        assert resp.status_code == 502
