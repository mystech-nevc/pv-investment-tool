# -*- coding: utf-8 -*-
"""
main.py
光效智算——分布式光伏项目投资收益智能测算与风险预警系统 V1.0
Streamlit Web 主程序（软件入口）

启动方式：
    streamlit run main.py

页面结构（左侧导航）：
1. 项目概览         —— 软件功能入口、当前项目关键指标速览
2. 项目参数录入     —— 成本 / 财务 / 技术 / 风险四组参数
3. 工程量与造价     —— 工程量清单自动组价，回填造价参数
4. 图纸解析（DXF）  —— 机器初算 + 人工校核（可选，需 ezdxf）
5. 动态收益测算     —— NPV / IRR / 回收期 / LCOE / 逐年现金流
6. 敏感性分析       —— 单因素曲线 + 龙卷风图 + 临界点
7. 风险预警         —— 蒙特卡洛概率模拟 + 三情景对比
8. 多方案对比       —— 保存方案横向对比
9. 报告导出         —— PDF 报告 + CSV 明细
10. 参数模板        —— JSON 导入导出
11. 使用说明        —— 计算口径与免责声明
"""

from __future__ import annotations

import copy
import io

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import config
from services import drawing, economics, montecarlo, report, sensitivity, storage

# ================================================================ 页面基础配置

st.set_page_config(
    page_title=f"{config.APP_SHORT}｜分布式光伏投资测算与风险预警",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

INT_KEYS = {"折旧年限", "项目寿命年", "蒙特卡洛抽样次数", "免所得税年数", "减半征收年数"}


def init_state():
    """初始化会话状态"""
    if "params" not in st.session_state:
        st.session_state.params = copy.deepcopy(config.DEFAULT_PARAMS)
    if "unit_prices" not in st.session_state:
        st.session_state.unit_prices = copy.deepcopy(config.UNIT_PRICE_LIB)
    if "quantities" not in st.session_state:
        st.session_state.quantities = copy.deepcopy(drawing.DEFAULT_QUANTITIES)
    if "result" not in st.session_state:
        st.session_state.result = None
    if "mc" not in st.session_state:
        st.session_state.mc = None
    if "dxf" not in st.session_state:
        st.session_state.dxf = None
    if "page" not in st.session_state:
        st.session_state.page = "项目概览"


init_state()
P = st.session_state.params


# ================================================================ 通用组件

def fmt_money(v):
    return "—" if v is None else f"{v:,.2f}"


def fmt_pct(v):
    return "—" if v is None else f"{v:.2%}"


def fmt_year(v):
    return "项目不具备回收能力" if v is None else f"{v:.2f} 年"


def reset_default_params():
    """恢复默认参数：清除所有参数控件缓存后重跑"""
    for group in ("cost", "finance", "tech", "risk"):
        for key in config.PARAM_META[group].keys():
            st.session_state.pop(f"in_{group}_{key}", None)
    st.session_state.params = copy.deepcopy(config.DEFAULT_PARAMS)
    st.session_state.result = None
    st.session_state.mc = None


def ensure_result() -> bool:
    """确保已有测算结果，没有则自动算一次"""
    if st.session_state.result is None:
        try:
            st.session_state.result = economics.evaluate(st.session_state.params)
        except Exception as exc:
            st.error(f"测算失败：{exc}")
            return False
    return True


def metric_row(result):
    """核心指标四联展示（多页面复用）"""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("初始总投资（元）", f"{result['init_invest']:,.0f}",
              help=f"单瓦造价 {result['unit_invest']:.2f} 元/W")
    c2.metric("净现值 NPV（元）", f"{result['npv']:,.0f}",
              delta=f"折现率 {result['discount_rate']:.2%}")
    c3.metric("内部收益率 IRR", fmt_pct(result["irr"]))
    c4.metric("静态投资回收期",
              fmt_year(result["static_payback"]) if result["static_payback"] else "不可回收")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("动态投资回收期",
              fmt_year(result["dynamic_payback"]) if result["dynamic_payback"] else "不可回收")
    c6.metric("平准化度电成本 LCOE", f"{result['lcoe']:.4f} 元/kWh" if result["lcoe"] else "—")
    c7.metric("全周期发电量（万kWh）", f"{result['total_gen'] / 1e4:,.1f}")
    c8.metric("全周期净收益（万元）", f"{result['total_net_profit'] / 1e4:,.1f}")


# ================================================================ 页面 1：项目概览

def page_overview():
    st.title("☀️ 光效智算 —— 分布式光伏项目投资收益智能测算与风险预警系统")
    st.caption(f"{config.APP_VERSION}｜{config.APP_AUTHOR}｜软件著作权申报版本")

    st.markdown("""
    **软件定位**：面向中小型 EPC 企业、校园与村镇光伏投资方、造价从业者的轻量化投资决策工具，
    实现 *工程量组价 → 造价与财税测算 → 动态经济评价 → 多因子概率风险预警 → 报告导出* 的一体化闭环。

    本版本全部基于开源技术栈（Python + Streamlit + Plotly + reportlab），本地即可运行，不依赖商业软件授权。
    """)

    st.divider()
    st.subheader("当前项目速览")
    meta = P.get("meta", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("项目名称", meta.get("项目名称", "未命名")[:14])
    c2.metric("建设地点", meta.get("建设地点", "—"))
    c3.metric("装机容量", f"{P['tech']['总装机kW']:.1f} kW")
    c4.metric("项目寿命", f"{P['tech']['项目寿命年']} 年")

    if ensure_result():
        st.subheader("当前参数下的核心指标")
        metric_row(st.session_state.result)
        if st.session_state.result["irr"] is not None and \
                st.session_state.result["irr"] < P["risk"]["IRR预警阈值"]:
            st.warning(f"⚠️ 当前 IRR {st.session_state.result['irr']:.2%} 低于预警阈值 "
                       f"{P['risk']['IRR预警阈值']:.2%}，建议前往「风险预警」页做概率评估。")

    st.divider()
    c_left, c_right = st.columns([1, 1])
    with c_left:
        st.subheader("功能导航")
        st.markdown("""
        | 页面 | 作用 |
        |---|---|
        | 项目参数录入 | 录入成本、财务、技术、风险四组参数，支持恢复默认 |
        | 工程量与造价 | 由组件数量、电缆长度等工程量自动组价，一键回填造价 |
        | 图纸解析（DXF） | 上传 DXF 做机器初算，结果需人工校核后使用 |
        | 动态收益测算 | 输出 NPV、IRR、回收期、LCOE 与逐年现金流 |
        | 敏感性分析 | 单因素曲线、龙卷风图、临界点分析 |
        | 风险预警 | 蒙特卡洛 1000+ 次抽样，输出 P10/P50/P90 与达标概率 |
        | 多方案对比 | 保存方案并横向比较，支持长期积累 |
        | 报告导出 | 一键导出 PDF 测算报告与 CSV 现金流量表 |
        | 参数模板 | 参数 JSON 导出与导入，便于团队复用 |
        """)
    with c_right:
        st.subheader("使用流程")
        st.plotly_chart(build_flow_chart(), use_container_width=True)

    st.divider()
    st.info("首次使用建议：① 在「项目参数录入」按实际报价填写成本 → ②「动态收益测算」看 IRR/NPV "
            "→ ③「风险预警」看达标概率 → ④「报告导出」生成 PDF。")


def build_flow_chart():
    """业务流程示意图（Plotly 绘制，不依赖外部图片）"""
    steps = ["工程量/参数录入", "造价与财税测算", "动态经济评价", "多因子风险预警", "报告与决策"]
    xs = list(range(len(steps)))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=[0.5] * len(steps), mode="markers+text",
        marker=dict(size=34, color="#2e8b57", line=dict(width=1, color="#1a5f3f")),
        text=[str(i + 1) for i in range(len(steps))],
        textfont=dict(color="white", size=15),
        hovertext=steps, hoverinfo="text", showlegend=False,
    ))
    for i in range(len(steps) - 1):
        fig.add_annotation(x=(xs[i] + xs[i + 1]) / 2, y=0.22, text=steps[i],
                           showarrow=False, font=dict(size=11), yanchor="bottom")
        fig.add_shape(type="line", x0=xs[i] + 0.35, x1=xs[i + 1] - 0.35, y0=0.5, y1=0.5,
                      line=dict(color="#9ec9ae", width=2))
    fig.add_annotation(x=xs[-1], y=0.22, text=steps[-1], showarrow=False, font=dict(size=11))
    fig.update_xaxes(visible=False, range=[-0.6, len(steps) - 0.4])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10),
                      plot_bgcolor="rgba(0,0,0,0)")
    return fig


