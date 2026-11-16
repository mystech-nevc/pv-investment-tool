# -*- coding: utf-8 -*-
"""
services/montecarlo.py
蒙特卡洛多因子概率风险模拟（对应申报书"抽样≥1000次"要求）

模拟思路：
1. 对 4 个核心不确定性因子按正态分布抽样（可设变异系数）：
   年等效利用小时、初始投资（设备+建安+并网）、自发自用电价、年度运维费；
2. 每个样本重算 IRR 与 NPV，形成结果样本集；
3. 输出 P10/P50/P90 分位数、均值、标准差、达标概率，并给出风险预警结论。

随机数种子固定，保证同一参数下结果可复现（软著演示与案例校验需要）。
"""

from __future__ import annotations

import copy
from typing import Dict, List

import numpy as np

from .economics import evaluate


def _sample_params(base: Dict, rng: np.random.Generator) -> Dict:
    """按基础参数与波动率生成一个随机样本（带边界截断，避免出现非物理值）"""
    p = copy.deepcopy(base)
    risk = base["risk"]

    hours_cv = float(risk.get("利用小时波动率", 0.08))
    cost_cv = float(risk.get("造价波动率", 0.08))
    price_cv = float(risk.get("电价波动率", 0.07))
    om_cv = float(risk.get("运维波动率", 0.10))

    # 年等效利用小时
    hours = float(base["tech"]["年等效利用小时"])
    p["tech"]["年等效利用小时"] = float(np.clip(
        rng.normal(hours, hours * hours_cv), hours * 0.5, hours * 1.5))

    # 造价：对设备、建安、并网三项同比例扰动（同一造价指数冲击，保持结构一致）
    factor = float(np.clip(rng.normal(1.0, cost_cv), 0.7, 1.3))
    p["cost"]["设备购置费"] = float(base["cost"]["设备购置费"]) * factor
    p["cost"]["建安施工造价"] = float(base["cost"]["建安施工造价"]) * factor
    p["cost"]["并网配套费"] = float(base["cost"]["并网配套费"]) * factor

    # 电价：自用与上网同向波动
    p_factor = float(np.clip(rng.normal(1.0, price_cv), 0.7, 1.3))
    p["finance"]["自发自用电价"] = float(base["finance"]["自发自用电价"]) * p_factor
    p["finance"]["余电上网电价"] = float(base["finance"]["余电上网电价"]) * p_factor

    # 运维费
    om = float(base["cost"]["年度运维费"])
    p["cost"]["年度运维费"] = float(np.clip(
        rng.normal(om, om * om_cv), om * 0.5, om * 2.0))

    return p


def run_simulation(params: Dict, sample_n: int = None, seed: int = 20261116) -> Dict:
    """
    执行蒙特卡洛模拟
    params   : 基准参数
    sample_n : 抽样次数，缺省取参数中的"蒙特卡洛抽样次数"
    seed     : 随机种子，保证结果可复现
    返回字典：IRR/NPV 样本数组、分位数、达标概率、预警结论
    """
    n = int(sample_n or params["risk"]["蒙特卡洛抽样次数"])
    rng = np.random.default_rng(seed)

    irr_list: List[float] = []
    npv_list: List[float] = []
    lcoe_list: List[float] = []

    for _ in range(n):
        sample = _sample_params(params, rng)
        res = evaluate(sample)
        irr_list.append(res["irr"] if res["irr"] is not None else -1.0)
        npv_list.append(res["npv"])
        lcoe_list.append(res["lcoe"] if res["lcoe"] is not None else 0.0)

    irr_arr = np.array(irr_list, dtype=float)
    npv_arr = np.array(npv_list, dtype=float)
    lcoe_arr = np.array(lcoe_list, dtype=float)

    p10, p50, p90 = np.percentile(irr_arr, [10, 50, 90])
    npv_p10, npv_p50, npv_p90 = np.percentile(npv_arr, [10, 50, 90])

    irr_threshold = float(params["risk"]["IRR预警阈值"])
    pass_prob = float(np.mean(irr_arr >= irr_threshold))
    npv_positive_prob = float(np.mean(npv_arr >= 0.0))
    warn_prob_threshold = float(params["risk"].get("达标概率阈值", 0.6))

    risk_level, risk_text = _risk_conclusion(pass_prob, irr_threshold, warn_prob_threshold, p10)

    return {
        "sample_n": n,
        "irr_samples": irr_arr,
        "npv_samples": npv_arr,
        "lcoe_samples": lcoe_arr,
        "P10": float(p10),
        "P50": float(p50),
        "P90": float(p90),
        "irr_mean": float(np.mean(irr_arr)),
        "irr_std": float(np.std(irr_arr)),
        "npv_P10": float(npv_p10),
        "npv_P50": float(npv_p50),
        "npv_P90": float(npv_p90),
        "lcoe_mean": float(np.mean(lcoe_arr)),
        "pass_prob": pass_prob,
        "npv_positive_prob": npv_positive_prob,
        "irr_threshold": irr_threshold,
        "warn_prob_threshold": warn_prob_threshold,
        "risk_level": risk_level,
        "risk_text": risk_text,
    }


def _risk_conclusion(pass_prob: float, irr_threshold: float,
                     warn_threshold: float, p10: float):
    """
    风险定级规则（可在参数页调整阈值）：
    达标概率 < 预警阈值                -> 红色（高风险）
    预警阈值 ≤ 达标概率 < 预警阈值+0.2 -> 橙色（中等风险）
    其余                               -> 绿色（风险可控）
    """
    if pass_prob < warn_threshold:
        return (
            "high",
            f"高风险预警：IRR 达到 {irr_threshold:.2%} 的概率仅 {pass_prob:.1%}，"
            f"低于设定阈值 {warn_threshold:.0%}；悲观情形（P10）IRR 为 {p10:.2%}，"
            f"建议重新核算造价、电价与自用比例，或暂缓投资决策。",
        )
    if pass_prob < warn_threshold + 0.2:
        return (
            "medium",
            f"中等风险：IRR 达到 {irr_threshold:.2%} 的概率为 {pass_prob:.1%}，"
            f"处于预警阈值附近；建议锁定电价与运维合同，控制造价上浮。",
        )
    return (
        "low",
        f"风险可控：IRR 达到 {irr_threshold:.2%} 的概率为 {pass_prob:.1%}，"
        f"高于设定阈值 {warn_threshold:.0%}；项目经济性具备一定安全边际。",
    )


def scenario_analysis(params: Dict) -> Dict:
    """
    三情景分析（悲观/中性/乐观），基于固定乘数而非随机抽样，便于答辩展示
    """
    scenarios = {
        "悲观情景": {"hours": 0.90, "cost": 1.10, "price": 0.95, "om": 1.15},
        "中性情景": {"hours": 1.00, "cost": 1.00, "price": 1.00, "om": 1.00},
        "乐观情景": {"hours": 1.08, "cost": 0.95, "price": 1.03, "om": 1.05},
    }
    out = {}
    for name, m in scenarios.items():
        p = copy.deepcopy(params)
        p["tech"]["年等效利用小时"] = params["tech"]["年等效利用小时"] * m["hours"]
        for k in ("设备购置费", "建安施工造价", "并网配套费"):
            p["cost"][k] = params["cost"][k] * m["cost"]
        p["finance"]["自发自用电价"] = params["finance"]["自发自用电价"] * m["price"]
        p["finance"]["余电上网电价"] = params["finance"]["余电上网电价"] * m["price"]
        p["cost"]["年度运维费"] = params["cost"]["年度运维费"] * m["om"]
        out[name] = evaluate(p)
    return out
