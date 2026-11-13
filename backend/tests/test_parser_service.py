# -*- coding: utf-8 -*-
"""parser_service 契约测试 —— 本项目最重要的一层测试。

为什么值得测（对应 expand_design 的"契约"概念）：
    parser_service 的三组正则是「脚本产物 ↔ 数据库 ↔ 历史页/打印报告」
    三方的唯一契约：ship_out / slam_plotter_final / imu_tool 产出的文本
    格式一旦变动，解析会静默漏字段，历史页与报告打印随之出错且无报错。
    本文件把"哪些文本格式必须永远能解析"固化为可执行断言。

测试文本全部对齐真实产物格式（scripts/ship_out.py、slam_plotter_final.py、
imu_tool/run_update_gyro_bias.sh），不是自造格式 —— 否则测的是想象中的契约。

覆盖的输入类别：
    parse_detection_summary  完整 PASS/FAIL、缺字段、文件缺失、中英文冒号变体
    parse_slam_stats         完整统计、合格/不合格、负数均值、文件缺失
    parse_slam_trajectory    正常换算、降采样保末点、缺 dist 列回退计算、
                             缺必需列、坏行跳过、空文件
    parse_imu_calibration_result  after/before 产物、stdout 失败关键字、
                             向量格式偏置、空目录
"""
from __future__ import annotations

import csv
import math

import pytest

from app.services import parser_service as ps


# ============================================================
# 1. parse_detection_summary —— 检测汇总报告契约
# ============================================================

# 与 ship_out.ReportGenerator.generate_reports 输出逐字段对齐
_SUMMARY_PASS = "\n".join([
    "=" * 60,
    "DemoVision 设备检测汇总报告",
    "=" * 60,
    "生成时间: 2026-09-15 10:00:00",
    "检测设备: DV000001",
    "",
    "设备总数: 2",
    "Color相机通过: 2/2",
    "Fisheye通过: 2/2",
    "SLAM通过: 1/2",
    "Color通过率: 100.0%",
    "Fisheye通过率: 100.0%",
    "SLAM通过率: 50.0%",
    "",
    "整体检测状态: PASS",
    "=" * 60,
])


class TestParseDetectionSummary:
    def test_full_pass_report_all_fields(self, tmp_path):
        """完整报告 → 8 个字段全部解析，overall_pass=True"""
        f = tmp_path / "00_summary_report.txt"
        f.write_text(_SUMMARY_PASS, encoding="utf-8")

        result = ps.parse_detection_summary(str(f))

        assert result is not None
        assert result["total_devices"] == 2
        assert result["color_pass"] == {"pass": 2, "total": 2}
        assert result["fisheye_pass"] == {"pass": 2, "total": 2}
        assert result["slam_pass"] == {"pass": 1, "total": 2}
        assert result["color_rate"] == 100.0
        assert result["fisheye_rate"] == 100.0
        assert result["slam_rate"] == 50.0
        assert result["overall_status"] == "PASS"
        assert result["overall_pass"] is True
        assert "设备总数" in result["raw_text"]  # 原文始终带回传

    def test_fail_report(self, tmp_path):
        """整体状态 FAIL → overall_pass=False（判定与文本同源）"""
        f = tmp_path / "00_summary_report.txt"
        f.write_text(_SUMMARY_PASS.replace("整体检测状态: PASS",
                                           "整体检测状态: FAIL"), encoding="utf-8")

        result = ps.parse_detection_summary(str(f))

        assert result["overall_status"] == "FAIL"
        assert result["overall_pass"] is False

    def test_missing_file_returns_none(self, tmp_path):
        """文件缺失 → None（调用方据此回退 report.overall_status）"""
        assert ps.parse_detection_summary(str(tmp_path / "no_such.txt")) is None

    def test_partial_fields_are_kept_not_crash(self, tmp_path):
        """缺某行 → 缺的键不在结果里，其余照常解析（宽容降级语义）"""
        text = "\n".join(
            line for line in _SUMMARY_PASS.splitlines()
            if not line.startswith("SLAM通过率")
        )
        f = tmp_path / "00_summary_report.txt"
        f.write_text(text, encoding="utf-8")

        result = ps.parse_detection_summary(str(f))

        assert "slam_rate" not in result
        assert result["slam_pass"] == {"pass": 1, "total": 2}
        assert result["overall_pass"] is True

    @pytest.mark.parametrize("colon", [":", "："],
                             ids=["ascii-colon", "fullwidth-colon"])
    def test_colon_variant(self, tmp_path, colon):
        """正则 [:：] 同时兼容中英文冒号 —— 产线脚本与手写报告都不得解析失败"""
        text = _SUMMARY_PASS.replace("设备总数:", f"设备总数{colon}")
        f = tmp_path / "00_summary_report.txt"
        f.write_text(text, encoding="utf-8")

        result = ps.parse_detection_summary(str(f))

        assert result["total_devices"] == 2


# ============================================================
# 2. parse_slam_stats —— SLAM 统计报告契约
# ============================================================

