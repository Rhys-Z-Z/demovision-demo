# -*- coding: utf-8 -*-
"""遗留下载代理的安全测试（api/files.py）。

为什么值得测：
    这是唯一一个"用户输入直接拼成文件系统路径"的接口（base64 解码后的
    绝对路径）。它一旦退化，整个 DATA_DIR 之外的文件都可被读取（任意文件
    读取漏洞）。安全测试的价值不在覆盖率，而在于把攻击面钉死。

覆盖：
    合法文件 → 200 + 内容
    数据根之外 → 403
    ../ 穿越 → 403
    非法 base64 → 400
    文件不存在 → 404
"""
from __future__ import annotations

import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.main import app

client = TestClient(app)


def _b64(path: str) -> str:
    return base64.b64encode(path.encode("utf-8")).decode("ascii")


def _write_under_data(rel: str, content: bytes = b"payload") -> str:
    p = os.path.join(DATA_DIR, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(content)
    return p


class TestFilesDownload:
    def test_download_valid_file(self):
        """数据根下的普通文件 → 200，内容与文件名正确"""
        path = _write_under_data("2026_Sep/Sep_10/dl/hello.txt", b"hello")
        resp = client.get("/api/files/download", params={"path": _b64(path)})

        assert resp.status_code == 200
        assert resp.content == b"hello"
        assert "hello.txt" in resp.headers.get("content-disposition", "")

    def test_reject_outside_data_dir(self, tmp_path):
        """数据根之外的文件 → 403（防任意文件读取）"""
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        resp = client.get("/api/files/download", params={"path": _b64(str(outside))})

        assert resp.status_code == 403

    def test_reject_parent_traversal(self):
        """../ 穿越到数据根外 → 403（realpath 归一化后逃逸）"""
        evil = os.path.join(DATA_DIR, "2026_Sep", "..", "..", "..", "etc", "passwd")
        resp = client.get("/api/files/download", params={"path": _b64(evil)})

        assert resp.status_code == 403

    def test_reject_invalid_base64(self):
        """非法 base64 → 400"""
        resp = client.get("/api/files/download", params={"path": "not-base64!!!"})

        assert resp.status_code == 400

    def test_missing_file_returns_404(self):
        """合法路径但文件不存在 → 404"""
        path = os.path.join(DATA_DIR, "2026_Sep/Sep_10/no_such_file.bin")
        resp = client.get("/api/files/download", params={"path": _b64(path)})

        assert resp.status_code == 404

    def test_missing_query_param_returns_422(self):
        """缺少必填 query → FastAPI 校验 422（接口契约）"""
        assert client.get("/api/files/download").status_code == 422
