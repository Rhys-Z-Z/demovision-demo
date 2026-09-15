#!/bin/bash
# ============================================================
# DemoVision Web 系统 — 一键部署脚本（全新 Ubuntu 机器）
#
# 作用：将本代码树部署到 FHS 标准目录，供 start.sh 一键启动。
#   APP_DIR  /opt/demovision_web            （程序本体：后端 + 前端产物 + 脚本 + IMU 工具）
#   DATA_DIR /var/lib/demovision_web/data   （业务数据，测试产物落盘区）
#   DB_DIR   /var/lib/demovision_web/db     （系统数据库）
#
# 用法：sudo bash install.sh
# 部署完成后用：sudo /opt/demovision_web/start.sh 启动
# ============================================================
set -e

echo "===== 开始安装 DemoVision Web 系统 ====="
APP_DIR="/opt/demovision_web"
DATA_DIR="/var/lib/demovision_web/data"
DB_DIR="/var/lib/demovision_web/db"

# 脚本自身目录（含 backend / frontend / imu_tool / start.sh）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 核心脚本随 scripts/ 一起部署（ship_out.py / slam_plotter_final.py）
CORE_SCRIPTS_DIR="$SCRIPT_DIR/scripts"

mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$DB_DIR"
mkdir -p "$APP_DIR/scripts"

# 拷贝文件
cp -rf "$SCRIPT_DIR/backend" "$APP_DIR/"
cp -rf "$SCRIPT_DIR/frontend/dist" "$APP_DIR/frontend/dist"
cp -rf "$SCRIPT_DIR/imu_tool" "$APP_DIR/"
cp -f "$CORE_SCRIPTS_DIR/ship_out.py" "$APP_DIR/scripts/"
cp -f "$CORE_SCRIPTS_DIR/slam_plotter_final.py" "$APP_DIR/scripts/"
cp -f "$SCRIPT_DIR/start.sh" "$APP_DIR/"

chmod +x "$APP_DIR/start.sh"

# 重建后端依赖
echo "===== 安装后端 Python 依赖 ====="
rm -rf "$APP_DIR/backend/pipdeps"
mkdir -p "$APP_DIR/backend/pipdeps"
pip3 install --target "$APP_DIR/backend/pipdeps" -r "$APP_DIR/backend/requirements.txt"

echo "===== 安装完成 ====="
echo "请使用: sudo $APP_DIR/start.sh  启动系统"
echo "数据目录: $DATA_DIR / $DB_DIR"