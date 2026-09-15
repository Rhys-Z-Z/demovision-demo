# -*- coding: utf-8 -*-
"""系统级接口（T10）：存储占用统计"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Query

from app.config import DATA_DIR

router = APIRouter(prefix="/api/system", tags=["system"])


def _dir_size(path: str) -> int:
    total = 0
    try:
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total


@router.get("/storage")
async def storage(month: Optional[str] = Query(default=None, description="如 2026_Sep，查单月")):
    """DATA_DIR 总占用 + 按月列表；exports/、.tmp/ 单列不计入日期统计"""
    data_root = DATA_DIR
    months_out = []
    total = 0
    try:
        year_dirs = sorted(
            d for d in os.listdir(data_root)
            if os.path.isdir(os.path.join(data_root, d)) and "_" in d
        )
    except OSError:
        year_dirs = []
    for yd in year_dirs:
        yd_path = os.path.join(data_root, yd)
        try:
            day_dirs = sorted(
                d for d in os.listdir(yd_path)
                if os.path.isdir(os.path.join(yd_path, d))
            )
        except OSError:
            day_dirs = []
        days = []
        month_bytes = 0
        for dd in day_dirs:
            b = _dir_size(os.path.join(yd_path, dd))
            days.append({"day": dd, "bytes": b})
            month_bytes += b
        # date_key = yd/dd，月名 = yd（形如 2026_Sep）
        months_out.append({"month": yd, "bytes": month_bytes, "days": days})
        total += month_bytes

    exports_bytes = _dir_size(os.path.join(data_root, "exports"))
    tmp_bytes = _dir_size(os.path.join(data_root, ".tmp"))

    if month:
        months_out = [m for m in months_out if m["month"] == month]

    return {
        "data_dir": data_root,
        "total_bytes": total,
        "months": months_out,
        "exports_bytes": exports_bytes,
        "tmp_bytes": tmp_bytes,
    }
