# ============================================================
# DemoVision 设备质检平台 — Docker 演示镜像（公开 Demo 版）
#
# 构建（从 demovision-demo 仓库根执行）：
#   docker build -t demovision-demo .
#
# 运行：
#   docker run -d -p 8010:8010 --name demovision-demo demovision-demo
#   浏览器访问 http://127.0.0.1:8010/
#
# 特性：
#   - 默认 Demo 模拟模式：无需 ROS / SDK / 硬件，全部页面开箱可用
#   - 数据落 /app/demo_data（可用 -v 挂载持久化）
#   - 前端构建产物由后端直接伺服（无需 Node/nginx）
# ============================================================
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    DEMOVISION_DEMO_MODE=1 \
    DEMOVISION_APP_DIR=/app \
    DEMOVISION_DATA_DIR=/app/demo_data \
    DEMOVISION_DB_DIR=/app/demo_data

WORKDIR /app

# 先装依赖（利用层缓存）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 拷贝程序本体
COPY backend /app/backend
COPY scripts /app/scripts
COPY imu_tool /app/imu_tool
COPY frontend/dist /app/frontend/dist
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh \
    && mkdir -p /app/demo_data

EXPOSE 8010

CMD ["/app/start.sh"]
