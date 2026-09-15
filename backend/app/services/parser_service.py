# -*- coding: utf-8 -*-
"""解析核心脚本生成的落盘报告（00_summary_report.txt / *_stats.txt / 轨迹 CSV）"""
from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional

# ============ 检测汇总报告 ============

SUMMARY_PATTERNS = {
    "total_devices": re.compile(r"设备总数[:：]\s*(\d+)"),
    "color_pass": re.compile(r"Color相机通过[:：]\s*(\d+)\s*/\s*(\d+)"),
    "fisheye_pass": re.compile(r"Fisheye通过[:：]\s*(\d+)\s*/\s*(\d+)"),
    "slam_pass": re.compile(r"SLAM通过[:：]\s*(\d+)\s*/\s*(\d+)"),
    "color_rate": re.compile(r"Color通过率[:：]\s*([\d.]+)%"),
    "fisheye_rate": re.compile(r"Fisheye通过率[:：]\s*([\d.]+)%"),
    "slam_rate": re.compile(r"SLAM通过率[:：]\s*([\d.]+)%"),
    "overall_status": re.compile(r"整体检测状态[:：]\s*(PASS|FAIL)"),
}


def parse_detection_summary(filepath: str) -> Optional[Dict]:
    """解析 00_summary_report.txt，返回结构化结果；文件缺失返回 None"""
    if not filepath or not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    result = {"raw_text": text}
    for key, pattern in SUMMARY_PATTERNS.items():
        m = pattern.search(text)
        if not m:
            continue
        if key == "overall_status":
            result[key] = m.group(1)
        elif key.endswith("_rate"):
            result[key] = float(m.group(1))
        elif key.endswith("_pass"):
            result[key] = {"pass": int(m.group(1)), "total": int(m.group(2))}
        else:
            result[key] = int(m.group(1))

    result["overall_pass"] = (result.get("overall_status") == "PASS")
    return result


# ============ SLAM 统计报告 ============

STATS_PATTERNS = {
    "mean_mm": re.compile(r"平均欧式距离\s*\(Mean\)[:：]\s*([-\d.]+)\s*mm"),
    "std_mm": re.compile(r"标准差\s*\(Std\)[:：]\s*([-\d.]+)\s*mm"),
    "sigma_3": re.compile(r"3σ\s*区间[:：]\s*\[([-\d.]+)\s*,\s*([-\d.]+)\]\s*mm"),
    "qualified": re.compile(r"合格性判断[:：]\s*(合格|不合格)"),
    "count": re.compile(r"有效数据点数[:：]\s*(\d+)"),
}


def parse_slam_stats(filepath: str) -> Optional[Dict]:
    """解析最新 _stats.txt，返回统计字典；文件缺失返回 None"""
    if not filepath or not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    result = {"raw_text": text}
    m = STATS_PATTERNS["mean_mm"].search(text)
    if m:
        result["mean_mm"] = float(m.group(1))
    m = STATS_PATTERNS["std_mm"].search(text)
    if m:
        result["std_mm"] = float(m.group(1))
    m = STATS_PATTERNS["sigma_3"].search(text)
    if m:
        result["sigma_3"] = [float(m.group(1)), float(m.group(2))]
    m = STATS_PATTERNS["qualified"].search(text)
    if m:
        result["is_qualified"] = (m.group(1) == "合格")
    m = STATS_PATTERNS["count"].search(text)
    if m:
        result["count"] = int(m.group(1))
    return result


def find_latest_stats_file(output_dir: str) -> Optional[str]:
    """在 output_dir 下查找最新的 _stats.txt（含子目录递归）"""
    if not output_dir or not os.path.isdir(output_dir):
        return None
    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith("_stats.txt"):
                candidates.append(os.path.join(root, name))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def find_latest_file(output_dir: str, suffix: str) -> Optional[str]:
    """在 output_dir 下查找最新的指定后缀文件（递归）"""
    if not output_dir or not os.path.isdir(output_dir):
        return None
    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith(suffix):
                candidates.append(os.path.join(root, name))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


# ============ SLAM 轨迹 CSV（网页内直接渲染曲线用） ============

_TRAJ_COLS = ("time_since_start_s", "x_m", "y_m", "z_m", "distance_mm")


