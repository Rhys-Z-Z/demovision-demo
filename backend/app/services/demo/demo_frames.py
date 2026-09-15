# -*- coding: utf-8 -*-
"""Demo 视频帧渲染：Pillow 生成 640×360 JPEG（渐变底 + 网格 + 话题名 + 时间戳）。

供实时视频流（video_streamer demo 分支）与截图（snapshot demo 分支）共用。
另提供 SLAM 轨迹 PNG 渲染（纯 Pillow，无 matplotlib/Tk 依赖），
供 seed_demo_data 预置产物与 scripts/slam_plotter_final.py 模拟器共用同一风格。
"""
from __future__ import annotations

import colorsys
import csv
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except Exception:  # noqa: BLE001
    _HAS_PIL = False


def _ensure_font(size: int):
    """优先用 DejaVu Sans（多数 Linux 自带），失败退回默认字体"""
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def render_frame(topic: str, width: int = 640, height: int = 360) -> bytes:
    """渲染一帧模拟图像，返回 JPEG 字节（非法图像/无 Pillow 时返回占位 JPEG 头帧）"""
    if not _HAS_PIL:
        return _placeholder_jpeg()
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    # 渐变底（上浅下深，品牌青蓝调）
    top, bottom = (24, 60, 90), (8, 20, 34)
    for y in range(height):
        k = y / max(height - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * k)
        g = int(top[1] + (bottom[1] - top[1]) * k)
        b = int(top[2] + (bottom[2] - top[2]) * k)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    # 网格
    for x in range(0, width, 64):
        draw.line([(x, 0), (x, height)], fill=(255, 255, 255, 18), width=1)
    for y in range(0, height, 64):
        draw.line([(0, y), (width, y)], fill=(255, 255, 255, 18), width=1)
    # 中心十字 + 光标圆（模拟取景框）
    cx, cy = width // 2, height // 2
    draw.ellipse([cx - 46, cy - 46, cx + 46, cy + 46],
                 outline=(120, 200, 255), width=2)
    draw.line([(cx - 64, cy), (cx - 20, cy)], fill=(120, 200, 255), width=2)
    draw.line([(cx + 20, cy), (cx + 64, cy)], fill=(120, 200, 255), width=2)
    draw.line([(cx, cy - 64), (cx, cy - 20)], fill=(120, 200, 255), width=2)
    draw.line([(cx, cy + 20), (cx, cy + 64)], fill=(120, 200, 255), width=2)
    # 文本：话题名 + 时间戳 + Demo 标识
    font = _ensure_font(16)
    draw.text((12, 10), topic, fill=(200, 230, 255), font=font)
    draw.text((12, height - 28),
              f"{datetime.now():%Y-%m-%d %H:%M:%S}", fill=(160, 190, 220), font=font)
    draw.text((width - 180, height - 28), "DemoVision 模拟信号",
              fill=(120, 200, 255), font=font)
    buf = __import__("io").BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def plot_trajectory_png(csv_path: str, png_path: str) -> bool:
    """将 SLAM 轨迹 CSV 渲染为轨迹 PNG（纯 Pillow，无 matplotlib/Tk 依赖）。

    数据列约定与 slam_plotter_final 输出一致（表头 6 列）：
      time_since_start_s, absolute_time, x_m, y_m, z_m, distance_mm
    渲染失败返回 False（调用方不应阻断任务）。
    """
    if not _HAS_PIL:
        return False
    ts, xs, ys = [], [], []
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 5 or not row[0].strip().replace(".", "", 1).isdigit():
                continue
            try:
                ts.append(float(row[0]))
                xs.append(float(row[2]) * 1000.0)  # 米 → 毫米
                ys.append(float(row[3]) * 1000.0)
            except (ValueError, IndexError):
                continue
    if len(ts) < 10:
        return False

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
    draw.text((L, 10), "DemoVision SLAM Trajectory (Simulated)",
              fill=(30, 40, 50), font=_ensure_font(15))
    font = _ensure_font(13)
    draw.text((L + pw / 2 - 18, T + ph + 12), "X (mm)", fill=(60, 60, 60), font=font)
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
    draw.text((cb_x0 - 12, cb_y1 + 6), "t (s)", fill=(60, 60, 60), font=font)
    draw.text((cb_x0 - 30, cb_y0 - 16), f"{tmax:.0f}", fill=(60, 60, 60), font=font)

    img.save(png_path, format="PNG")
    return True


def _placeholder_jpeg() -> bytes:
    """最小合法 JPEG（1×1 灰色），确保无 Pillow 时视频流/截图不崩"""
    # 1x1 灰度 JPEG 的静态字节
    return bytes.fromhex(
        "FFD8FFE000104A46494600010100000100010000FFDB004300080606070605080707"
        "0709090A0C140D0C0B0B0C1912130F141D1A1F1E1D1A1C1C20242E2720222C231C1C"
        "2837292C30313434341F27393D38323C2E333432FFC0000B080001000101011100FF"
        "C4001F0000010501010101010100000000000000000102030405060708090A0BFFC4"
        "00B5100002010303020403050504040000017D010203000411051221314106135161"
        "07227114328191A1082342B1C11552D1F02433627282090A161718191A2526272829"
        "2A3435363738393A434445464748494A535455565758595A636465666768696A7374"
        "75767778797A838485868788898A92939495969798999AA2A3A4A5A6A7A8A9AAB2B3"
        "B4B5B6B7B8B9BAC2C3C4C5C6C7C8C9CAD2D3D4D5D6D7D8D9DAE1E2E3E4E5E6E7E8"
        "E9EAF1F2F3F4F5F6F7F8F9FAFFC4001F010003010101010101010101000000000000"
        "0102030405060708090A0BFFC400B511000201020404030407050404000102770001"
        "02031104052131061241510761711322328108144291A1B1C109233352F0156272D1"
        "0A162434E125F11718191A262728292A35363738393A434445464748494A53545556"
        "5758595A636465666768696A737475767778797A82838485868788898A9293949596"
        "9798999AA2A3A4A5A6A7A8A9AAB2B3B4B5B6B7B8B9BAC2C3C4C5C6C7C8C9CAD2D3"
        "D4D5D6D7D8D9DAE2E3E4E5E6E7E8E9EAF2F3F4F5F6F7F8F9FAFFDA000C03010002"
        "110311003F00E7EAE8000000FFD9"
    )
