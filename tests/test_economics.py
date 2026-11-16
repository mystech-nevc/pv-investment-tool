# -*- coding: utf-8 -*-
"""
tests/test_economics.py
核心算法单元测试与边界测试（对应申报书"测试校验"内容）

运行方式（无需 pytest）：
    cd 光效智算V1.0
    python tests/test_economics.py

若安装 pytest，也可：
    pytest tests/test_economics.py -v
"""

from __future__ import annotations

import copy
import os
import sys

# 保证从项目根目录导入 config 与 services
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config
from services import economics, montecarlo, sensitivity
from services.drawing import build_boq, boq_to_cost, compute_capacity


def base_params():
    return copy.deepcopy(config.DEFAULT_PARAMS)


# ============================================================ 1. 基础财务函数

def test_npv_zero_rate():
    """折现率为 0 时，NPV 应等于现金流之和"""
    cf = [-1000, 400, 400, 400]
    assert abs(economics.npv(0.0, cf) - 200) < 1e-6


def test_irr_known_case():
    """经典案例：-1000, 500, 500, 500 的 IRR 约 23.375%"""
    cf = [-1000.0, 500.0, 500.0, 500.0]
    r = economics.irr(cf)
    assert r is not None and abs(r - 0.23375) < 0.001


def test_irr_no_solution():
    """全负现金流无 IRR 解"""
    assert economics.irr([-1000, -100, -100]) is None


def test_payback_interpolation():
    """回收期插值：-1000, 600, 600 → 第 1 年末累计 -400，第 2 年回本，约 1.67 年"""
    pb = economics.payback_period([-1000.0, 600.0, 600.0], 0.0)
    assert pb is not None and abs(pb - 1.6667) < 0.01


def test_payback_unrecoverable():
    """投资无法回收时返回 None"""
    assert economics.payback_period([-1000.0, 100.0], 0.0) is None


# ============================================================ 2. 逐年序列一致性

def test_series_length_and_decay():
    """发电量序列长度等于寿命年，且逐年递减"""
    p = base_params()
    r = economics.evaluate(p)
    gen = r["series"]["发电量"]
    assert len(gen) == p["tech"]["项目寿命年"]
    assert all(gen[i] >= gen[i + 1] for i in range(len(gen) - 1))
    assert gen[-1] < gen[0]


def test_first_year_generation_formula():
    """首年发电量 = 装机 × 利用小时 × (1−弃光率) × (1−首年衰减)"""
    p = base_params()
    r = economics.evaluate(p)
    expect = (p["tech"]["总装机kW"] * p["tech"]["年等效利用小时"]
              * (1 - p["tech"]["弃光率"]) * (1 - p["tech"]["组件首年衰减"]))
    assert abs(r["series"]["发电量"][0] - expect) < 1.0


def test_cashflow_reconcile_net_profit():
    """净现金流 = 净利润 + 折旧（末年另加残值）"""
    p = base_params()
    r = economics.evaluate(p)
    s = r["series"]
    life = r["life"]
    for i in range(life - 1):
        expect = s["净利润"][i] + s["折旧"][i]
        assert abs(s["经营现金流"][i] - expect) < 0.01
    # 末年含残值
    residual = s["残值"][0]
    assert abs(s["经营现金流"][-1] - (s["净利润"][-1] + s["折旧"][-1] + residual)) < 0.01


def test_vat_credit_exhausted():
    """进项税抵扣池最终会被用完，之后应交增值税应回升"""
    p = base_params()
    r = economics.evaluate(p)
    vat = r["series"]["应交增值税"]
    assert vat[-1] > vat[0]  # 后期无进项抵扣，税负上升


def test_tax_holiday_option():
    """开启三免三减半后，前三年所得税应为 0，第 4~6 年为正常税负的 50%"""
    p = base_params()
    p["finance"]["免所得税年数"] = 3
    p["finance"]["减半征收年数"] = 3
    r = economics.evaluate(p)
    tax = r["series"]["所得税"]
    assert tax[0] == 0 and tax[1] == 0 and tax[2] == 0
    if r["series"]["利润总额"][3] > 0:
        expect_half = r["series"]["利润总额"][3] * p["finance"]["所得税率"] * 0.5
        assert abs(tax[3] - expect_half) < 0.01


# ============================================================ 3. 指标合理性

def test_indicators_reasonable():
    """默认参数下指标应具备工程合理性"""
    r = economics.evaluate(base_params())
    assert 1_000_000 < r["init_invest"] < 3_000_000
    assert -0.5 < r["irr"] < 0.40
    assert r["npv"] > 0                      # 基准参数下项目应可行
    assert 3 < r["static_payback"] < 15      # 回收期在常规区间
    assert r["dynamic_payback"] > r["static_payback"]  # 动态回收期必然更长
    assert 0.10 < r["lcoe"] < 1.0


def test_npv_irr_consistency():
    """按 IRR 折现时 NPV 应约为 0"""
    r = economics.evaluate(base_params())
    assert abs(economics.npv(r["irr"], r["cash_flows"])) < 1.0


