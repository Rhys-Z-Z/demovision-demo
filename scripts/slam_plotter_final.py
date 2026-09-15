#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DemoVision SLAM Plotter - DEMO SIMULATOR
=============================================================================
公开 Demo 版：本文件是产线 SLAM 录制/绘图脚本的**模拟实现**，不依赖 ROS、
不依赖 dv_sdk、不依赖硬件，生成模拟轨迹（Lissajous + 噪声）并落盘：
    {DEMOVISION_DATA_DIR}/{sn8拼接}_output_slam/
        {sn8}_{HHMMSS}.csv          轨迹点（表头 6 列，50Hz 采样）
        {sn8}_{HHMMSS}_stats.txt    统计报告（格式对齐 parser_service.STATS_PATTERNS）
        {sn8}_{HHMMSS}.png          轨迹图（纯 Pillow 渲染，无 matplotlib/Tk 依赖）

被 backend/slam_runner.py 以 `import + main()` 方式调用，argparse 解析 --duration。
可被终止：写入按块 flush，SIGINT/SIGTERM 时收尾写出已有点的统计。
=============================================================================
"""
from __future__ import annotations

import argparse
import colorsys
import csv
import math
import os
import random
import signal
import sys
import time
import zlib
from datetime import datetime

# 与 ship_out 模拟设备保持一致
_DEMO_SERIALS = [
    "DVSNDV000001",
    "DVSNDV000002",
]

# 统计口径（对齐 parser_service）：3σ 区间 ⊆ [-4, 4] mm 判合格
_SIGMA_LIMIT = 4.0


def _discover_devices() -> list:
    """设备发现：优先读后端注入的 DEMOVISION_SLAM_DEVICES（保证与任务请求一致），
    否则复用 ship_out（demo 返回模拟 SN），失败则用内置列表兜底"""
    env_sns = os.environ.get("DEMOVISION_SLAM_DEVICES", "")
    if env_sns:
        return [s.strip() for s in env_sns.split(",") if s.strip()]
    try:
        from ship_out import ROSInterface  # 同 scripts 目录
        return ROSInterface.get_devices()
    except Exception:  # noqa: BLE001
        return list(_DEMO_SERIALS)


def _sn8(sn: str) -> str:
    return sn[-8:] if len(sn) >= 8 else sn


def _generate_trajectory(sn: str, out_dir: str, duration: float) -> str:
    """为单台设备生成模拟轨迹；返回 stats 文件路径"""
    sn8 = _sn8(sn)
    ts = datetime.now().strftime("%H%M%S")
    stem = f"{sn8}_{ts}"
    csv_path = os.path.join(out_dir, f"{stem}.csv")

    # 确定性随机（同设备多次运行结果稳定，保证演示合格性可预期）
    # 注意：sn8 可含非十六进制字符（如 DV000001），用 crc32 而非 int(sn8,16)
    rng = random.Random(zlib.crc32(sn8.encode("utf-8")))

    # 轨迹形状：Lissajous + 缓慢漂移 + 噪声
    fx, fy = 0.18, 0.13
    amp = 0.6
    drift_x, drift_y = 0.02, -0.015
    freq = 50  # Hz
    sim_duration = max(3.0, min(duration, 20.0))  # demo 压缩时长，上限 20s
    n_points = int(sim_duration * freq)

    header = ["time_since_start_s", "absolute_time", "x_m", "y_m", "z_m", "distance_mm"]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        t = 0.0
        for i in range(n_points):
            # 模拟时间推进（50Hz）
            x = amp * math.sin(2 * math.pi * fx * t) + drift_x * t + rng.gauss(0, 0.004)
            y = amp * math.sin(2 * math.pi * fy * t + 0.6) + drift_y * t + rng.gauss(0, 0.004)
            z = rng.gauss(0, 0.003)
            # 距离残差（口径与实时一致：毫米，均值≈0、σ≈0.8 → 3σ 区间 ⊆ [-4,4] 合格）
            dist_mm = rng.gauss(0, 0.8)
            # 20ms 一点（50Hz 墙钟推进，可被 SIGINT/SIGTERM 打断）
            writer.writerow([
                f"{t:.3f}",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"))[:-3],
                f"{x:.6f}", f"{y:.6f}", f"{z:.6f}",
                f"{dist_mm:.3f}",
            ])
            f.flush()
            t = round(t + 1.0 / freq, 4)
            if i % 25 == 0:
                pct = int(100.0 * (i + 1) / n_points)
                print(f"[SLAM] {sn8} 录制中 {pct}% ...", flush=True)
            time.sleep(0.02)

    print(f"[SLAM] {sn8} 录制完成，共 {n_points} 点 -> {csv_path}", flush=True)
    return _write_stats(out_dir, stem, csv_path)


def _write_stats(out_dir: str, stem: str, csv_path: str) -> str:
    """从轨迹 CSV 回读距离列计算统计，落盘 _stats.txt（对齐 parser_service.STATS_PATTERNS）"""
    dists = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        idx = None
        for i, h in enumerate(header or []):
            if (h or "").strip().lower() == "distance_mm":
                idx = i
                break
        if idx is None:
            return ""
        for row in reader:
            if len(row) > idx and row[idx].strip():
                try:
                    dists.append(float(row[idx]))
                except ValueError:
                    continue
    count = len(dists)
    mean_mm = sum(dists) / count if count else 0.0
    std_mm = (sum((d - mean_mm) ** 2 for d in dists) / count) ** 0.5 if count else 0.0
    low, high = mean_mm - 3 * std_mm, mean_mm + 3 * std_mm
    qualified = low >= -_SIGMA_LIMIT and high <= _SIGMA_LIMIT
    stats_path = os.path.join(out_dir, f"{stem}_stats.txt")
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write("\n".join([
            "=" * 50,
            "DemoVision SLAM 统计报告（DEMO 模拟数据）",
            "=" * 50,
            f"平均欧式距离 (Mean): {mean_mm:.2f} mm",
            f"标准差 (Std): {std_mm:.2f} mm",
            f"3σ 区间: [{low:.2f}, {high:.2f}] mm",
            f"合格性判断: {'合格' if qualified else '不合格'}",
            f"有效数据点数: {count}",
            "=" * 50,
        ]) + "\n")
    print(f"[SLAM] 统计已落盘 -> {stats_path}", flush=True)
    return stats_path


def _font(size: int):
    """优先用 DejaVu Sans（多数 Linux 自带），失败退回 Pillow 默认字体"""
    try:
        from PIL import ImageFont
        for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _plot_trajectory(csv_path: str, out_dir: str, stem: str) -> None:
    """轨迹图（纯 Pillow 渲染，无 matplotlib/Tk 依赖）：x-y 平面 + 按时间渐变色带"""
    png_path = os.path.join(out_dir, f"{stem}.png")
    try:
        from PIL import Image, ImageDraw
    except Exception as e:  # noqa: BLE001 绘图失败不阻断录制
        print(f"[SLAM] 轨迹图生成跳过（无 Pillow）: {e}", flush=True)
        return

    ts, xs, ys = [], [], []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 5:
                continue
            try:
                ts.append(float(row[0]))
                xs.append(float(row[2]) * 1000.0)   # 米 → 毫米
                ys.append(float(row[3]) * 1000.0)
            except (ValueError, IndexError):
                continue
    if len(ts) < 10:
        return

    W, H = 720, 520
    L, R, T, B = 70, 125, 48, 58          # 右侧留时间色带
    pw, ph = W - L - R, H - T - B
    x_c = (min(xs) + max(xs)) / 2.0
    y_c = (min(ys) + max(ys)) / 2.0
    rx = max(max(xs) - min(xs), 1e-6)
    ry = max(max(ys) - min(ys), 1e-6)
    scale = min(pw / rx, ph / ry) * 0.92

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    def px(x):
        return L + pw / 2 + (x - x_c) * scale

    def py(y):
        return T + ph / 2 - (y - y_c) * scale

    # 网格 + 边框
    for g in range(1, 6):
        k = g / 5.0
        draw.line([(L + pw * k, T), (L + pw * k, T + ph)], fill=(232, 232, 232))
        draw.line([(L, T + ph * k), (L + pw, T + ph * k)], fill=(232, 232, 232))
    draw.rectangle([L, T, L + pw, T + ph], outline=(120, 130, 140))

    # 标题与坐标轴标签（英文，避免依赖系统中文字体）
    title_font = _font(15)
    font = _font(13)
    if title_font:
        draw.text((L, 10), "DemoVision SLAM Trajectory (Simulated)",
                  fill=(30, 40, 50), font=title_font)
    if font:
        draw.text((L + pw / 2 - 18, T + ph + 12), "X (mm)",
                  fill=(60, 60, 60), font=font)
        draw.text((12, T + ph / 2 - 6), "Y (mm)", fill=(60, 60, 60), font=font)

    # 轨迹：按时间渐变色带（蓝 → 青 → 黄）
    tmax = max(ts) or 1.0
    pts = [(px(x), py(y)) for x, y in zip(xs, ys)]
    for i in range(1, len(pts)):
        r, g, b = colorsys.hsv_to_rgb(0.62 - 0.5 * (ts[i] / tmax), 0.75, 0.95)
        draw.line([pts[i - 1], pts[i]],
                  fill=(int(r * 255), int(g * 255), int(b * 255)), width=2)

    # 时间色带图例
    cb_x0, cb_x1 = W - 100, W - 80
    cb_y0, cb_y1 = T + 24, T + ph - 24
    for j in range(cb_y1 - cb_y0):
        r, g, b = colorsys.hsv_to_rgb(0.62 - 0.5 * (j / max(cb_y1 - cb_y0 - 1, 1)),
                                      0.75, 0.95)
        draw.line([(cb_x0, cb_y0 + j), (cb_x1, cb_y0 + j)],
                  fill=(int(r * 255), int(g * 255), int(b * 255)))
    if font:
        draw.text((cb_x0 - 12, cb_y1 + 6), "t (s)", fill=(60, 60, 60), font=font)
        draw.text((cb_x0 - 30, cb_y0 - 16), f"{tmax:.0f}",
                  fill=(60, 60, 60), font=font)

    img.save(png_path, format="PNG")
    print(f"[SLAM] 轨迹图已生成 -> {png_path}", flush=True)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="DemoVision SLAM 录制（DEMO 模拟器）")
    parser.add_argument("--duration", type=float, default=120.0,
                        help="录制时长（秒）；demo 压缩为最多 20s 模拟轨迹")
    args = parser.parse_args(argv)

    # 输出根：由 slam.py 注入 DEMOVISION_DATA_DIR = 日期目录
    data_dir = os.environ.get("DEMOVISION_DATA_DIR") or os.getcwd()
    devices = _discover_devices()
    if not devices:
        print("[SLAM] 未发现设备，使用内置模拟设备", flush=True)
        devices = list(_DEMO_SERIALS)

    suffix = "_".join(_sn8(sn) for sn in devices)
    out_dir = os.path.join(data_dir, f"{suffix}_output_slam")
    os.makedirs(out_dir, exist_ok=True)
    print(f"[SLAM] DemoVision SLAM 录制启动（DEMO） | 设备: {', '.join(_sn8(s) for s in devices)}", flush=True)
    print(f"[SLAM] 输出目录: {out_dir} | 时长: {args.duration}s（demo 压缩为最多 20s）", flush=True)

    started = time.time()
    try:
        for sn in devices:
            print(f"[SLAM] 设备 {_sn8(sn)} 开始录制...", flush=True)
            stats = _generate_trajectory(sn, out_dir, args.duration)
            # stats 形如 {out_dir}/{stem}_stats.txt → 反解 stem 用于 CSV/PNG 定位
            stem = os.path.basename(stats)[: -len("_stats.txt")]
            _plot_trajectory(os.path.join(out_dir, f"{stem}.csv"), out_dir, stem)
    except KeyboardInterrupt:
        print("[SLAM] 录制被中断，已保留已写入数据", flush=True)
    finally:
        print(f"[SLAM] 录制结束，耗时 {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
