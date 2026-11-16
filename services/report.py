# -*- coding: utf-8 -*-
"""
services/report.py
测算报告导出（PDF / CSV）

PDF 使用 reportlab 的 STSong-Light 中文字体（reportlab 内置 CID 字体，无需附带字体文件），
保证中文在不同 Windows/Linux 环境都能正常显示。
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

import config

CN_FONT = "STSong-Light"
_FONT_REGISTERED = False

# 参数表格中的分组简称
GROUP_SHORT = {"cost": "成本", "finance": "财务", "tech": "技术", "risk": "风险"}

# 需按百分比格式展示的参数键
PCT_KEYS = {
    "增值税率", "所得税率", "附加税率", "折现率", "弃光率", "自发自用比例",
    "组件首年衰减", "后续年衰减率", "残值率", "利用小时波动率", "造价波动率",
    "电价波动率", "运维波动率", "达标概率阈值", "IRR预警阈值",
}


def _ensure_font():
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(CN_FONT))
        except Exception:
            # 极端环境下若 CID 字体不可用，退回 Helvetica（英文表格仍可输出）
            pass
        _FONT_REGISTERED = True


def _styles():
    _ensure_font()
    ss = getSampleStyleSheet()
    title = ParagraphStyle("cn_title", parent=ss["Title"], fontName=CN_FONT, fontSize=18, leading=26)
    h2 = ParagraphStyle("cn_h2", parent=ss["Heading2"], fontName=CN_FONT, fontSize=13, leading=20,
                        spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1a5f3f"))
    body = ParagraphStyle("cn_body", parent=ss["BodyText"], fontName=CN_FONT, fontSize=9.5, leading=15)
    small = ParagraphStyle("cn_small", parent=ss["BodyText"], fontName=CN_FONT, fontSize=8, leading=11)
    return title, h2, body, small


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}"


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:.2%}"


def _fmt_year(v) -> str:
    if v is None:
        return "项目不具备回收能力"
    return f"{v:.2f} 年"


def build_pdf(result: Dict, mc: Optional[Dict] = None, note: str = "") -> bytes:
    """
    生成 PDF 测算报告
    result : evaluate() 的返回结果
    mc     : run_simulation() 的返回结果（可选）
    note   : 备注文字（可选，写入手册说明区）
    """
    _ensure_font()
    title_style, h2, body, small = _styles()
    params = result["params"]
    meta = params.get("meta", {})
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="光效智算 光伏项目投资收益测算报告",
        author=config.APP_AUTHOR,
    )
    story = []

    # ---------------- 封面标题区
    story.append(Paragraph("分布式光伏项目投资收益测算报告", title_style))
    story.append(Paragraph(f"{config.APP_NAME}　{config.APP_VERSION}", body))
    story.append(Spacer(1, 6))
    info_rows = [
        [Paragraph("项目名称", small), Paragraph(str(meta.get("项目名称", "未命名项目")), small),
         Paragraph("建设地点", small), Paragraph(str(meta.get("建设地点", "—")), small)],
        [Paragraph("编制人", small), Paragraph(str(meta.get("编制人", "—")), small),
         Paragraph("生成时间", small), Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), small)],
        [Paragraph("装机容量", small), Paragraph(f"{params['tech']['总装机kW']:.1f} kW", small),
         Paragraph("项目寿命", small), Paragraph(f"{result['life']} 年", small)],
        [Paragraph("单瓦造价", small), Paragraph(f"{result['unit_invest']:.2f} 元/W", small),
         Paragraph("基准折现率", small), Paragraph(_fmt_pct(result["discount_rate"]), small)],
    ]
    info_tbl = Table(info_rows, colWidths=[28 * mm, 55 * mm, 28 * mm, 45 * mm])
    info_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfbfbf")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5f0")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef5f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 10))

    # ---------------- 一、核心指标
    story.append(Paragraph("一、核心经济评价指标", h2))
    metrics = [
        ["初始总投资（元）", _fmt_money(result["init_invest"]), "净现值 NPV（元）", _fmt_money(result["npv"])],
        ["内部收益率 IRR", _fmt_pct(result["irr"]), "静态投资回收期", _fmt_year(result["static_payback"])],
        ["动态投资回收期", _fmt_year(result["dynamic_payback"]), "平准化度电成本 LCOE", f"{result['lcoe']:.4f} 元/kWh" if result["lcoe"] else "—"],
        ["全周期发电量（kWh）", _fmt_money(result["total_gen"]), "全周期净收益（元）", _fmt_money(result["total_net_profit"])],
    ]
    m_tbl = Table(metrics, colWidths=[38 * mm, 42 * mm, 38 * mm, 42 * mm])
    m_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfbfbf")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5f0")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef5f0")),
    ]))
    story.append(m_tbl)
    story.append(Spacer(1, 10))

    # ---------------- 二、输入参数
    story.append(Paragraph("二、测算输入参数", h2))
    p_rows = [["类别", "参数项", "取值"]]
    labels = config.PARAM_META
    for group in ("cost", "finance", "tech", "risk"):
        for key, meta_item in labels[group].items():
            label, unit, *_ = meta_item
            value = params[group].get(key)
            if isinstance(value, (int, float)) and key in PCT_KEYS:
                shown = f"{value:.2%}"
            elif isinstance(value, float):
                shown = f"{value:,.2f}"
            else:
                shown = str(value)
            p_rows.append([GROUP_SHORT.get(group, group), f"{label}（{unit}）" if unit else label, shown])
    p_tbl = Table(p_rows, colWidths=[30 * mm, 70 * mm, 45 * mm], repeatRows=1)
    p_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d8ead9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(p_tbl)
    story.append(PageBreak())

    # ---------------- 三、逐年现金流
    story.append(Paragraph("三、逐年现金流测算表", h2))
    s = result["series"]
    cf_rows = [["年份", "发电量(kWh)", "电费收入(元)", "运维+保险(元)", "所得税(元)", "净现金流(元)", "累计现金流(元)"]]
    for i in range(result["life"]):
        cf_rows.append([
            str(i + 1),
            f"{s['发电量'][i]:,.0f}",
            f"{s['含税电费收入'][i]:,.0f}",
            f"{s['运维费'][i] + s['保险费'][i]:,.0f}",
            f"{s['所得税'][i]:,.0f}",
            f"{s['经营现金流'][i]:,.0f}",
            f"{result['cumulative'][i + 1]:,.0f}",
        ])
    cf_tbl = Table(cf_rows, colWidths=[14 * mm, 27 * mm, 27 * mm, 27 * mm, 22 * mm, 27 * mm, 30 * mm], repeatRows=1)
    cf_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d8ead9")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fbf7")]),
    ]))
    story.append(cf_tbl)

    # ---------------- 四、风险模拟
    if mc is not None:
        story.append(PageBreak())
        story.append(Paragraph("四、蒙特卡洛风险模拟结果", h2))
        story.append(Paragraph(
            f"模拟次数：{mc['sample_n']} 次；随机扰动因子：年等效利用小时、初始投资、电价、运维费；"
            f"IRR 预警阈值：{mc['irr_threshold']:.2%}。", body))
        story.append(Spacer(1, 6))
        mc_rows = [
            ["统计量", "IRR", "NPV（元）"],
            ["P10（悲观情形）", _fmt_pct(mc["P10"]), _fmt_money(mc["npv_P10"])],
            ["P50（中位情形）", _fmt_pct(mc["P50"]), _fmt_money(mc["npv_P50"])],
            ["P90（乐观情形）", _fmt_pct(mc["P90"]), _fmt_money(mc["npv_P90"])],
            ["均值", _fmt_pct(mc["irr_mean"]), _fmt_money(float(pd.Series(mc["npv_samples"]).mean()))],
            ["标准差", _fmt_pct(mc["irr_std"]), "—"],
        ]
        mc_tbl = Table(mc_rows, colWidths=[45 * mm, 45 * mm, 45 * mm])
        mc_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfbfbf")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d8ead9")),
        ]))
        story.append(mc_tbl)
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"收益达标概率（IRR ≥ 阈值）：<b>{mc['pass_prob']:.1%}</b>；"
                               f"NPV ≥ 0 概率：<b>{mc['npv_positive_prob']:.1%}</b>；"
                               f"平均 LCOE：<b>{mc['lcoe_mean']:.4f} 元/kWh</b>。", body))
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>风险评估结论：</b>{mc['risk_text']}", body))

    # ---------------- 五、说明
    story.append(Spacer(1, 10))
    story.append(Paragraph("五、测算说明与免责声明", h2))
    story.append(Paragraph(
        "1. 本报告由光效智算系统自动生成，全部输入参数以本报告第二部分所列数值为准；<br/>"
        "2. 计算口径：成本参数为不含税金额，电价为含税销售电价；增值税按销项税减进项税结转抵扣计算，"
        "附加税以应交增值税为基数；折旧采用直线法并预留残值；所得税支持“三免三减半”政策选项；<br/>"
        "3. 项目投资现金流为全投资口径，融资利息作为费用支出列示；<br/>"
        "4. 本报告为项目前期投资决策辅助材料，不能替代正式可行性研究报告、造价咨询成果及电网接入评审意见。",
        small))
    if note:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"备注：{note}", small))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def build_csv(result: Dict) -> bytes:
    """导出逐年现金流明细为 CSV（UTF-8-SIG，Excel 直接打开不乱码）"""
    s = result["series"]
    df = pd.DataFrame({
        "年份": list(range(1, result["life"] + 1)),
        "发电量(kWh)": s["发电量"],
        "含税电费收入(元)": s["含税电费收入"],
        "不含税收入(元)": s["不含税收入"],
        "应交增值税(元)": s["应交增值税"],
        "附加税(元)": s["附加税"],
        "折旧(元)": s["折旧"],
        "运维费(元)": s["运维费"],
        "保险费(元)": s["保险费"],
        "融资利息(元)": s["融资利息"],
        "利润总额(元)": s["利润总额"],
        "所得税(元)": s["所得税"],
        "净利润(元)": s["净利润"],
        "净现金流(元)": s["经营现金流"],
        "累计现金流(元)": result["cumulative"][1:],
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)
    return buf.read()
