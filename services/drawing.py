# -*- coding: utf-8 -*-
"""
services/drawing.py
图纸解析与工程量提取模块（申报书图4）

V1.0 实现范围：
1. 工程量清单（BOQ）录入与自动组价：把组件数量、单块功率、电缆长度、
   屋面面积等工程量，按综合单价库自动汇总为"设备购置费 / 建安施工造价 /
   并网配套费 / 前期咨询费"，直接回填到造价参数；
2. DXF 图纸辅助解析：若本地安装 ezdxf，则按图层统计图元数量与线长，
   为工程量提供"机器初算"参考值；未安装时给出明确的降级提示，不静默失败；
3. 图纸解析坚持"机器初算 + 人工校核"原则：解析结果一律允许人工修改后再使用，
   不做全自动替代。

未在 V1.0 实现（列入 V1.1 迭代）：DWG 二进制直读、IFC/BIM 构件级建模、
屋面障碍物自动识别与组件排布优化，这些能力需依赖商业内核或大量样本训练。
"""

from __future__ import annotations

import io
import math
from typing import Dict, List, Optional, Tuple

import pandas as pd

import config


# ---------------------------------------------------------------- 工程量清单

DEFAULT_QUANTITIES = {
    "组件数量": 900,          # 块
    "单块功率W": 550,         # W/块
    "电缆长度m": 4200,        # m
    "屋面面积m2": 3200,       # m2（用于校核装机密度是否合理）
    "支架容量占比": 1.0,      # 支架按装机容量计价
    "逆变器容量占比": 1.0,    # 逆变器按交流侧容量计价
}


def compute_capacity(quantity: float, unit_power_w: float) -> float:
    """由组件数量与单块功率推算装机容量（kW）"""
    return float(quantity) * float(unit_power_w) / config.W_PER_KW


def check_density(capacity_kw: float, roof_area_m2: float) -> Optional[str]:
    """
    装机密度校核：分布式屋顶光伏一般 60~120 W/m2，
    超出范围说明工程量或屋面面积可能录入有误，返回提示文字
    """
    if roof_area_m2 <= 0 or capacity_kw <= 0:
        return None
    density = capacity_kw * 1000.0 / roof_area_m2
    if density < 40:
        return f"装机密度 {density:.0f} W/m² 偏低，请核对屋面可利用面积或组件数量"
    if density > 160:
        return f"装机密度 {density:.0f} W/m² 偏高，请核对组件排布与遮挡间距"
    return None


def build_boq(quantities: Dict, unit_prices: Dict, capacity_kw: float) -> pd.DataFrame:
    """
    按工程量与综合单价生成造价清单（BOQ）
    quantities : 工程量字典
    返回 DataFrame：项目 / 单位 / 数量 / 单价 / 合价 / 归集科目
    """
    rows: List[Dict] = []

    def add(name: str, unit: str, qty: float, price: float, subject: str):
        rows.append({
            "项目": name, "单位": unit, "数量": qty, "单价": price,
            "合价": qty * price, "归集科目": subject,
        })

    pv_price = float(unit_prices["光伏组件"]["单价"])
    inv_price = float(unit_prices["逆变器"]["单价"])
    brk_price = float(unit_prices["支架系统"]["单价"])
    cab_price = float(unit_prices["电缆及桥架"]["单价"])
    grid_price = float(unit_prices["并网及监控"]["单价"])
    ins_price = float(unit_prices["安装施工"]["单价"])
    des_price = float(unit_prices["设计咨询"]["单价"])

    cap_w = capacity_kw * config.W_PER_KW

    add("光伏组件", "W", cap_w, pv_price, "设备购置费")
    add("逆变器", "W", cap_w * float(quantities.get("逆变器容量占比", 1.0)), inv_price, "设备购置费")
    add("支架系统", "kW", capacity_kw * float(quantities.get("支架容量占比", 1.0)), brk_price, "设备购置费")
    add("电缆及桥架", "m", float(quantities.get("电缆长度m", 0)), cab_price, "设备购置费")
    add("安装施工", "kW", capacity_kw, ins_price, "建安施工造价")
    add("并网及监控", "项", 1, grid_price, "并网配套费")
    add("设计咨询", "项", 1, des_price, "前期咨询费")

    return pd.DataFrame(rows)