# ================================================================ 页面 2：参数录入

def page_params():
    st.title("① 项目参数录入")
    st.caption("全部参数均可在页面直接修改，修改后即时写入会话参数库；带 ? 的标签可查看取值说明。")

    with st.expander("项目基本信息", expanded=True):
        c1, c2, c3 = st.columns(3)
        P["meta"]["项目名称"] = c1.text_input("项目名称", value=P["meta"].get("项目名称", ""),
                                           key="meta_name")
        P["meta"]["建设地点"] = c2.text_input("建设地点", value=P["meta"].get("建设地点", ""),
                                           key="meta_site")
        P["meta"]["编制人"] = c3.text_input("编制人", value=P["meta"].get("编制人", ""),
                                         key="meta_author")
        P["meta"]["方案说明"] = st.text_input("方案说明", value=P["meta"].get("方案说明", ""),
                                            key="meta_note")

    tabs = st.tabs(["成本参数", "财务参数", "技术参数", "风险参数"])

    with tabs[0]:
        _render_group("cost", 2)
    with tabs[1]:
        _render_group("finance", 3)
    with tabs[2]:
        _render_group("tech", 3)
    with tabs[3]:
        _render_group("risk", 2)

    st.divider()
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("🔄 恢复默认参数", use_container_width=True):
        reset_default_params()
        st.success("已恢复默认参数")
        st.rerun()
    if c2.button("✅ 保存并重新测算", type="primary", use_container_width=True):
        errors = economics.validate_params(st.session_state.params)
        if errors:
            for e in errors:
                st.error(e)
        else:
            st.session_state.result = economics.evaluate(st.session_state.params)
            st.session_state.mc = None
            st.success("参数校验通过，已重新测算，可前往「动态收益测算」或「风险预警」查看结果")

    with c3:
        errors = economics.validate_params(st.session_state.params)
        if errors:
            st.warning(f"存在 {len(errors)} 处参数异常：" + "；".join(errors[:3]))
        else:
            st.success("当前参数校验通过（全部参数位于允许取值范围内）")


def _render_group(group: str, cols: int):
    """按 PARAM_META 渲染一组参数控件"""
    st.markdown(f"**{config.GROUP_TITLE[group]}**")
    items = list(config.PARAM_META[group].items())
    for i in range(0, len(items), cols):
        columns = st.columns(cols)
        for col, (key, (label, unit, vmin, vmax, step, help_text)) in zip(columns, items[i:i + cols]):
            widget_key = f"in_{group}_{key}"
            current = P[group].get(key, 0)
            if key in INT_KEYS:
                value = col.number_input(
                    f"{label}" + (f"（{unit}）" if unit else ""),
                    min_value=int(vmin), max_value=int(vmax),
                    value=int(float(current)), step=int(step) if step >= 1 else 1,
                    help=help_text, key=widget_key,
                )
                P[group][key] = int(value)
            else:
                value = col.number_input(
                    f"{label}" + (f"（{unit}）" if unit else ""),
                    min_value=float(vmin), max_value=float(vmax),
                    value=float(current), step=float(step),
                    help=help_text, key=widget_key, format="%.4f" if step < 0.01 else "%.2f",
                )
                P[group][key] = float(value)


