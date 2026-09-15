#!/usr/bin/env bash
# ============================================================
# DemoVision IMU 陀螺仪校准工具 — DEMO SIMULATOR
#
# 公开 Demo 版：本脚本是产线 update_gyro_bias 工具的**模拟实现**，
# 不依赖真实 USB 设备与动态库，仅打印 reset → calib → verify 阶段日志
# 并落盘模拟产物（imu_calib_before.txt / imu_calib_after.txt / imu_calib_after.bin）。
#
# 契约（backend IMUCalibRunner 判定成功 = returncode==0 且目录有 .txt）：
#   bash run_update_gyro_bias.sh <duration>
#
# 注意：stdout 不得出现失败语义关键字（failed/fail/cannot/error/不合格/失败 等），
#       否则 parser_service 会把任务判为不合格。
# ============================================================
DURATION="${1:-5}"

# 用 duration 缩到 1s 内做演示节奏（真实采集不做，仅模拟）
SIM_SECONDS=$((DURATION > 2 ? 2 : DURATION))
[ "$SIM_SECONDS" -lt 1 ] && SIM_SECONDS=1

echo "============================================================"
echo "DemoVision IMU 陀螺仪校准（DEMO 模拟器）"
echo "============================================================"

# ---- 阶段 1: reset ----
echo "[1/3] reset: 重置陀螺仪偏置..."
sleep "$SIM_SECONDS"
cat > imu_calib_before.txt <<'EOF'
DemoVision IMU calibration (DEMO)
Stage: before
GyroBias= 0.0000 0.0000 0.0000
EOF
echo "      已写入 imu_calib_before.txt"

# ---- 阶段 2: calib ----
echo "[2/3] calib: 采集陀螺仪数据并计算偏置（采样中）..."
sleep "$SIM_SECONDS"

# ---- 阶段 3: verify ----
echo "[3/3] verify: 校验校准结果..."
sleep "$SIM_SECONDS"
echo "      GyroBias= 0.0012 -0.0008 0.0003"

cat > imu_calib_after.txt <<'EOF'
DemoVision IMU calibration (DEMO)
Stage: after
GyroBias= 0.0012 -0.0008 0.0003
Result: pass
EOF

# 模拟二进制产物（偏置原始记录占位）
printf 'DEMO-BIAS-0.0012--0.0008-0.0003\n' > imu_calib_after.bin

echo "      已写入 imu_calib_after.txt / imu_calib_after.bin"
echo "============================================================"
echo "DemoVision IMU 校准完成"
echo "============================================================"
exit 0
