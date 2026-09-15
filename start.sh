#!/usr/bin/env bash
# ============================================================
# DemoVision 设备质检平台 — 一键启动脚本（公开 Demo 版）
#
# 特性：
#   - 默认开启 Demo 模拟模式（DEMOVISION_DEMO_MODE=1）：无需 ROS / SDK / 硬件，
#     全部页面（检测 / SLAM / IMU / 实时大屏 / 视频流 / 历史 / 报告打印）开箱可用。
#   - 数据落 $HOME/demovision_data（可 export DEMOVISION_DATA_DIR 覆盖），
#     首次启动自动预置演示数据。
#   - 首次运行自动安装后端 Python 依赖与前端 npm 依赖。
#   - Ctrl+C 退出时自动停止前后端。
#
# 用法:
#   ./start.sh                     # 默认后端 8010、前端 5173
#   PORT=8000 ./start.sh           # 自定义后端端口（前端代理自动跟随）
#   FRONTEND_PORT=8080 ./start.sh
#   DEMOVISION_DATA_DIR=/data ./start.sh
#   DEMOVISION_DEMO_MODE=0 ./start.sh   # 关闭模拟，切回真实模式（需 ROS/SDK/硬件）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# 端口（可用环境变量覆盖；本机 8000 常被占用，默认 8010）
BACKEND_PORT="${PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PID=""
FRONTEND_PID=""

# 运行环境判定：是否处于 Docker 容器内
if [ -f "/.dockerenv" ]; then CONTAINER=1; else CONTAINER=0; fi

# ---------- 工具函数 ----------
info() { echo -e "\033[1;36m[DemoVision]\033[0m $*"; }
warn() { echo -e "\033[1;33m[DemoVision]\033[0m $*"; }
fail() { echo -e "\033[1;31m[DemoVision]\033[0m $*"; exit 1; }

port_busy() {
  (echo > "/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

# ---------- 0. 路径与环境决策 ----------
export DEMOVISION_DEMO_MODE="${DEMOVISION_DEMO_MODE:-1}"
export DEMOVISION_APP_DIR="${DEMOVISION_APP_DIR:-$SCRIPT_DIR}"
export DEMOVISION_DATA_DIR="${DEMOVISION_DATA_DIR:-$HOME/demovision_data}"
export DEMOVISION_DB_DIR="${DEMOVISION_DB_DIR:-$DEMOVISION_DATA_DIR}"
mkdir -p "$DEMOVISION_DATA_DIR" "$DEMOVISION_DB_DIR"
info "Demo 模式: $DEMOVISION_DEMO_MODE（1=模拟数据，0=真实模式）"
info "数据目录: $DEMOVISION_DATA_DIR"

# ---------- 1. 端口检查 ----------
if port_busy "$BACKEND_PORT"; then
  fail "后端端口 $BACKEND_PORT 已被占用，请用 PORT=xxxx ./start.sh 指定其他端口"
fi
if port_busy "$FRONTEND_PORT"; then
  warn "前端端口 $FRONTEND_PORT 已被占用，vite 将自动使用其他端口（以后续输出为准）"
fi

# ---------- 2. 依赖安装（首次） ----------
if [ "$CONTAINER" = "1" ]; then
  # 容器镜像已内置后端依赖；兜底校验（异常时补装到 pipdeps）
  if ! (cd "$BACKEND_DIR" && python3 -c "import fastapi, uvicorn" 2>/dev/null); then
    info "容器内后端依赖缺失，安装到 pipdeps..."
    pip3 install --target="$BACKEND_DIR/pipdeps" -i https://pypi.tuna.tsinghua.edu.cn/simple \
      -r "$BACKEND_DIR/requirements.txt" || fail "后端依赖安装失败"
  fi
elif [ ! -d "$BACKEND_DIR/pipdeps" ]; then
  info "首次运行，安装后端依赖..."
  pip3 install --target="$BACKEND_DIR/pipdeps" -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r "$BACKEND_DIR/requirements.txt" \
    || fail "后端依赖安装失败，请检查网络"
fi

if [ "$CONTAINER" = "0" ] && [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  info "首次运行，安装前端依赖..."
  (cd "$FRONTEND_DIR" && npm install) || fail "前端依赖安装失败"
fi

# ---------- 3. 启动后端 ----------
info "启动后端: http://127.0.0.1:$BACKEND_PORT"
(
  cd "$BACKEND_DIR"
  export PYTHONPATH="$BACKEND_DIR/pipdeps${PYTHONPATH:+:$PYTHONPATH}"
  exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --access-log
) &
BACKEND_PID=$!

# 等待后端就绪
for _ in $(seq 1 30); do
  if port_busy "$BACKEND_PORT"; then break; fi
  sleep 0.5
done

# ---------- 4. 启动前端（容器内由后端直接伺服 dist，不启 dev server） ----------
if [ "$CONTAINER" = "0" ]; then
  info "启动前端: http://127.0.0.1:$FRONTEND_PORT (代理指向后端 $BACKEND_PORT)"
  (
    cd "$FRONTEND_DIR"
    export BACKEND_PORT FRONTEND_PORT
    exec npm run dev
  ) &
  FRONTEND_PID=$!
fi

# ---------- 5. 退出清理 ----------
cleanup() {
  echo
  info "正在停止服务..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo
if [ "$CONTAINER" = "1" ]; then
  info "容器就绪。浏览器访问: http://127.0.0.1:$BACKEND_PORT/  （后端伺服前端产物）"
else
  info "全部就绪。浏览器访问: http://localhost:$FRONTEND_PORT/"
  echo "    (后端 API/WS 独立地址: http://127.0.0.1:$BACKEND_PORT)"
fi
echo
wait