# ================================================================ 页面 3：工程量与造价

def page_boq():
    st.title("② 工程量清单与造价组价")
    st.caption("录入工程量 → 按综合单价自动组价 → 一键回填到成本参数，避免手工加总出错。")

    c1, c2, c3 = st.columns(3)
    q = st.session_state.quantities
    q["组件数量"] = c1.number_input("组件数量（块）", min_value=0.0, value=float(q["组件数量"]),
                                  step=10.0, key="q_count")
    q["单块功率W"] = c2.number_input("单块组件功率（W）", min_value=0.0, value=float(q["单块功率W"]),
                                   step=5.0, key="q_power")
    q["电缆长度m"] = c3.number_input("电缆及桥架长度（m）", min_value=0.0, value=float(q["电缆长度m"]),
                                   step=100.0, key="q_cable")

    c4, c5, c6 = st.columns(3)
    q["屋面面积m2"] = c4.number_input("屋面可利用面积（m²）", min_value=0.0, value=float(q["屋面面积m2"]),
                                   step=50.0, key="q_roof")
    q["支架容量占比"] = c5.slider("支架按容量计价系数", 0.5, 1.5, float(q["支架容量占比"]), 0.05,
                                help="部分项目支架复用既有结构时可下调")
    q["逆变器容量占比"] = c6.slider("逆变器按容量计价系数", 0.5, 1.5, float(q["逆变器容量占比"]), 0.05,
                                 help="容配比 1.1~1.3 时取 0.8~0.9")

    capacity = drawing.compute_capacity(q["组件数量"], q["单块功率W"])
    st.metric("推算装机容量", f"{capacity:.2f} kW")
    hint = drawing.check_density(capacity, q["屋面面积m2"])
    if hint:
        st.warning(hint)

    st.divider()
    st.subheader("综合单价库（可修改，单位：元）")
    up = st.session_state.unit_prices
    rows = []
    cols = st.columns(4)
    for i, (name, info) in enumerate(up.items()):
        with cols[i % 4]:
            new_price = st.number_input(f"{name}（{info['单位']}）", min_value=0.0,
                                        value=float(info["单价"]), step=1.0,
                                        help=info["说明"], key=f"up_{name}")
            up[name]["单价"] = float(new_price)
            rows.append({"项目": name, "单位": info["单位"], "综合单价": new_price, "说明": info["说明"]})

    st.divider()
    boq = drawing.build_boq(q, st.session_state.unit_prices, capacity)
    st.subheader("造价清单（BOQ）")
    st.dataframe(
        boq.style.format({"数量": "{:,.1f}", "单价": "{:,.2f}", "合价": "{:,.2f}"}),
        use_container_width=True, hide_index=True,
    )
    total = float(boq["合价"].sum())
    cost_map = drawing.boq_to_cost(boq)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("设备购置费", f"{cost_map['设备购置费']:,.0f}")
    c2.metric("建安施工造价", f"{cost_map['建安施工造价']:,.0f}")
    c3.metric("并网配套费", f"{cost_map['并网配套费']:,.0f}")
    c4.metric("前期咨询费", f"{cost_map['前期咨询费']:,.0f}")
    c5.metric("合计造价", f"{total:,.0f}",
              help=f"单瓦造价 {total / (capacity * 1000):.2f} 元/W" if capacity > 0 else "")

    fig = px.bar(boq, x="项目", y="合价", color="归集科目", text="合价",
                 title="造价构成")
    fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns([1, 2])
    if c1.button("⬅️ 一键回填到成本参数", type="primary", use_container_width=True):
        P["cost"].update(cost_map)
        P["tech"]["总装机kW"] = round(capacity, 2)
        # 清除参数控件缓存，使参数页读取回填后的新值
        for key in cost_map.keys():
            st.session_state.pop(f"in_cost_{key}", None)
        st.session_state.pop("in_tech_总装机kW", None)
        st.session_state.result = None
        st.session_state.mc = None
        st.success(f"已回填：设备 {cost_map['设备购置费']:,.0f} 元、建安 {cost_map['建安施工造价']:,.0f} 元、"
                   f"并网 {cost_map['并网配套费']:,.0f} 元、前期 {cost_map['前期咨询费']:,.0f} 元；"
                   f"装机容量 {capacity:.2f} kW")
    c2.info("回填后请到「项目参数录入」核对，再到「动态收益测算」重新计算。造价清单可按需单独调整。")

    st.download_button("📥 导出造价清单 CSV", data=boq.to_csv(index=False).encode("utf-8-sig"),
                       file_name="造价清单BOQ.csv", mime="text/csv")


# ================================================================ 页面 4：图纸解析

