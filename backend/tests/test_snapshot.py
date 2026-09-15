# -*- coding: utf-8 -*-
"""截图接口测试（S3，无需硬件/web_video_server 即可跑）：SSRF 防护 + 抓帧失败 502。

注：与 test_paths 等共享 app.config 进程缓存，需**单独**运行（python -m unittest tests.test_snapshot）。
SSRF 校验与抓帧失败路径均在触碰数据库前短路返回，无需 init_db。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_ROOT = tempfile.mkdtemp(prefix="demovision_test_snapshot_")
os.environ.setdefault("DEMOVISION_DATA_DIR", os.path.join(_TMP_ROOT, "data"))
os.environ.setdefault("DEMOVISION_DB_DIR", os.path.join(_TMP_ROOT, "db"))
# 本测试覆盖真实模式的抓帧失败/SSRF 路径（demo 模式走本地渲染，不触达 httpx）。
# 注意：app.config 为进程级缓存，先被其他测试模块导入时 DEMO_MODE 默认即开启，
# 因此除设环境变量外，还需直接覆写 snapshot 模块级开关，保证任意导入顺序下都走真实模式。
os.environ["DEMOVISION_DEMO_MODE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.api import snapshot  # noqa: E402

snapshot.DEMO_MODE = False  # 强制真实模式：抓帧段走 httpx 而非本地渲染

client = TestClient(app)


class _FailingClient:
    """AsyncClient 伪造：get 抛异常，模拟 web_video_server 未运行/抓帧失败"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):  # noqa: A003
        raise Exception("web_video_server not running")


class TestSnapshotSSRF(unittest.TestCase):
    """topic 校验：仅允许 ROS 话题名，拒绝 URL scheme / 穿越（S4）"""

    def test_reject_http_scheme(self):
        resp = client.post("/api/snapshot", json={"sn": "VS1", "topic": "http://evil"})
        self.assertEqual(resp.status_code, 400)

    def test_reject_double_slash(self):
        resp = client.post("/api/snapshot", json={"sn": "VS1", "topic": "//evil/x"})
        self.assertEqual(resp.status_code, 400)

    def test_reject_path_traversal(self):
        resp = client.post("/api/snapshot", json={"sn": "VS1", "topic": "/a/../../etc"})
        self.assertEqual(resp.status_code, 400)

    def test_reject_empty(self):
        resp = client.post("/api/snapshot", json={"sn": "VS1", "topic": ""})
        self.assertEqual(resp.status_code, 400)

    def test_accept_ros_topic(self):
        # 合法 ROS 话题名通过校验（此处仍会去抓帧失败 502，证明未被 400 拦截）
        with mock.patch.object(snapshot.httpx, "AsyncClient",
                               return_value=_FailingClient()):
            resp = client.post("/api/snapshot",
                               json={"sn": "VS1",
                                     "topic": "/dv_sdk/VS123/camera/image"})
        self.assertEqual(resp.status_code, 502)


class TestSnapshotCaptureFailure(unittest.TestCase):
    """web_video_server 未运行 → 502 + 友好提示，不崩溃"""

    def test_server_down_returns_502(self):
        with mock.patch.object(snapshot.httpx, "AsyncClient",
                               return_value=_FailingClient()):
            resp = client.post("/api/snapshot",
                               json={"sn": "VS1",
                                     "topic": "/dv_sdk/VS123/camera/image"})
        self.assertEqual(resp.status_code, 502)
        self.assertIn("实时图像服务", resp.json()["detail"])

    def test_server_non_200_returns_502(self):
        class _Resp:
            status_code = 503
            content = b""

        class _CM(_FailingClient):
            async def get(self, url):  # noqa: A003
                return _Resp()

        with mock.patch.object(snapshot.httpx, "AsyncClient",
                               return_value=_CM()):
            resp = client.post("/api/snapshot",
                               json={"sn": "VS1",
                                     "topic": "/dv_sdk/VS123/camera/image"})
        self.assertEqual(resp.status_code, 502)


if __name__ == "__main__":
    unittest.main(verbosity=2)