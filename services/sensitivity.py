# -*- coding: utf-8 -*-
"""
services/sensitivity.py
单因素敏感性分析（对应申报书"敏感性分析"需求）

做法：选定一个关键变量，其余参数保持不变，按给定扰动比例逐点重算，
输出各扰动点对应的 IRR / NPV / 静态回收期，用于绘制敏感性曲线与龙卷风图。
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

import pandas as pd

from .economics import evaluate

# 支持分析的因子：显示名 -> (参数分组, 参数键, 单位)
SENS_FACTORS = {
    "年等效利用小时": ("tech", "年等效利用小时", "h"),
    "设备购置费": ("cost", "设备购置费", "元"),
    "建安施工造价": ("cost", "建安施工造价", "元"),
    "自发自用电价": ("finance", "自发自用电价", "元/kWh"),
    "余电上网电价": ("finance", "余电上网电价", "元/kWh"),
    "年度运维费": ("cost", "年度运维费", "元/年"),
}

DEFAULT_PERTURB = [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30]


def single_factor_analysis(params: Dict, factor: str,
                           perturb: Optional[List[float]] = None) -> pd.DataFrame:
    """
    单因素敏感性分析
    params : 基准参数
    factor : SENS_FACTORS 中的键
    perturb: 扰动比例列表（0.1 表示 +10%）
    返回 DataFrame：扰动比例 / 变量取值 / IRR / NPV / 静态回收期
    """
    if factor not in SENS_FACTORS:
        raise ValueError(f"不支持的敏感性因子：{factor}")
    if perturb is None:
        perturb = DEFAULT_PERTURB

    group, key, _unit = SENS_FACTORS[factor]
    base_value = float(params[group][key])

    rows: List[Dict] = []
    for pct in perturb:
        p = copy.deepcopy(params)
        p[group][key] = base_value * (1.0 + pct)
        res = evaluate(p)
        rows.append({
            "扰动比例": pct,
            "变量取值": base_value * (1.0 + pct),
            "IRR": res["irr"],
            "NPV": res["npv"],
            "静态回收期": res["static_payback"],
        })
    df = pd.DataFrame(rows)
    return df


def multi_factor_summary(params: Dict, perturb: float = 0.10) -> pd.DataFrame:
    """
    多因子敏感性对比（龙卷风图数据）：每个因子在 ±perturb 下的 IRR 变化幅度
    返回 DataFrame：因子 / 低值IRR / 高值IRR / IRR变动幅度
    """
    base_irr = evaluate(params)["irr"]
    rows: List[Dict] = []
    for factor in SENS_FACTORS.keys():
        group, key, _unit = SENS_FACTORS[factor]
        base_value = float(params[group][key])

        low_p = copy.deepcopy(params)
        low_p[group][key] = base_value * (1.0 - perturb)
        low_irr = evaluate(low_p)["irr"]

        high_p = copy.deepcopy(params)
        high_p[group][key] = base_value * (1.0 + perturb)
        high_irr = evaluate(high_p)["irr"]

        low_v = low_irr if low_irr is not None else -1.0
        high_v = high_irr if high_irr is not None else -1.0
        rows.append({
            "因子": factor,
            "下降{:.0%}IRR".format(perturb): low_irr,
            "上升{:.0%}IRR".format(perturb): high_irr,
            "IRR变动幅度": abs(high_v - low_v),
            "基准IRR": base_irr,
        })
    df = pd.DataFrame(rows).sort_values("IRR变动幅度", ascending=False).reset_index(drop=True)
    return df


def critical_points(params: Dict, factors: Optional[List[str]] = None,
                    target_irr: float = 0.08) -> pd.DataFrame:
    """
    临界点分析：各因子下降到什么水平时 IRR 跌至目标值
    返回 DataFrame：因子 / 当前取值 / 临界取值 / 可下降幅度
    """
    from .economics import breakeven_value

    if factors is None:
        factors = ["年等效利用小时", "自发自用电价"]
    rows: List[Dict] = []
    for factor in factors:
        group, key, unit = SENS_FACTORS[factor]
        base_value = float(params[group][key])
        critical = breakeven_value(params, factor, target_irr)
        if critical is None:
            rows.append({"因子": factor, "单位": unit, "当前取值": base_value,
                         "临界取值": None, "可下降幅度": None})
        else:
            drop = (critical - base_value) / base_value if base_value else None
            rows.append({"因子": factor, "单位": unit, "当前取值": base_value,
                         "临界取值": critical, "可下降幅度": drop})
    return pd.DataFrame(rows)