def page_dxf():
    st.title("③ 图纸解析（DXF）与工程量初算")
    st.caption("对应申报书「图纸解析与工程量提取模块」：机器初算 + 人工校核，不追求全自动替代人工。")

    st.info("**V1.0 能力边界**：支持 DXF 图层图元统计与线长/面积初算（需本地安装 `ezdxf`）；"
            "不支持 DWG 二进制直读与 IFC/BIM 构件级建模（列入 V1.1 迭代）。"
            "未安装解析依赖时，直接在「工程量与造价」页手工录入工程量，业务流程同样完整可用。")

    uploaded = st.file_uploader("上传 DXF 图纸", type=["dxf"], key="dxf_upload")
    if uploaded is not None:
        if st.button("🔍 执行机器初算", type="primary"):
            with st.spinner("正在解析图纸图层与图元..."):
                result, msg = drawing.parse_dxf(uploaded.getvalue())
            if result is None:
                st.error(msg)
            else:
                st.session_state.dxf = result
                st.success(msg)

    if st.session_state.dxf:
        d = st.session_state.dxf
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("图层数量", d["图层数量"])
        c2.metric("图元总数", d["图元总数"])
        c3.metric("总线长（m）", f"{d['总线长m']:,.1f}")
        c4.metric("闭合面积（m²）", f"{d['闭合多段线面积合计m2']:,.1f}")

        st.subheader("图层图元统计（机器初算）")
        df_layer = pd.DataFrame(
            [{"图层": k, "图元数": v, "线长(m)": d["图层线长"].get(k, 0.0)}
             for k, v in d["图层统计"].items()]
        ).sort_values("图元数", ascending=False)
        st.dataframe(df_layer, use_container_width=True, hide_index=True)
        st.plotly_chart(px.bar(df_layer, x="图层", y="图元数", title="各图层图元数量分布"),
                        use_container_width=True)

        st.subheader("人工校核")
        st.markdown("""
        解析结果仅为参考，请按图纸人工核对后使用：
        1. 对照图例确认「光伏组件」「支架」「电缆」所在图层是否符合实际；
        2. 确认图纸单位为毫米，若为其他单位需自行换算；
        3. 核对输出线长与屋面面积是否与实际工程一致，再决定是否采纳。
        """)
        if st.button("✅ 采纳初算结果（覆盖工程量中的电缆长度与屋面面积）", use_container_width=True):
            st.session_state.quantities = drawing.apply_dxf_hint(st.session_state.quantities, d)
            st.session_state["q_cable"] = float(st.session_state.quantities["电缆长度m"])
            st.session_state["q_roof"] = float(st.session_state.quantities["屋面面积m2"])
            st.success("已写入工程量，请前往「工程量与造价」核对并组价")


# ================================================================ 页面 5：动态收益测算

def page_results():
    st.title("④ 动态经济评价测算")
    st.caption("依据 NB/T 11894-2025《光伏发电项目经济评价规范》与《建设项目经济评价方法与参数》的通用口径。")

    if st.button("🚀 执行测算", type="primary"):
        errors = economics.validate_params(st.session_state.params)
        if errors:
            for e in errors:
                st.error(e)
        else:
            with st.spinner("正在逐年推演 25 年现金流..."):
                st.session_state.result = economics.evaluate(st.session_state.params)
                st.session_state.mc = None
            st.success("测算完成")

    if not ensure_result():
        return

    res = st.session_state.result
    metric_row(res)

    if res["irr"] is not None and res["irr"] < P["risk"]["IRR预警阈值"]:
        st.error(f"⚠️ IRR {res['irr']:.2%} 低于预警阈值 {P['risk']['IRR预警阈值']:.2%}：项目在该参数下收益不达标。")
    elif res["npv"] < 0:
        st.error("⚠️ 净现值为负：按当前折现率项目不具备投资价值。")
    else:
        st.success("✅ 当前参数下项目经济性合格（NPV ≥ 0 且 IRR ≥ 预警阈值）。")

    st.divider()
    tab1, tab2, tab3, tab4 = st.tabs(["现金流曲线", "发电量与收入", "逐年明细表", "成果保存"])

    with tab1:
        df_cum = pd.DataFrame({
            "年份": list(range(0, res["life"] + 1)),
            "累计现金流(元)": res["cumulative"],
        })
        fig1 = px.line(df_cum, x="年份", y="累计现金流(元)", markers=True,
                       title="累计净现金流曲线（含初始投资）")
        fig1.add_hline(y=0, line_dash="dash", line_color="red")
        if res["static_payback"]:
            fig1.add_vline(x=res["static_payback"], line_dash="dot", line_color="green",
                           annotation_text=f"静态回收期 {res['static_payback']:.2f} 年")
        st.plotly_chart(fig1, use_container_width=True)

        df_cf = pd.DataFrame({
            "年份": list(range(1, res["life"] + 1)),
            "年度净现金流(元)": res["series"]["经营现金流"],
        })
        fig2 = px.bar(df_cf, x="年份", y="年度净现金流(元)", title="年度净现金流柱状图")
        st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        s = res["series"]
        years = list(range(1, res["life"] + 1))
        fig3 = px.line(x=years, y=s["发电量"], markers=True,
                       labels={"x": "年份", "y": "发电量(kWh)"}, title="逐年发电量（含组件衰减）")
        st.plotly_chart(fig3, use_container_width=True)

        df_rev = pd.DataFrame({
            "年份": years,
            "自用电费收入": [s["发电量"][i] * P["tech"]["自发自用比例"] * P["finance"]["自发自用电价"] for i in range(len(years))],
            "上网电费收入": [s["发电量"][i] * (1 - P["tech"]["自发自用比例"]) * P["finance"]["余电上网电价"] for i in range(len(years))],
        })
        fig4 = px.area(df_rev, x="年份", y=["自用电费收入", "上网电费收入"],
                       title="收入构成（自发自用 vs 余电上网）")
        st.plotly_chart(fig4, use_container_width=True)

        df_base = pd.DataFrame({
            "项目": ["电费收入(含税)", "运维+保险", "增值税+附加", "折旧", "所得税"],
            "首年金额": [
                s["含税电费收入"][0],
                s["运维费"][0] + s["保险费"][0],
                s["应交增值税"][0] + s["附加税"][0],
                s["折旧"][0],
                s["所得税"][0],
            ],
        })
        fig5 = px.bar(df_base, x="项目", y="首年金额", title="首年收支结构")
        st.plotly_chart(fig5, use_container_width=True)

    with tab3:
        df_detail = pd.DataFrame({
            "年份": years,
            "发电量(kWh)": np.round(s["发电量"], 0),
            "含税收入(元)": np.round(s["含税电费收入"], 0),
            "应交增值税(元)": np.round(s["应交增值税"], 0),
            "附加税(元)": np.round(s["附加税"], 0),
            "折旧(元)": np.round(s["折旧"], 0),
            "利润总额(元)": np.round(s["利润总额"], 0),
            "所得税(元)": np.round(s["所得税"], 0),
            "净利润(元)": np.round(s["净利润"], 0),
            "净现金流(元)": np.round(s["经营现金流"], 0),
            "累计现金流(元)": np.round(res["cumulative"][1:], 0),
        })
        st.dataframe(df_detail, use_container_width=True, hide_index=True, height=460)

    with tab4:
        st.markdown("**保存当前方案**（保存后可在「多方案对比」页长期对比，数据写入本地 SQLite）")
        c1, c2 = st.columns([2, 1])
        scheme_name = c1.text_input("方案名称", value=f"方案 {pd.Timestamp.now().strftime('%m%d-%H%M')}",
                                    key="scheme_name")
        if c2.button("💾 保存方案", type="primary", use_container_width=True):
            metrics = {
                "init_invest": res["init_invest"],
                "npv": res["npv"],
                "irr": res["irr"],
                "static_payback": res["static_payback"],
                "dynamic_payback": res["dynamic_payback"],
                "lcoe": res["lcoe"],
                "capacity_kw": P["tech"]["总装机kW"],
                "unit_invest": res["unit_invest"],
            }
            sid = storage.save_scheme(scheme_name, P, metrics)
            st.success(f"已保存方案「{scheme_name}」（记录编号 {sid}）")