# 与 slam_plotter_final._write_stats 输出逐字段对齐
def _stats_text(mean="2.50", std="0.50", sigma="[-4.00, 4.00]",
                verdict="合格", count="100") -> str:
    return "\n".join([
        "=" * 50,
        "DemoVision SLAM 统计报告",
        "=" * 50,
        f"平均欧式距离 (Mean): {mean} mm",
        f"标准差 (Std): {std} mm",
        f"3σ 区间: {sigma} mm",
        f"合格性判断: {verdict}",
        f"有效数据点数: {count}",
        "=" * 50,
    ])


class TestParseSlamStats:
    def test_full_stats(self, tmp_path):
        f = tmp_path / "DV000001_120000_stats.txt"
        f.write_text(_stats_text(), encoding="utf-8")

        result = ps.parse_slam_stats(str(f))

        assert result["mean_mm"] == pytest.approx(2.5)
        assert result["std_mm"] == pytest.approx(0.5)
        assert result["sigma_3"] == pytest.approx([-4.0, 4.0])
        assert result["is_qualified"] is True
        assert result["count"] == 100

    @pytest.mark.parametrize("verdict, expected", [
        ("合格", True),
        ("不合格", False),
    ], ids=["qualified", "unqualified"])
    def test_verdict_mapping(self, tmp_path, verdict, expected):
        """合格性判断以工具文本为准 —— is_qualified 必须与文本严格对应"""
        f = tmp_path / "s_stats.txt"
        f.write_text(_stats_text(verdict=verdict), encoding="utf-8")

        result = ps.parse_slam_stats(str(f))

        assert result["is_qualified"] is expected

    def test_negative_mean(self, tmp_path):
        """均值可为负（[-\\d.]+ 正则覆盖负号）—— 回归保护"""
        f = tmp_path / "s_stats.txt"
        f.write_text(_stats_text(mean="-2.50", std="0.50"), encoding="utf-8")

        result = ps.parse_slam_stats(str(f))

        assert result["mean_mm"] == pytest.approx(-2.5)

    def test_missing_file_returns_none(self, tmp_path):
        assert ps.parse_slam_stats(str(tmp_path / "no_such_stats.txt")) is None


# ============================================================
# 3. parse_slam_trajectory —— 轨迹 CSV 解析与降采样
# ============================================================

_HEADER = ["time_since_start_s", "absolute_time",
           "x_m", "y_m", "z_m", "distance_mm"]


def _write_csv(tmp_path, rows, header=None) -> str:
    """写一份轨迹 CSV；rows 为每行字段列表（长度须与 header 一致）"""
    p = tmp_path / "traj.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header if header is not None else _HEADER)
        for r in rows:
            w.writerow(r)
    return str(p)


class TestParseSlamTrajectory:
    def test_basic_unit_conversion(self, tmp_path):
        """米 → 毫米换算；distance_mm 直接取列（不重算）"""
        path = _write_csv(tmp_path, [
            [0.0,   "2026-09-15 10:00:00.000", 0.5, 0.2, 0.1, 1.5],
            [0.02,  "2026-09-15 10:00:00.020", 0.6, 0.3, 0.2, 2.5],
        ])

        result = ps.parse_slam_trajectory(path)

        assert result["total"] == 2 and result["sampled"] == 2
        assert result["t"] == [0.0, 0.02]
        assert result["x"] == [500.0, 600.0]   # ×1000
        assert result["y"] == [200.0, 300.0]
        assert result["z"] == [100.0, 200.0]
        assert result["dist"] == [1.5, 2.5]    # 直接取列

    def test_downsample_keeps_first_and_last(self, tmp_path):
        """超过 max_points 时等间隔抽取且强制保留末点（打印页末尾不丢点）"""
        n = 100
        rows = [[i * 0.02, "t", i / 1000.0, 0.0, 0.0, 1.0] for i in range(n)]
        path = _write_csv(tmp_path, rows)

        result = ps.parse_slam_trajectory(path, max_points=10)

        assert result["total"] == 100
        assert result["sampled"] == 10
        assert result["x"][0] == pytest.approx(0.0)      # 首点保留
        assert result["x"][-1] == pytest.approx(99.0)    # 末点强制保留

    def test_within_max_points_no_sampling(self, tmp_path):
        """数据量小于 max_points → 不降采样"""
        rows = [[0.0, "t", 0.1, 0.0, 0.0, 1.0],
                [0.02, "t", 0.2, 0.0, 0.0, 1.0]]
        path = _write_csv(tmp_path, rows)

        result = ps.parse_slam_trajectory(path, max_points=2000)

        assert result["sampled"] == 2

    def test_missing_distance_column_computes_dist(self, tmp_path):
        """缺 distance_mm 列 → 用 x/y/z（毫米）回退计算欧式距离"""
        header5 = _HEADER[:-1]
        path = _write_csv(tmp_path,
                          [[0.0, "t", 0.5, 0.2, 0.1]], header=header5)

        result = ps.parse_slam_trajectory(path)

        expected = math.sqrt(500.0 ** 2 + 200.0 ** 2 + 100.0 ** 2)
        assert result["dist"][0] == pytest.approx(expected, rel=1e-6)

    def test_missing_required_column_returns_none(self, tmp_path):
        """缺 x_m 等必需列 → None（不可解析的输入安静返回，不抛异常）"""
        header_no_x = ["time_since_start_s", "absolute_time",
                       "y_m", "z_m", "distance_mm"]
        path = _write_csv(tmp_path, [[0.0, "t", 0.0, 0.0, 1.0]],
                          header=header_no_x)

        assert ps.parse_slam_trajectory(path) is None

    def test_bad_rows_are_skipped(self, tmp_path):
        """非数字坏行安全跳过，其余行正常解析"""
        path = _write_csv(tmp_path, [
            [0.0, "t", 0.1, 0.0, 0.0, 1.0],
            ["bad", "t", "x", "y", "z", "d"],        # 坏行
            [0.04, "t", 0.3, 0.0, 0.0, 1.5],
        ])

        result = ps.parse_slam_trajectory(path)

        assert result["total"] == 2
        assert result["x"] == [100.0, 300.0]

    @pytest.mark.parametrize("content", [
        "",                                    # 完全空文件
        ",".join(_HEADER),                     # 只有表头没有数据行
    ], ids=["empty-file", "header-only"])
    def test_no_data_returns_none(self, tmp_path, content):
        f = tmp_path / "traj.csv"
        f.write_text(content, encoding="utf-8")

        assert ps.parse_slam_trajectory(str(f)) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert ps.parse_slam_trajectory(str(tmp_path / "no.csv")) is None