def test_unit_invest():
    """单瓦造价 = 初始投资 / (装机 × 1000)"""
    r = economics.evaluate(base_params())
    p = base_params()
    assert abs(r["unit_invest"] - r["init_invest"] / (p["tech"]["总装机kW"] * 1000)) < 0.01


# ============================================================ 4. 边界与极端参数

def test_extreme_low_resource():
    """极低利用小时：项目应亏损，且不报错"""
    p = base_params()
    p["tech"]["年等效利用小时"] = 300
    r = economics.evaluate(p)
    assert r["npv"] < 0
    assert r["static_payback"] is None


def test_zero_subsidy_and_high_interest():
    """零补贴 + 高融资利息：程序不崩溃，指标仍可计算"""
    p = base_params()
    p["finance"]["年度补贴"] = 0
    p["cost"]["年度融资利息"] = 120000
    r = economics.evaluate(p)
    assert r["npv"] is not None
    assert r["init_invest"] > 0


def test_zero_vat():
    """增值税率为 0 时不应出现除零错误"""
    p = base_params()
    p["finance"]["增值税率"] = 0.0
    r = economics.evaluate(p)
    assert r["series"]["应交增值税"][0] == 0
    assert r["npv"] is not None


def test_full_self_consumption():
    """自用比例 100%：上网电量为 0，收益应高于 70% 自用情形"""
    p1 = base_params()
    p1["tech"]["自发自用比例"] = 1.0
    p2 = base_params()
    p2["tech"]["自发自用比例"] = 0.0
    assert economics.evaluate(p1)["npv"] > economics.evaluate(p2)["npv"]


def test_validate_params_detects_error():
    """参数校验应能识别超范围取值"""
    p = base_params()
    p["tech"]["自发自用比例"] = 1.5
    errors = economics.validate_params(p)
    assert any("自发自用比例" in e for e in errors)


def test_validate_default_params_pass():
    """默认参数应通过校验"""
    assert economics.validate_params(base_params()) == []


# ============================================================ 5. 敏感性与盈亏平衡

def test_sensitivity_monotonic():
    """设备购置费上升时 IRR 应单调下降"""
    p = base_params()
    df = sensitivity.single_factor_analysis(p, "设备购置费")
    irr_values = df.dropna(subset=["IRR"])["IRR"].tolist()
    assert all(irr_values[i] >= irr_values[i + 1] for i in range(len(irr_values) - 1))


def test_breakeven_hours():
    """盈亏平衡利用小时应低于当前取值（IRR 目标 8%）"""
    p = base_params()
    be = economics.breakeven_value(p, "年等效利用小时", 0.08)
    assert be is not None and be < p["tech"]["年等效利用小时"]


# ============================================================ 6. 蒙特卡洛

def test_monte_carlo_basic():
    """模拟结果分位数递增，概率位于 [0,1]"""
    p = base_params()
    mc = montecarlo.run_simulation(p, 300)
    assert mc["P10"] <= mc["P50"] <= mc["P90"]
    assert 0.0 <= mc["pass_prob"] <= 1.0
    assert len(mc["irr_samples"]) == 300


def test_monte_carlo_reproducible():
    """同一参数与抽样次数下结果应可复现（随机种子固定）"""
    p = base_params()
    a = montecarlo.run_simulation(p, 200)
    b = montecarlo.run_simulation(p, 200)
    assert abs(a["P50"] - b["P50"]) < 1e-9


def test_risk_level_rule():
    """达标概率极低时应判为高风险"""
    level, text = montecarlo._risk_conclusion(0.2, 0.08, 0.6, 0.03)
    assert level == "high"
    level2, _ = montecarlo._risk_conclusion(0.9, 0.08, 0.6, 0.12)
    assert level2 == "low"


# ============================================================ 7. 工程量与造价

def test_capacity_and_boq():
    """由组件数量推算容量，并完成组价"""
    cap = compute_capacity(900, 550)
    assert abs(cap - 495.0) < 1e-6
    boq = build_boq({"组件数量": 900, "单块功率W": 550, "电缆长度m": 4000, "屋面面积m2": 3000},
                    config.UNIT_PRICE_LIB, cap)
    cost = boq_to_cost(boq)
    assert cost["设备购置费"] > 0
    assert cost["建安施工造价"] > 0
    assert abs(sum(cost.values()) - float(boq["合价"].sum())) < 1e-6


# ============================================================ 运行入口

def run_all():
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_")]
    passed = 0
    failed = []
    print("=" * 70)
    print("光效智算 V1.0 核心算法测试")
    print("=" * 70)
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"[PASS] {name}")
        except AssertionError as exc:
            failed.append((name, f"断言失败：{exc}"))
            print(f"[FAIL] {name}  断言失败")
        except Exception as exc:
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"[ERROR] {name}  {type(exc).__name__}: {exc}")
    print("-" * 70)
    print(f"用例总数 {len(tests)}，通过 {passed}，失败 {len(failed)}")
    if failed:
        print("失败明细：")
        for n, m in failed:
            print(f"  - {n}: {m}")
    return len(failed) == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