def parse_slam_trajectory(csv_path: str, max_points: int = 2000) -> Optional[Dict]:
    """把 SLAM 轨迹 CSV 解析成网页绘图用的降采样序列。

    列（scripts/slam_plotter_final.py 产出，实测一致）：
        time_since_start_s, absolute_time, x_m, y_m, z_m, distance_mm

    返回：{t[], x[], y[], z[], dist[], total, sampled}
      - x/y/z 由米换算为毫米（×1000），与实时大屏 / stats 口径一致；
      - dist 直接取 CSV 的 distance_mm（脚本已算好，避免两处口径不一致）；
      - 超过 max_points 时等间隔抽取并强制保留末点，避免一次把 5000+ 点推给前端。
    列按表头名定位（不依赖列序），缺列/坏行安全跳过。
    """
    if not csv_path or not os.path.isfile(csv_path):
        return None
    rows: List[tuple] = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return None
            idx = {}
            for i, h in enumerate(header):
                key = (h or "").strip().lower()
                if key in _TRAJ_COLS:
                    idx[key] = i
            need = ("time_since_start_s", "x_m", "y_m", "z_m")
            if any(k not in idx for k in need):
                return None
            widest = max(idx.values())
            has_dist = "distance_mm" in idx
            for r in reader:
                if not r or len(r) <= widest:
                    continue
                try:
                    t = float(r[idx["time_since_start_s"]])
                    x = float(r[idx["x_m"]]) * 1000.0
                    y = float(r[idx["y_m"]]) * 1000.0
                    z = float(r[idx["z_m"]]) * 1000.0
                    if has_dist and r[idx["distance_mm"]].strip() != "":
                        d = float(r[idx["distance_mm"]])
                    else:
                        d = (x * x + y * y + z * z) ** 0.5
                except (ValueError, IndexError):
                    continue
                rows.append((t, x, y, z, d))
    except OSError:
        return None

    total = len(rows)
    if total == 0:
        return None

    if total > max_points:
        step = total / float(max_points)
        picked = [rows[min(int(i * step), total - 1)] for i in range(max_points)]
        picked[-1] = rows[-1]          # 强制保留末点
        rows = picked

    return {
        "t": [round(r[0], 4) for r in rows],
        "x": [round(r[1], 4) for r in rows],
        "y": [round(r[2], 4) for r in rows],
        "z": [round(r[3], 4) for r in rows],
        "dist": [round(r[4], 4) for r in rows],
        "total": total,
        "sampled": len(rows),
    }


# ============ IMU 陀螺仪校准结果 ============

_IMU_BIAS_PATTERNS = {
    # update_gyro_bias 工具实际落盘格式：GyroBias=         x y z
    "gyro_bias_line": re.compile(r"GyroBias\s*=\s*(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)"),
    # 兼容小写命名 "gyro_bias x: 1.0" 等
    "gyro_bias_x": re.compile(r"gyro_bias[_\s]*x\s*[:=]\s*(-?[\d.eE+-]+)"),
    "gyro_bias_y": re.compile(r"gyro_bias[_\s]*y\s*[:=]\s*(-?[\d.eE+-]+)"),
    "gyro_bias_z": re.compile(r"gyro_bias[_\s]*z\s*[:=]\s*(-?[\d.eE+-]+)"),
    # 兼容 "gyro bias = [x, y, z]" / "(x, y, z)" 等整体输出
    "gyro_bias_vec": re.compile(r"gyro[_\s]*bias[^=]*[=:]\s*[\[\(]([-?\d.eE+-]+)\s*,\s*([-?\d.eE+-]+)\s*,\s*([-?\d.eE+-]+)[\]\)]"),
    "gyro_std": re.compile(r"gyro[_\s]*std\s*[:=]\s*([\d.eE+-]+)"),
    "gyro_mean": re.compile(r"gyro[_\s]*mean\s*[:=]\s*([\d.eE+-]+)"),
}

# update_gyro_bias 工具在 stdout 中打印的失败判定（严格以工具自身判定为准，不写数值阈值）
_IMU_STDOUT_FAIL = re.compile(
    r"(?:failed|fail|cannot\s+connect|cannot\s+load|not\s+modified|"
    r"too\s+high|unable|error|invalid|unexpected|不合格|失败|无效)",
    re.IGNORECASE,
)


def _pick_imu_txt(output_dir: str) -> Optional[str]:
    """选择最新 imu_calib_*.txt，优先 after 产物（校准后的 GyroBias 才有判定意义）"""
    if not output_dir or not os.path.isdir(output_dir):
        return None
    candidates = []
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith(".txt") and "imu_calib" in name:
                candidates.append(os.path.join(root, name))
    if not candidates:
        return None
    after = [c for c in candidates if "after" in os.path.basename(c)]
    pool = after or candidates
    return max(pool, key=os.path.getmtime)


def parse_imu_calibration_result(output_dir: str) -> Optional[Dict]:
    """解析最新 imu_calib_*.txt，提取偏置数据与合格性判断；无产物返回 None

    合格性判定（严禁数值阈值，一律以工具自身判定为准）：
      1) 若存在工具 stdout 日志 imu_calib_run.log，以其中打印的判定结果为准；
      2) 否则只要能成功解析出 GyroBias 行，即判定 qualified = True。
    """
    txt_path = _pick_imu_txt(output_dir)
    if not txt_path:
        return None
    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    result = {"raw_text": text}
    for key, pattern in _IMU_BIAS_PATTERNS.items():
        m = pattern.search(text)
        if not m:
            continue
        if key == "gyro_bias_line":
            result["gyro_bias_x"] = float(m.group(1))
            result["gyro_bias_y"] = float(m.group(2))
            result["gyro_bias_z"] = float(m.group(3))
        elif key == "gyro_bias_vec":
            result["gyro_bias_x"] = float(m.group(1))
            result["gyro_bias_y"] = float(m.group(2))
            result["gyro_bias_z"] = float(m.group(3))
        else:
            result[key] = float(m.group(1))

    # 合格性判定：优先工具 stdout 日志中的判定结果；无日志时以 GyroBias 行能否解析为准
    stdout_log = os.path.join(output_dir, "imu_calib_run.log")
    has_bias = "gyro_bias_x" in result or "gyro_bias_vec" in result
    if os.path.exists(stdout_log):
        with open(stdout_log, "r", encoding="utf-8", errors="ignore") as f:
            log_text = f.read()
        if _IMU_STDOUT_FAIL.search(log_text):
            result["qualified"] = False
        else:
            result["qualified"] = has_bias
    else:
        result["qualified"] = has_bias
    return result