def boq_to_cost(boq: pd.DataFrame) -> Dict[str, float]:
    """造价清单按科目汇总，输出可直接回填参数库的四个造价字段"""
    subject_map = {
        "设备购置费": "设备购置费",
        "建安施工造价": "建安施工造价",
        "并网配套费": "并网配套费",
        "前期咨询费": "前期咨询费",
    }
    total = boq.groupby("归集科目")["合价"].sum()
    out = {target: float(total.get(src, 0.0)) for src, target in subject_map.items()}
    return out


def unit_price_table(unit_prices: Dict) -> pd.DataFrame:
    """综合单价库转为表格，便于前端展示和修改"""
    return pd.DataFrame([
        {"项目": name, "单位": info["单位"], "综合单价": info["单价"], "说明": info["说明"]}
        for name, info in unit_prices.items()
    ])


# ---------------------------------------------------------------- DXF 辅助解析

def parse_dxf(file_buffer) -> Tuple[Optional[Dict], str]:
    """
    按图层统计 DXF 图元数量与线段总长，输出"机器初算"参考值
    file_buffer : 上传的文件对象（bytes）或文件路径
    返回 (解析结果 dict 或 None, 提示信息)
    解析结果为参考值，必须经人工校核后方可参与造价计算。
    """
    try:
        import ezdxf  # 可选依赖，未安装时走降级分支
    except ImportError:
        return None, ("未检测到 ezdxf 模块，图纸自动解析不可用。可以手动录入工程量继续测算；"
                      "若需启用解析，请执行：pip install ezdxf")

    try:
        if isinstance(file_buffer, (bytes, bytearray)):
            data = io.BytesIO(file_buffer)
            doc = ezdxf.read(data)
        else:
            doc = ezdxf.readfile(str(file_buffer))
    except Exception as exc:  # DXF 版本或编码异常
        return None, f"图纸解析失败：{exc}。建议在 CAD 中另存为 DXF R12/R2010 后重试。"

    msp = doc.modelspace()
    layer_count: Dict[str, int] = {}
    layer_length: Dict[str, float] = {}
    circles = 0
    closed_area = 0.0

    for entity in msp:
        layer = entity.dxf.layer
        layer_count[layer] = layer_count.get(layer, 0) + 1
        etype = entity.dxftype()

        if etype == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            seg = math.dist((start.x, start.y, start.z), (end.x, end.y, end.z))
            layer_length[layer] = layer_length.get(layer, 0.0) + seg
        elif etype in ("LWPOLYLINE", "POLYLINE"):
            try:
                pts = [(p[0], p[1]) for p in entity.get_points()] if etype == "LWPOLYLINE" else \
                      [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                seg = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                layer_length[layer] = layer_length.get(layer, 0.0) + seg
                if etype == "LWPOLYLINE" and getattr(entity, "closed", False):
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    closed_area += 0.5 * abs(sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
                                                 for i in range(len(pts) - 1)))
            except Exception:
                continue
        elif etype == "CIRCLE":
            circles += 1

    result = {
        "图层数量": len(layer_count),
        "图元总数": sum(layer_count.values()),
        "圆/圆形图元数": circles,
        "图层统计": layer_count,
        "图层线长": {k: round(v, 1) for k, v in layer_length.items()},
        "闭合多段线面积合计m2": round(closed_area, 1),
        "总线长m": round(sum(layer_length.values()), 1),
    }
    return result, "解析完成。结果仅为机器初算参考值，请结合图纸人工校核后再录入工程量。"


def apply_dxf_hint(quantities: Dict, dxf_result: Dict) -> Dict:
    """
    把 DXF 解析的总线长作为电缆长度初值（仅当用户未手工填写时覆盖）
    """
    q = dict(quantities)
    if dxf_result.get("总线长m"):
        q["电缆长度m"] = float(dxf_result["总线长m"])
    if dxf_result.get("闭合多段线面积合计m2"):
        q["屋面面积m2"] = float(dxf_result["闭合多段线面积合计m2"])
    return q
