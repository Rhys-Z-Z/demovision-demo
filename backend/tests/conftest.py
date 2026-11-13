# -*- coding: utf-8 -*-
"""pytest 全局配置与共享 fixture —— 本项目测试重构的核心。

为什么需要这个文件（旧 run_all.py 子进程隔离问题的根治）：
    app/config.py 的 DATA_DIR / DB_DIR / DEMO_MODE 是 import 时固化的模块级
    常量（进程级缓存）。旧 unittest 版每个测试文件在"模块顶层"setdefault
    环境变量再 import，谁先被导入谁说了算；pytest 按文件名字母序收集
    （date_key → paths → slam_archive → snapshot），test_date_key 先固化了
    DATA_DIR，轮到 test_paths 再改环境变量已经无效，其 6 个用例全部 skip。
    旧 run_all.py 的解法是每个模块开一个子进程（慢、报告割裂、无法单跑调试）。

    conftest.py 在 pytest 收集阶段、任何测试模块 import 之前加载，
    在这里一次性定死环境变量，所有模块看到的 app.config 完全一致，
    17 个用例就能在 1 个进程里跑完。
"""
from __future__ import annotations

import asyncio
import os
import tempfile

# ===== 1. 进程级环境裁决（必须发生在任何 import app.* 之前） =====
# 注意用直接赋值而非 setdefault：测试必须隔离外部环境，
# 否则 shell 里残留的 export DEMOVISION_DATA_DIR 会悄悄改变测试行为。
_TMP_ROOT = tempfile.mkdtemp(prefix="demovision_pytest_")
os.environ["DEMOVISION_DATA_DIR"] = os.path.join(_TMP_ROOT, "data")
os.environ["DEMOVISION_DB_DIR"] = os.path.join(_TMP_ROOT, "db")
# 统一真实模式：snapshot 的 SSRF / 抓帧失败用例需要走 httpx 路径；
# 其余被测函数（paths / slam._finalize / parser）不依赖 DEMO_MODE，
# 真实模式下整套测试行为完全确定。
os.environ["DEMOVISION_DEMO_MODE"] = "0"

import pytest  # noqa: E402


# ===== 2. 共享 fixture =====
@pytest.fixture(scope="session")
def data_dir() -> str:
    """数据根目录（与上面 env 同源）。

    scope="session"：整个测试会话只求值一次，所有用例共享同一实例。
    取代旧版 test_paths.setUpClass 里手写的 mkdtemp + skipTest 兜底。
    """
    from app.config import DATA_DIR
    return DATA_DIR


@pytest.fixture(scope="session", autouse=True)
def _init_db() -> None:
    """整个会话建一次库表。

    autouse=True：无需用例显式声明参数，收集完成后自动执行一次。
    取代旧版散在 test_slam_archive.setUpClass 的 asyncio.run(init_db())。
    """
    from app.db.database import init_db
    asyncio.run(init_db())


@pytest.fixture(autouse=True)
def _clean_runtime_state() -> None:
    """每个用例前后清空各模块的进程级运行态（function 级：每用例一次）。

    slam.py 的 _tasks/_processes/_finalized、detection.py 的 _running_task
    都是模块级可变状态，跨用例残留会让"互斥/归档"断言互相串扰。
    autouse + yield 前后各清一次，等价于旧版 setUp 里的 clear()，
    但对所有测试模块生效，且新增模块只需在这里补一行。
    """
    from app.api import detection, slam

    def _reset() -> None:
        slam._tasks.clear()
        slam._processes.clear()
        slam._finalized.clear()
        detection._running_task = None

    _reset()
    yield
    _reset()