# ================================================================ 页面 6：敏感性分析

def page_sensitivity():
    st.title("⑤ 敏感性分析")
    st.caption("其余参数不变，单独扰动某因子，观察 IRR 与 NPV 的变化，识别关键风险驱动因素。")

    if not ensure_result():
        return
    base = P
    base_res = st.session_state.result

    c1, c2 = st.columns([2, 2])
    factor = c1.selectbox("选择分析因子", list(sensitivity.SENS_FACTORS.keys()))
    perturb_range = c2.slider("扰动幅度上限", 0.05, 0.50, 0.30, 0.05, format="%.0f%%")

    perturb = [-perturb_range, -perturb_range * 2 / 3, -perturb_range / 3, 0.0,
               perturb_range / 3, perturb_range * 2 / 3, perturb_range]
    perturb = [round(p, 4) for p in perturb]
    df = sensitivity.single_factor_analysis(base, factor, perturb)

    st.metric("基准 IRR", fmt_pct(base_res["irr"]),
              delta=f"基准 NPV {base_res['npv']:,.0f} 元")

    fig = px.line(df, x="扰动比例", y="IRR", markers=True,
                  title=f"{factor} 敏感性曲线（IRR）")
    fig.add_hline(y=P["risk"]["IRR预警阈值"], line_dash="dash", line_color="red",
                  annotation_text="IRR 预警阈值")
    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

    show = df.copy()
    show["扰动比例"] = (show["扰动比例"] * 100).round(1).astype(str) + "%"
    show["IRR"] = show["IRR"].apply(lambda v: "不可计算" if v is None else f"{v:.2%}")
    show["NPV"] = show["NPV"].apply(lambda v: f"{v:,.0f}")
    show["静态回收期"] = show["静态回收期"].apply(lambda v: "不可回收" if v is None else f"{v:.2f} 年")
    show["变量取值"] = show["变量取值"].round(2)
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("多因子敏感性（龙卷风图）")
    summary = sensitivity.multi_factor_summary(base, perturb=0.10)
    tornado_df = summary.dropna(subset=["基准IRR"]).copy()
    fig_t = go.Figure()
    fig_t.add_trace(go.Bar(y=tornado_df["因子"],
                           x=tornado_df.iloc[:, 1].fillna(-0.5) - tornado_df["基准IRR"],
                           orientation="h", name="下降 10%", marker_color="#d9534f"))
    fig_t.add_trace(go.Bar(y=tornado_df["因子"],
                           x=tornado_df.iloc[:, 2].fillna(-0.5) - tornado_df["基准IRR"],
                           orientation="h", name="上升 10%", marker_color="#2e8b57"))
    fig_t.add_vline(x=0, line_color="black")
    fig_t.update_layout(title="各因子 ±10% 对 IRR 的影响（龙卷风图）", barmode="overlay",
                        xaxis_title="IRR 变动幅度", yaxis_title="")
    fig_t.update_xaxes(tickformat=".1%")
    st.plotly_chart(fig_t, use_container_width=True)

    st.subheader("临界点分析（IRR 降至预警阈值时的因子水平）")
    cp = sensitivity.critical_points(base, ["年等效利用小时", "自发自用电价"],
                                     target_irr=P["risk"]["IRR预警阈值"])
    cp_show = cp.copy()
    cp_show["当前取值"] = cp_show["当前取值"].round(3)
    cp_show["临界取值"] = cp_show["临界取值"].apply(lambda v: "无解" if v is None or pd.isna(v) else f"{v:.3f}")
    cp_show["可下降幅度"] = cp_show["可下降幅度"].apply(
        lambda v: "—" if v is None or pd.isna(v) else f"{v:.2%}")
    st.dataframe(cp_show, use_container_width=True, hide_index=True)
    st.caption("临界值低于当前取值说明该因子尚有下降空间，可下降幅度表示安全边际；负值越大越安全。")