# ============================================================
# 4. parse_imu_calibration_result —— IMU 校准产物契约
# ============================================================

_AFTER_TXT = "\n".join([
    "DemoVision IMU calibration",
    "Stage: after",
    "GyroBias= 0.0012 -0.0008 0.0003",
    "Result: pass",
])


class TestParseImuCalibrationResult:
    def test_after_txt_gyro_bias(self, tmp_path):
        """after 产物含 GyroBias 行 → 三个偏置提取，无 stdout 日志时默认合格"""
        (tmp_path / "imu_calib_after.txt").write_text(_AFTER_TXT, encoding="utf-8")

        result = ps.parse_imu_calibration_result(str(tmp_path))

        assert result["gyro_bias_x"] == pytest.approx(0.0012)
        assert result["gyro_bias_y"] == pytest.approx(-0.0008)
        assert result["gyro_bias_z"] == pytest.approx(0.0003)
        assert result["qualified"] is True

    def test_before_only_fallback(self, tmp_path):
        """只有 before 产物也可解析（after 优先，before 兜底）"""
        (tmp_path / "imu_calib_before.txt").write_text(_AFTER_TXT.replace(
            "Stage: after", "Stage: before"), encoding="utf-8")

        result = ps.parse_imu_calibration_result(str(tmp_path))

        assert result["gyro_bias_x"] == pytest.approx(0.0012)
        assert result["qualified"] is True

    @pytest.mark.parametrize("keyword", [
        "failed", "Failed", "error", "不合格", "cannot connect", "not modified",
    ], ids=["failed", "Failed", "error", "unqualified-cn", "cannot-connect", "not-modified"])
    def test_stdout_fail_keyword_marks_unqualified(self, tmp_path, keyword):
        """stdout 日志含失败语义关键字 → 强制不合格（与 demo 脚本的
        『stdout 不得出现失败关键字』约定互为镜像验证）"""
        (tmp_path / "imu_calib_after.txt").write_text(_AFTER_TXT, encoding="utf-8")
        (tmp_path / "imu_calib_run.log").write_text(
            f"[3/3] verify: 校验校准结果...\n{keyword}\n", encoding="utf-8")

        result = ps.parse_imu_calibration_result(str(tmp_path))

        assert result["qualified"] is False

    def test_vec_format_bias(self, tmp_path):
        """向量格式 "gyro bias = [x, y, z]" 兼容解析（工具旧版本格式）"""
        (tmp_path / "imu_calib_after.txt").write_text(
            "gyro bias = [0.1, 0.2, 0.3]\n", encoding="utf-8")

        result = ps.parse_imu_calibration_result(str(tmp_path))

        assert result["gyro_bias_x"] == pytest.approx(0.1)
        assert result["gyro_bias_y"] == pytest.approx(0.2)
        assert result["gyro_bias_z"] == pytest.approx(0.3)

    def test_no_products_returns_none(self, tmp_path):
        """目录无任何 imu_calib 产物 → None"""
        assert ps.parse_imu_calibration_result(str(tmp_path)) is None

    def test_no_bias_line_marks_unqualified(self, tmp_path):
        """产物存在但解析不出 GyroBias → qualified=False（不能虚报合格）"""
        (tmp_path / "imu_calib_after.txt").write_text("garbage content\n",
                                                      encoding="utf-8")

        result = ps.parse_imu_calibration_result(str(tmp_path))

        assert result["qualified"] is False
