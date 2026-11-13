# -*- coding: utf-8 -*-
"""detection_runner.LogRedirect 测试 —— 手写的"行/进度条"解析器。

为什么值得测：
    产线脚本（ship_out）用 print + \\r 进度条 + ANSI 颜色输出，LogRedirect
    负责把这些流式文本切成 WebSocket 消息并 tee 到 run.log。它错了不会抛
    异常，只会让前端日志缺行/花屏——典型的"静默故障"。字符串解析逻辑是
    回归高发区，且完全是纯函数，测试成本极低。

覆盖：
    逐行切分、跨 write 边界拼接、\\r 进度条取最新段、ANSI 转义剥离、
    tee 落盘、空输入、flush 无副作用。
"""
from __future__ import annotations

import pytest

from app.services.detection_runner import LogRedirect


@pytest.fixture
def captured():
    """收集 LogRedirect 回调收到的每一行"""
    return []


@pytest.fixture
def redirect(captured):
    return LogRedirect(lambda line: captured.append(line))


class TestLogRedirect:
    def test_splits_multiple_lines(self, redirect, captured):
        redirect.write("line1\nline2\n")

        assert captured == ["line1", "line2"]

    def test_buffers_partial_line_across_writes(self, redirect, captured):
        """半行必须先缓冲，等换行才发出（跨 write 边界拼接）"""
        redirect.write("hel")
        assert captured == []
        redirect.write("lo\n")
        assert captured == ["hello"]

    def test_carriage_return_progress_keeps_latest(self, redirect, captured):
        """同一次 write 内多段 \\r：只取最新一段，不产生海量日志"""
        redirect.write("[Color] 采集中 10%\r[Color] 采集中 55%\r")

        assert captured == ["[Color] 采集中 55%"]

    def test_carriage_return_trailing_single_segment(self, redirect, captured):
        """回归：print(msg, end="\\r") 的形态（尾部带空段）不得整行丢弃"""
        redirect.write("[Color] 采集中 88%\r")

        assert captured == ["[Color] 采集中 88%"]

    def test_strips_ansi_color_codes(self, redirect, captured):
        redirect.write("\033[1;31mERROR\033[0m occurred\n")

        assert captured == ["ERROR occurred"]

    def test_strips_trailing_carriage_return_on_normal_lines(self, redirect, captured):
        redirect.write("done\r\n")

        assert captured == ["done"]

    def test_ignores_blank_lines(self, redirect, captured):
        redirect.write("\n   \n")

        assert captured == []

    def test_empty_write_is_noop(self, redirect, captured):
        redirect.write("")

        assert captured == []

    def test_tee_writes_same_lines_to_file(self, tmp_path, captured):
        """tee：广播与落盘同源（历史页 run.log 与实时日志必须一致）"""
        log_path = tmp_path / "run.log"
        r = LogRedirect(lambda line: captured.append(line))
        r.set_tee(str(log_path))
        try:
            r.write("a\nb\n")
        finally:
            r.close_tee()

        assert captured == ["a", "b"]
        assert log_path.read_text(encoding="utf-8") == "a\nb\n"

    def test_flush_is_noop(self, redirect):
        """flush 不抛异常、不产生输出（兼容 print(flush=True)）"""
        redirect.flush()

        assert redirect.encoding == "utf-8"
        assert redirect.isatty() is False

    def test_fileno_is_invalid(self, redirect):
        """fileno=-1：禁止下游把它当真实文件描述符使用"""
        assert redirect.fileno() == -1

    def test_read_raises(self, redirect):
        with pytest.raises(OSError):
            redirect.read()