# ================================================================ 页面 7：风险预警

def page_risk():
    st.title("⑥ 蒙特卡洛风险模拟与预警")
    st.caption("对利用小时、造价、电价、运维成本四个因子做随机抽样，量化项目收益达标概率。")

    c1, c2 = st.columns([1, 3])
    sample_n = c1.number_input("抽样次数", min_value=200, max_value=5000,
                               value=int(P["risk"]["蒙特卡洛抽样次数"]), step=100,
                               help="建议 1000~2000 次；次数越多结果越稳定，耗时越长")
    c2.info(f"当前 IRR 预警阈值 **{P['risk']['IRR预警阈值']:.2%}**，达标概率预警阈值 "
            f"**{P['risk']['达标概率阈值']:.0%}**（可在「参数录入-风险参数」中调整）。")

    if st.button("🎲 启动蒙特卡洛模拟", type="primary"):
        with st.spinner(f"正在执行 {sample_n} 次随机抽样测算..."):
            st.session_state.mc = montecarlo.run_simulation(P, int(sample_n))
        st.success("模拟完成，结果固定（同一参数与抽样次数下结果可复现）")

    if st.session_state.mc is None:
        st.info("点击上方按钮开始模拟。建议先完成「动态收益测算」确认基础参数无误。")
        return

    mc = st.session_state.mc
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("IRR P10（悲观）", f"{mc['P10']:.2%}")
    s2.metric("IRR P50（中位）", f"{mc['P50']:.2%}")
    s3.metric("IRR P90（乐观）", f"{mc['P90']:.2%}")
    s4.metric("收益达标概率", f"{mc['pass_prob']:.1%}",
              delta=f"阈值 {mc['irr_threshold']:.2%}")

    if mc["risk_level"] == "high":
        st.error(f"🚨 {mc['risk_text']}")
    elif mc["risk_level"] == "medium":
        st.warning(f"⚠️ {mc['risk_text']}")
    else:
        st.success(f"✅ {mc['risk_text']}")

    tabs = st.tabs(["IRR 概率分布", "NPV 概率分布", "分位数对比", "三情景分析", "样本明细"])
    with tabs[0]:
        fig = px.histogram(pd.DataFrame({"IRR": mc["irr_samples"]}), x="IRR", nbins=40,
                          title=f"IRR 概率分布（{mc['sample_n']} 次抽样）")
        fig.add_vline(x=mc["irr_threshold"], line_dash="dash", line_color="red",
                      annotation_text="预警阈值")
        fig.add_vline(x=mc["P10"], line_dash="dot", line_color="gray", annotation_text="P10")
        fig.add_vline(x=mc["P50"], line_dash="dot", line_color="green", annotation_text="P50")
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    with tabs[1]:
        fig2 = px.histogram(pd.DataFrame({"NPV": mc["npv_samples"]}), x="NPV", nbins=40,
                           title="净现值 NPV 概率分布")
        fig2.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="NPV=0")
        st.plotly_chart(fig2, use_container_width=True)

    with tabs[2]:
        df_q = pd.DataFrame({
            "分位": ["P10（悲观）", "P50（中位）", "P90（乐观）"],
            "IRR": [f"{mc['P10']:.2%}", f"{mc['P50']:.2%}", f"{mc['P90']:.2%}"],
            "NPV(元)": [f"{mc['npv_P10']:,.0f}", f"{mc['npv_P50']:,.0f}", f"{mc['npv_P90']:,.0f}"],
        })
        st.dataframe(df_q, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("平均 LCOE", f"{mc['lcoe_mean']:.4f} 元/kWh")
        c2.metric("NPV≥0 概率", f"{mc['npv_positive_prob']:.1%}")
        c3.metric("IRR 标准差", f"{mc['irr_std']:.2%}")

    with tabs[3]:
        scen = montecarlo.scenario_analysis(P)
        rows = []
        for name, r in scen.items():
            rows.append({
                "情景": name,
                "IRR": fmt_pct(r["irr"]),
                "NPV(元)": f"{r['npv']:,.0f}",
                "静态回收期": fmt_year(r["static_payback"]),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("悲观：利用小时 -10%、造价 +10%、电价 -5%、运维 +15%；"
                   "乐观：利用小时 +8%、造价 -5%、电价 +3%、运维 +5%；中性为基础参数。")
        fig3 = go.Figure()
        for name, r in scen.items():
            if r["irr"] is not None:
                fig3.add_trace(go.Bar(name=name, x=["IRR"], y=[r["irr"]]))
        fig3.update_layout(title="三情景 IRR 对比", yaxis_tickformat=".0%")
        st.plotly_chart(fig3, use_container_width=True)

    with tabs[4]:
        df_s = pd.DataFrame({
            "样本序号": range(1, len(mc["irr_samples"]) + 1),
            "IRR": np.round(mc["irr_samples"], 4),
            "NPV(元)": np.round(mc["npv_samples"], 0),
            "LCOE(元/kWh)": np.round(mc["lcoe_samples"], 4),
        })
        st.dataframe(df_s, use_container_width=True, hide_index=True, height=400)

    st.divider()
    st.markdown("**风险结论可写入报告**：请在「报告导出」页生成 PDF，模拟结果会自动附在报告第四章。")


# ================================================================ 页面 8：多方案对比

def page_compare():
    st.title("⑦ 多方案对比")
    st.caption("所有保存的方案持久化在本地数据库 data/projects.db，关闭软件后仍保留。")

    schemes = storage.list_schemes()
    if not schemes:
        st.info("暂无已保存方案。请到「动态收益测算 - 成果保存」页保存至少一个方案后再来对比。")
        return

    rows = []
    for s in schemes:
        m = s.get("metrics", {})
        rows.append({
            "编号": s["id"],
            "方案名称": s["name"],
            "装机(kW)": m.get("capacity_kw"),
            "初始投资(元)": m.get("init_invest"),
            "单瓦造价(元/W)": m.get("unit_invest"),
            "NPV(元)": m.get("npv"),
            "IRR": m.get("irr"),
            "静态回收期(年)": m.get("static_payback"),
            "LCOE(元/kWh)": m.get("lcoe"),
            "保存时间": s["created_at"],
        })
    df = pd.DataFrame(rows)

    st.subheader("方案汇总对比")
    st.dataframe(
        df.style.format({
            "装机(kW)": "{:,.1f}", "初始投资(元)": "{:,.0f}", "单瓦造价(元/W)": "{:.2f}",
            "NPV(元)": "{:,.0f}", "IRR": "{:.2%}", "静态回收期(年)": "{:.2f}",
            "LCOE(元/kWh)": "{:.4f}",
        }, na_rep="—"),
        use_container_width=True, hide_index=True,
    )

    valid = df.dropna(subset=["IRR"])
    if len(valid) >= 2:
        c1, c2 = st.columns(2)
        fig = px.bar(valid, x="方案名称", y="IRR", color="方案名称", text="IRR",
                     title="IRR 对比", color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(texttemplate="%{text:.2%}", textposition="outside")
        fig.update_yaxes(tickformat=".0%")
        c1.plotly_chart(fig, use_container_width=True)

        fig2 = px.bar(valid, x="方案名称", y="NPV(元)", color="方案名称",
                      title="NPV 对比", color_discrete_sequence=px.colors.qualitative.Set3)
        c2.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("方案管理")
    c1, c2, c3 = st.columns([2, 1, 1])
    options = {f"{s['id']}｜{s['name']}": s for s in schemes}
    picked = c1.selectbox("选择方案", list(options.keys()), key="compare_pick")
    target = options[picked]
    if c2.button("📤 载入该方案参数", use_container_width=True):
        st.session_state.params = copy.deepcopy(target["params"])
        for group in ("cost", "finance", "tech", "risk"):
            for key in target["params"].get(group, {}):
                st.session_state.pop(f"in_{group}_{key}", None)
        st.session_state.result = None
        st.session_state.mc = None
        st.success(f"已载入方案「{target['name']}」的参数，请重新测算")
        st.rerun()
    if c3.button("🗑️ 删除该方案", use_container_width=True):
        storage.delete_scheme(target["id"])
        st.warning(f"已删除方案「{target['name']}」")
        st.rerun()

    if st.button("清空全部方案（谨慎操作）"):
        storage.clear_schemes()
        st.warning("已清空全部保存方案")
        st.rerun()


# ================================================================ 页面 9：报告导出

def page_report():
    st.title("⑧ 测算报告导出")
    st.caption("PDF 报告含项目概况、核心指标、输入参数、25 年现金流量表与风险模拟结论，可直接用于项目汇报与结题材料。")

    if not ensure_result():
        return
    res = st.session_state.result
    mc = st.session_state.mc

    c1, c2 = st.columns(2)
    c1.metric("初始总投资", f"{res['init_invest']:,.0f} 元")
    c2.metric("IRR", fmt_pct(res["irr"]))
    st.info("风险模拟结果：" + ("已纳入报告（第四章）" if mc else "未执行模拟，报告中不含风险章节（可先到「风险预警」页运行）"))

    note = st.text_area("报告备注（可选）", value="", height=80,
                        placeholder="例如：本方案依据 2026 年 10 月设备询价，屋面为彩钢瓦结构...")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("📄 生成 PDF 报告", type="primary", use_container_width=True):
            with st.spinner("正在排版 PDF..."):
                pdf_bytes = report.build_pdf(res, mc, note=note)
            st.session_state["pdf_bytes"] = pdf_bytes
            st.success("PDF 已生成，点击下方按钮下载")
        if st.session_state.get("pdf_bytes"):
            st.download_button("📥 下载 PDF 测算报告", data=st.session_state["pdf_bytes"],
                               file_name=f"光效智算_测算报告_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.pdf",
                               mime="application/pdf", use_container_width=True)

    with c2:
        st.download_button("📥 下载逐年现金流量表 CSV", data=report.build_csv(res),
                           file_name=f"光效智算_现金流量表_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
                           mime="text/csv", use_container_width=True)

    if st.session_state.get("pdf_bytes"):
        st.divider()
        st.subheader("报告预览（首页）")
        try:
            import fitz  # PyMuPDF 可选，用于页面预览
            doc = fitz.open(stream=st.session_state["pdf_bytes"], filetype="pdf")
            pix = doc[0].get_pixmap(dpi=110)
            st.image(pix.tobytes("png"), caption="PDF 第 1 页预览", use_container_width=True)
        except Exception:
            st.caption("当前环境未安装预览组件（PyMuPDF），下载 PDF 后可直接查看，不影响使用。")


# ================================================================ 页面 10：参数模板

def page_template():
    st.title("⑨ 参数模板导入导出")
    st.caption("把一整套参数保存为 JSON 模板，团队成员之间可直接复用，避免重复录入。")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("导出")
        json_text = storage.export_params_json(P)
        st.download_button("📥 导出当前参数模板（JSON）", data=json_text.encode("utf-8"),
                           file_name="光效智算_参数模板.json", mime="application/json",
                           use_container_width=True)
        st.code(json_text[:1200] + ("\n..." if len(json_text) > 1200 else ""), language="json")

    with c2:
        st.subheader("导入")
        uploaded = st.file_uploader("上传 JSON 参数模板", type=["json"], key="tpl_upload")
        if uploaded is not None and st.button("📤 载入模板", use_container_width=True):
            data = storage.import_params_json(uploaded.getvalue().decode("utf-8"))
            if data is None:
                st.error("模板格式不正确：需包含 cost / finance / tech / risk 四个分组")
            else:
                st.session_state.params = data
                for group in ("cost", "finance", "tech", "risk"):
                    for key in config.PARAM_META[group].keys():
                        st.session_state.pop(f"in_{group}_{key}", None)
                st.session_state.result = None
                st.session_state.mc = None
                st.success("模板已载入，请核对参数后重新测算")
                st.rerun()

    st.divider()
    st.subheader("当前参数预览")
    rows = []
    for group in ("cost", "finance", "tech", "risk"):
        for key, meta in config.PARAM_META[group].items():
            rows.append({
                "分组": config.GROUP_TITLE[group],
                "参数": meta[0],
                "单位": meta[1],
                "取值": P[group].get(key),
            })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=420)


# ================================================================ 页面 11：使用说明

def page_help():
    st.title("⑩ 使用说明与计算口径")
    st.markdown("""
    ### 一、计算口径
    1. **成本参数**均为不含税金额（元）；**电价参数**为含税销售电价（元/kWh）。
    2. **初始总投资** = 设备购置费 + 建安施工造价 + 并网配套费 + 前期咨询费。
    3. **发电量** = 装机容量 × 年等效利用小时 × (1 − 弃光率) × 衰减系数；
       首年衰减系数 = 1 − 组件首年衰减；第 n 年再乘 (1 − 后续年衰减率)。
    4. **收入** = 自用电量 × 自用电价 + 上网电量 × 上网电价 + 年度补贴。
    5. **增值税**：销项税 = 不含税收入 × 增值税率；进项税来源于设备、建安、并网三类投资，
       按年结转抵扣；**附加税** = 应交增值税 × 附加税率。
    6. **折旧**：直线法，年折旧额 = 初始投资 × (1 − 残值率) / 折旧年限；
       寿命末回收残值。
    7. **所得税**：以利润总额为基数，支持"三免三减半"（在财务参数中设置免/减半年数）。
    8. **净现金流** = 含税电费收入 + 补贴 − 运维费 − 保险费 − 融资利息 − 附加税
       − 应交增值税 − 所得税（寿命末年另加残值）。
    9. **NPV** 以基准折现率折现首年投资与各年净现金流；**IRR** 用二分法求解 NPV=0；
       **回收期**采用线性插值，静态口径折现率为 0。
    10. **LCOE** = (初始投资 + Σ(运维+保险)折现) / Σ发电量折现。

    ### 二、主要功能边界
    - 本软件面向**中小型屋顶分布式光伏**前期投资决策，不适用于大型地面电站的复杂融资结构测算；
    - 图纸解析 V1.0 仅支持 DXF 图元统计（依赖可选库 ezdxf），DWG/IFC 解析列入 V1.1；
    - 蒙特卡洛采用独立正态抽样，未构建因子间相关性矩阵（V1.1 计划引入相关性建模）。

    ### 三、免责声明
    本软件输出结果为工程投资决策辅助参考，不构成投资建议，不能替代具备资质单位出具的
    可行性研究报告、造价咨询成果文件与电网接入评审意见。实际投资决策应以正式评审结论为准。

    ### 四、软件信息
    """)
    st.table(pd.DataFrame({
        "项目": ["软件名称", "版本", "开发语言", "运行环境", "依赖库", "著作权人"],
        "内容": [
            config.APP_NAME,
            config.APP_VERSION,
            "Python 3.10+",
            "Windows / macOS / Linux，浏览器访问",
            "streamlit、pandas、numpy、plotly、reportlab、ezdxf(可选)",
            config.APP_AUTHOR,
        ],
    }))
    st.caption("技术支持：大创项目组。软件著作权申报版本，源码结构见项目 README。")


# ================================================================ 侧边栏与路由

PAGES = {
    "项目概览": page_overview,
    "① 项目参数录入": page_params,
    "② 工程量与造价": page_boq,
    "③ 图纸解析（DXF）": page_dxf,
    "④ 动态收益测算": page_results,
    "⑤ 敏感性分析": page_sensitivity,
    "⑥ 风险预警": page_risk,
    "⑦ 多方案对比": page_compare,
    "⑧ 报告导出": page_report,
    "⑨ 参数模板": page_template,
    "⑩ 使用说明": page_help,
}

with st.sidebar:
    st.markdown(f"### ☀️ {config.APP_SHORT}")
    st.caption(f"{config.APP_VERSION}｜分布式光伏投资测算与风险预警")
    choice = st.radio("功能导航", list(PAGES.keys()), index=list(PAGES.keys()).index(st.session_state.page)
                      if st.session_state.page in PAGES else 0,
                      label_visibility="collapsed")
    st.session_state.page = choice
    st.divider()
    st.markdown(f"**当前项目**：{P['meta'].get('项目名称', '未命名')[:16]}")
    st.markdown(f"**装机容量**：{P['tech']['总装机kW']:.1f} kW")
    if st.session_state.result:
        r = st.session_state.result
        st.markdown(f"**IRR**：{fmt_pct(r['irr'])}　**NPV**：{r['npv']:,.0f} 元")
    if st.session_state.mc:
        st.markdown(f"**达标概率**：{st.session_state.mc['pass_prob']:.1%}")
    st.divider()
    if st.button("🔄 恢复默认参数", use_container_width=True):
        reset_default_params()
        st.rerun()
    st.caption("参数与方案保存在本会话与本地 SQLite，导出报告后可长期留存。")

PAGES[choice]()
