# -*- coding: utf-8 -*-
"""Demo 模式模拟包：无硬件/ROS 环境下提供同构的实时数据源。

约定：
    - 所有 demo 逻辑集中在本包，业务文件只留单行 DEMO_MODE 分支；
    - 对外消息结构/量纲与真实模式完全一致（WS 消息 shape 变更会被前端静默丢弃）；
    - 顶层禁止 import rospy。
"""
