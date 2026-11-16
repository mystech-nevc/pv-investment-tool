# -*- coding: utf-8 -*-
"""
services/economics.py
动态经济评价测算核心（对应申报书图3）
功能：
1. 逐年发电量与收入测算（含组件首年衰减 + 逐年衰减）
2. 增值税（销项－进项结转抵扣）、附加税、直线法折旧
3. 所得税（可选“三免三减半”）、税后净利润、经营净现金流
4. 指标：初始总投资、NPV、IRR、静态/动态投资回收期、LCOE、盈亏平衡点

计算口径（全系统统一）：
- 成本参数均为不含税金额；
- 电价参数为含税销售电价；
- 项目投资现金流为全投资口径：现金流入 = 含税电费收入（含补贴），
  现金流出 = 运维费 + 保险费 + 融资利息 + 附加税 + 应交增值税 + 所得税，
  寿命末计入残值回收。
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional


# ---------------------------------------------------------------- 基础财务函数

def npv(rate: float, cash_flows: List[float]) -> float:
    """净现值：Σ CF_t / (1+rate)^t，t 从 0 开始"""
    return float(sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cash_flows)))


def irr(cash_flows: List[float], low: float = -0.95, high: float = 3.0, iters: int = 300) -> Optional[float]:
    """
    内部收益率：二分法求解 NPV(r)=0
    要求现金流首年为负、末期为正；无解时返回 None
    """
    f_low = npv(low, cash_flows)
    f_high = npv(high, cash_flows)
    if f_low < 0 or f_high > 0:
        return None
    for _ in range(iters):
        mid = (low + high) / 2.0
        f_mid = npv(mid, cash_flows)
        if abs(f_mid) < 1e-9:
            return mid
        if f_mid > 0:
            low, f_low = mid, f_mid
        else:
            high, f_high = mid, f_mid
    return (low + high) / 2.0


def payback_period(cash_flows: List[float], discount_rate: float = 0.0) -> Optional[float]:
    """
    投资回收期（线性插值）
    discount_rate=0 时为静态回收期；>0 时为动态回收期
    返回单位为年（含建设期不计，自投运起算）；无法回收时返回 None
    """
    if len(cash_flows) < 2:
        return None
    # t=0 为初始投资（负值），累计值自初始投资起算
    cum = cash_flows[0]
    cum_prev = cum
    for t in range(1, len(cash_flows)):
        cum_prev = cum
        cum += cash_flows[t] / ((1.0 + discount_rate) ** (t - 1))
        if cum >= 0 and cum_prev < 0:
            # 前一年累计为负、本年转正，年内在第 (t-1)+x 处回本
            gap = cum - cum_prev
            frac = abs(cum_prev) / gap if gap > 0 else 0.0
            return float(t - 1 + frac)
    return None


# ---------------------------------------------------------------- 逐年序列构建

def build_annual_series(params: Dict) -> Dict[str, List[float]]:
    """
    构建逐年财务序列（长度 = 项目寿命年）
    返回字典，各键均为列表：
    发电量、含税电费收入、不含税收入、销项税、应交增值税、
    附加税、折旧、融资利息、运维费、保险费、利润总额、所得税、净利润、净现金流
    """
    cost = params["cost"]
    fin = params["finance"]
    tech = params["tech"]

    life = int(tech["项目寿命年"])
    dep_years = max(1, int(fin["折旧年限"]))
    vat_rate = float(fin["增值税率"])
    add_rate = float(fin["附加税率"])
    it_rate = float(fin["所得税率"])

    # 初始总投资（不含税）
    init_invest = (
        float(cost["设备购置费"])
        + float(cost["建安施工造价"])
        + float(cost["并网配套费"])
        + float(cost["前期咨询费"])
    )

    # 可抵扣进项税额：设备、建安、并网三类投资按增值税率估算
    vat_credit_pool = (
        float(cost["设备购置费"]) + float(cost["建安施工造价"]) + float(cost["并网配套费"])
    ) * vat_rate

    annual_dep = init_invest * (1.0 - float(cost["残值率"])) / dep_years
    residual = init_invest * float(cost["残值率"])

    series: Dict[str, List[float]] = {k: [] for k in [
        "发电量", "含税电费收入", "不含税收入", "销项税", "应交增值税", "附加税",
        "折旧", "融资利息", "运维费", "保险费", "利润总额", "所得税", "净利润",
        "经营现金流",
    ]}

    decay_factor = 1.0
    for i in range(1, life + 1):
        # 组件衰减：首年按首年衰减率，之后按后续年衰减率
        if i == 1:
            decay_factor = 1.0 - float(tech["组件首年衰减"])
        else:
            decay_factor *= 1.0 - float(tech["后续年衰减率"])

        gen_kwh = (
            float(tech["总装机kW"])
            * float(tech["年等效利用小时"])
            * (1.0 - float(tech["弃光率"]))
            * decay_factor
        )
        self_kwh = gen_kwh * float(tech["自发自用比例"])
        grid_kwh = gen_kwh * (1.0 - float(tech["自发自用比例"]))

        # 含税电费收入 + 补贴（补贴不计增值税）
        revenue_inc_vat = (
            self_kwh * float(fin["自发自用电价"])
            + grid_kwh * float(fin["余电上网电价"])
            + float(fin["年度补贴"])
        )
        revenue_ex_vat = revenue_inc_vat / (1.0 + vat_rate) if vat_rate > 0 else revenue_inc_vat
        output_vat = revenue_ex_vat * vat_rate

        # 进项税结转抵扣
        if output_vat > 0 and vat_credit_pool > 0:
            used = min(vat_credit_pool, output_vat)
            vat_credit_pool -= used
            vat_payable = output_vat - used
        else:
            vat_payable = output_vat

        vat_add = vat_payable * add_rate

        dep = annual_dep if i <= dep_years else 0.0
        interest = float(cost["年度融资利息"])
        om = float(cost["年度运维费"])
        ins = float(cost["年度保险费"])

        profit_before_tax = revenue_ex_vat - om - ins - interest - dep - vat_add

        # 所得税：免税期 -> 0，减半期 -> 50%
        free_years = int(fin.get("免所得税年数", 0) or 0)
        half_years = int(fin.get("减半征收年数", 0) or 0)
        if i <= free_years:
            eff_rate = 0.0
        elif i <= free_years + half_years:
            eff_rate = it_rate * 0.5
        else:
            eff_rate = it_rate
        income_tax = max(profit_before_tax, 0.0) * eff_rate

        net_profit = profit_before_tax - income_tax

        # 经营净现金流 = 净利润 + 折旧（利息已在利润中扣除，属全投资口径支出）
        op_cf = net_profit + dep
        if i == life:
            op_cf += residual

        series["发电量"].append(gen_kwh)
        series["含税电费收入"].append(revenue_inc_vat)
        series["不含税收入"].append(revenue_ex_vat)
        series["销项税"].append(output_vat)
        series["应交增值税"].append(vat_payable)
        series["附加税"].append(vat_add)
        series["折旧"].append(dep)
        series["融资利息"].append(interest)
        series["运维费"].append(om)
        series["保险费"].append(ins)
        series["利润总额"].append(profit_before_tax)
        series["所得税"].append(income_tax)
        series["净利润"].append(net_profit)
        series["经营现金流"].append(op_cf)

    series["初始投资"] = [init_invest]
    series["残值"] = [residual]
    return series


# ---------------------------------------------------------------- 指标计算

def calc_lcoe(params: Dict, series: Dict, discount_rate: float) -> Optional[float]:
    """平准化度电成本 LCOE（元/kWh）：(初始投资 + Σ运维保险折现) / Σ发电量折现"""
    init_invest = series["初始投资"][0]
    disc_cost = init_invest
    disc_gen = 0.0
    for t in range(len(series["发电量"])):
        disc_cost += (series["运维费"][t] + series["保险费"][t]) / ((1.0 + discount_rate) ** (t + 1))
        disc_gen += series["发电量"][t] / ((1.0 + discount_rate) ** (t + 1))
    if disc_gen <= 0:
        return None
    return disc_cost / disc_gen


def evaluate(params: Dict) -> Dict:
    """
    主入口：完成一次完整测算
    返回结果字典，供前端展示、报告导出、蒙特卡洛复用
    """
    series = build_annual_series(params)
    init_invest = series["初始投资"][0]
    discount_rate = float(params["finance"]["折现率"])

    cash_flows = [-init_invest] + series["经营现金流"]
    npv_value = npv(discount_rate, cash_flows)
    irr_value = irr(cash_flows)
    static_pb = payback_period(cash_flows, 0.0)
    dynamic_pb = payback_period(cash_flows, discount_rate)

    total_gen = float(sum(series["发电量"]))
    total_revenue = float(sum(series["含税电费收入"]))
    total_net_profit = float(sum(series["净利润"]))
    lcoe_value = calc_lcoe(params, series, discount_rate)

    cumulative = []
    acc = -init_invest
    cumulative.append(acc)
    for cf in series["经营现金流"]:
        acc += cf
        cumulative.append(acc)

    return {
        "params": copy.deepcopy(params),
        "series": series,
        "cash_flows": cash_flows,
        "cumulative": cumulative,
        "init_invest": init_invest,
        "discount_rate": discount_rate,
        "npv": npv_value,
        "irr": irr_value,
        "static_payback": static_pb,
        "dynamic_payback": dynamic_pb,
        "total_gen": total_gen,
        "total_revenue": total_revenue,
        "total_net_profit": total_net_profit,
        "lcoe": lcoe_value,
        "life": int(params["tech"]["项目寿命年"]),
        "unit_invest": init_invest / (float(params["tech"]["总装机kW"]) * 1000.0),
    }


# ---------------------------------------------------------------- 盈亏平衡点

def breakeven_value(params: Dict, factor: str, target_irr: float,
                    lo: Optional[float] = None, hi: Optional[float] = None,
                    iters: int = 60) -> Optional[float]:
    """
    盈亏平衡点求解：在目标 IRR 下，某单一关键变量的临界值
    factor 可选：'年等效利用小时'、'自发自用电价'、'总装机kW'
    采用二分法，返回临界值；无解返回 None
    """
    # 各因子的默认搜索区间（工程量纲）
    default_bounds = {
        "年等效利用小时": (100.0, 2600.0),
        "自发自用电价": (0.05, 2.0),
        "总装机kW": (10.0, 10000.0),
    }
    if factor not in default_bounds:
        return None
    if lo is None:
        lo = default_bounds[factor][0]
    if hi is None:
        hi = default_bounds[factor][1]

    def irr_at(value: float) -> Optional[float]:
        p = copy.deepcopy(params)
        if factor == "年等效利用小时":
            p["tech"]["年等效利用小时"] = value
        elif factor == "自发自用电价":
            p["finance"]["自发自用电价"] = value
        elif factor == "总装机kW":
            p["tech"]["总装机kW"] = value
        else:
            return None
        return evaluate(p)["irr"]

    irr_lo = irr_at(lo)
    irr_hi = irr_at(hi)
    if irr_hi is None or irr_hi < target_irr:
        return None
    # 下限无正收益时（IRR 无解）视为远低于目标，不影响寻根区间
    if irr_lo is None:
        irr_lo = -0.99
    if irr_lo >= target_irr:
        return lo
    if irr_lo < target_irr < irr_hi:
        low, high = lo, hi
        for _ in range(iters):
            mid = (low + high) / 2.0
            v = irr_at(mid)
            if v is None:
                low = mid
                continue
            if v < target_irr:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0
    return None


def validate_params(params: Dict) -> List[str]:
    """参数合法性校验，返回错误提示列表（空列表表示通过）"""
    import config
    errors: List[str] = []
    for group in ("cost", "finance", "tech", "risk"):
        meta = config.PARAM_META.get(group, {})
        for key, (label, unit, vmin, vmax, step, _help) in meta.items():
            value = params.get(group, {}).get(key, None)
            if value is None:
                errors.append(f"参数缺失：{label}")
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                errors.append(f"{label} 必须为数字")
                continue
            if v < vmin or v > vmax:
                errors.append(f"{label} 超出允许范围 [{vmin}, {vmax}]，当前 {v}")
    if params["tech"]["总装机kW"] <= 0:
        errors.append("总装机容量必须大于 0")
    if params["cost"]["设备购置费"] <= 0:
        errors.append("设备购置费必须大于 0")
    return errors
