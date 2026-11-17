"""Build the AgentProg paper-review deck for a group meeting.

Reuses docs/ppt/参考模板.pptx purely as a visual template (blue header bar,
campus cover photo, page-number slot), drops its 22 content slides, and
rebuilds a compact review deck: background -> method -> experiments ->
reviewer critique -> outlook.

Run:  python scripts/build_paper_review_deck.py
Out:  docs/ppt/AgentProg_论文分享.pptx
"""

from __future__ import annotations

import copy
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "ppt" / "参考模板.pptx"
FIGDIR = ROOT / "docs" / "ppt" / "figures"
OUT = ROOT / "docs" / "ppt" / "AgentProg_论文分享.pptx"

# ---------------------------------------------------------------- palette
NAVY = RGBColor(0x15, 0x49, 0x9A)
BLUE = RGBColor(0x44, 0x72, 0xC4)
CYAN = RGBColor(0x05, 0x8D, 0xC7)
ORANGE = RGBColor(0xD9, 0x4B, 0x0F)
GREEN = RGBColor(0x2E, 0x8B, 0x3E)
GRAY = RGBColor(0x66, 0x66, 0x66)
LGRAY = RGBColor(0x8C, 0x8C, 0x8C)
DARK = RGBColor(0x26, 0x26, 0x26)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BG_SOFT = RGBColor(0xF3, 0xF6, 0xFB)
BG_BLUE = RGBColor(0xE8, 0xEF, 0xF9)
BG_ORANGE = RGBColor(0xFD, 0xF0, 0xEA)
BG_GREEN = RGBColor(0xEC, 0xF5, 0xEC)
BORDER = RGBColor(0xD5, 0xDD, 0xEA)

EA = "Microsoft YaHei"
LATIN = "Verdana"
MONO = "Consolas"

W = Inches(10)
H = Inches(5.625)
BAR_H = Emu(490600)
CONTENT_TOP = Inches(0.72)
CONTENT_BOTTOM = Inches(5.36)

# ---------------------------------------------------------------- text helpers


def set_run(run, size=14, color=DARK, bold=False, italic=False,
            latin=LATIN, ea=EA, mono=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    f.name = MONO if mono else latin
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", MONO if mono else ea)


def _bullet(p, char="▪", color=BLUE, indent=0.22):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(int(Inches(indent))))
    pPr.set("indent", str(-int(Inches(indent))))
    for tag in ("a:buNone", "a:buChar", "a:buClr", "a:buSzPts", "a:buFont"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    buClr = pPr.makeelement(qn("a:buClr"), {})
    srgb = buClr.makeelement(qn("a:srgbClr"), {"val": str(color)})
    buClr.append(srgb)
    pPr.append(buClr)
    pPr.append(pPr.makeelement(qn("a:buSzPts"), {"val": "1000"}))
    pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
    pPr.append(pPr.makeelement(qn("a:buChar"), {"char": char}))


def _nobullet(p):
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    if pPr.find(qn("a:buNone")) is None:
        pPr.append(pPr.makeelement(qn("a:buNone"), {}))


def textbox(slide, x, y, w, h, wrap=True, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    return box


def para(tf, runs, size=14, color=DARK, bold=False, first=False,
         space_before=0, space_after=0, line=1.12, align=PP_ALIGN.LEFT,
         bullet=None, bullet_color=BLUE, indent=0.22, level=0,
         latin=LATIN, ea=EA, mono=False):
    """runs: str or list of (text, {overrides})"""
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.line_spacing = line
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    if bullet:
        _bullet(p, char=bullet, color=bullet_color, indent=indent)
    else:
        _nobullet(p)
    if isinstance(runs, str):
        runs = [(runs, {})]
    for text, ov in runs:
        r = p.add_run()
        r.text = text
        set_run(r, size=ov.get("size", size), color=ov.get("color", color),
                bold=ov.get("bold", bold), italic=ov.get("italic", False),
                mono=ov.get("mono", False), latin=ov.get("latin", LATIN),
                ea=ov.get("ea", EA))
    return p


def fill_tf(tf, blocks):
    """blocks: list of dicts accepted by para()."""
    for i, b in enumerate(blocks):
        para(tf, first=(i == 0), **b)


# ---------------------------------------------------------------- shape helpers


def rect(slide, x, y, w, h, fill=BG_SOFT, line=BORDER, radius=None,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, line_w=0.75, shadow=False,
         anchor=MSO_ANCHOR.TOP):
    sh = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(line_w)
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sh.adjustments[0] = radius
        except Exception:
            pass
    if not shadow:
        sh.shadow.inherit = False
    sh.text_frame.word_wrap = True
    sh.text_frame.vertical_anchor = anchor
    sh.text_frame.margin_left = Inches(0.12)
    sh.text_frame.margin_right = Inches(0.12)
    sh.text_frame.margin_top = Inches(0.07)
    sh.text_frame.margin_bottom = Inches(0.07)
    return sh


def card(slide, x, y, w, h, title, body, accent=BLUE, fill=BG_SOFT,
         title_size=13.5, body_size=11.5, title_color=None, badge=None):
    sh = rect(slide, x, y, w, h, fill=fill, line=BORDER, radius=0.08)
    tf = sh.text_frame
    tf.margin_top = Inches(0.10)
    tf.margin_bottom = Inches(0.08)
    blocks = []
    if title:
        head = []
        if badge:
            head.append((badge + "  ", {"color": accent, "bold": True,
                                        "size": title_size}))
        head.append((title, {"color": title_color or accent, "bold": True,
                             "size": title_size}))
        blocks.append(dict(runs=head, space_after=3, line=1.05))
    if isinstance(body, str):
        body = [body]
    for i, b in enumerate(body):
        if isinstance(b, str):
            blocks.append(dict(runs=b, size=body_size, color=DARK,
                               space_before=1, line=1.16))
        else:
            blocks.append(b)
    fill_tf(tf, blocks)
    return sh


def chip(slide, x, y, w, h, text, fill=BG_BLUE, color=NAVY, size=10.5):
    sh = rect(slide, x, y, w, h, fill=fill, line=None, radius=0.45)
    tf = sh.text_frame
    tf.margin_left = Inches(0.04)
    tf.margin_right = Inches(0.04)
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    para(tf, text, size=size, color=color, bold=True, first=True,
         align=PP_ALIGN.CENTER, line=1.0)
    return sh


def arrow(slide, x, y, w, h, color=BLUE):
    sh = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


# ---------------------------------------------------------------- slide chrome


def content_slide(prs, title, page):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    bar = textbox(s, Emu(0), Emu(46750), Emu(7510200), Emu(334200),
                  anchor=MSO_ANCHOR.MIDDLE)
    bar.text_frame.margin_left = Emu(68575)
    bar.text_frame.margin_top = Emu(0)
    bar.text_frame.margin_bottom = Emu(0)
    para(bar.text_frame, title, size=20, color=WHITE, bold=True, first=True,
         line=1.0, latin=LATIN)
    num = textbox(s, Emu(8035200), Emu(4905000), Emu(1108800), Emu(223200))
    para(num.text_frame, str(page), size=11, color=GRAY, first=True,
         align=PP_ALIGN.RIGHT, line=1.0)
    return s


def headline(slide, text, y=Inches(0.62), size=15.5, color=NAVY,
             w=Inches(9.45), x=Inches(0.28)):
    box = textbox(slide, x, y, w, Inches(0.5))
    para(box.text_frame, text, size=size, color=color, bold=True, first=True,
         line=1.05)
    return box


def caption(slide, x, y, w, text, size=9, color=GRAY):
    box = textbox(slide, x, y, w, Inches(0.26))
    para(box.text_frame, text, size=size, color=color, first=True, line=1.0)


def picture(slide, name, x, y, w=None, h=None):
    path = FIGDIR / name
    kw = {}
    if w is not None:
        kw["width"] = w
    if h is not None:
        kw["height"] = h
    return slide.shapes.add_picture(str(path), x, y, **kw)


# ---------------------------------------------------------------- tables


def _cell_text(cell, runs, size=10.5, color=DARK, bold=False,
               align=PP_ALIGN.CENTER):
    cell.margin_left = Inches(0.05)
    cell.margin_right = Inches(0.05)
    cell.margin_top = Inches(0.02)
    cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = 1.0
    _nobullet(p)
    if isinstance(runs, str):
        runs = [(runs, {})]
    for text, ov in runs:
        r = p.add_run()
        r.text = text
        set_run(r, size=ov.get("size", size), color=ov.get("color", color),
                bold=ov.get("bold", bold), mono=ov.get("mono", False),
                latin=ov.get("latin", LATIN), ea=ov.get("ea", EA))


def table(slide, x, y, w, rows, col_widths, header=True, row_h=0.26,
          head_h=0.3, size=10, head_size=10, highlight_rows=(),
          first_col_left=False, header_fill=NAVY):
    nrows, ncols = len(rows), len(rows[0])
    gf = slide.shapes.add_table(nrows, ncols, x, y, w,
                                Inches(head_h + row_h * (nrows - 1)))
    tbl = gf.table
    tbl.first_row = bool(header)
    tbl.horz_banding = False
    total = sum(col_widths)
    for i, cw in enumerate(col_widths):
        tbl.columns[i].width = Emu(int(w * cw / total))
    for r in range(nrows):
        tbl.rows[r].height = Inches(head_h if (header and r == 0) else row_h)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            is_head = header and r == 0
            if is_head:
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_fill
                _cell_text(cell, val, size=head_size, color=WHITE, bold=True)
            else:
                cell.fill.solid()
                if r in highlight_rows:
                    cell.fill.fore_color.rgb = BG_BLUE
                else:
                    cell.fill.fore_color.rgb = WHITE if r % 2 else BG_SOFT
                _cell_text(
                    cell, val, size=size,
                    bold=(r in highlight_rows),
                    color=NAVY if r in highlight_rows else DARK,
                    align=(PP_ALIGN.LEFT if (first_col_left and c == 0)
                           else PP_ALIGN.CENTER),
                )
    return gf


# ---------------------------------------------------------------- cover / end


def _set_box_text(shape, lines):
    """Replace the text of a template textbox, keeping the first run's style."""
    tf = shape.text_frame
    style = None
    for p in tf.paragraphs:
        if p.runs:
            r = p.runs[0]
            try:
                color = r.font.color.rgb
            except Exception:
                color = None
            style = (r.font.size, r.font.bold, color, r.font.name)
            break

    for p in list(tf.paragraphs)[1:]:
        p._p.getparent().remove(p._p)
    first = tf.paragraphs[0]
    align = first.alignment
    for r in list(first.runs):
        r._r.getparent().remove(r._r)

    for i, line in enumerate(lines):
        p = first if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = 1.0
        run = p.add_run()          # add_run() inserts before endParaRPr
        run.text = line
        if style is not None:
            size, bold, color, name = style
            if size is not None:
                run.font.size = size
            run.font.bold = bool(bold)
            if color is not None:
                run.font.color.rgb = color
            if name:
                run.font.name = name


def build_cover(slide, layout0):
    # blue bar text lives on the layout, shared by cover and closing slide
    for sh in layout0.shapes:
        if sh.has_text_frame and sh.name.startswith("Google Shape;8"):
            _set_box_text(sh, ["AgentProg：程序引导的长程智能体上下文管理"])

    title = None
    sub = None
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text
        if "多智能体协作" in t and sh.top < Inches(2.5):
            title = sh
        elif "导师" in t or "软件学院" in t:
            sub = sh

    if title is not None:
        tf = title.text_frame
        for p in list(tf.paragraphs)[1:]:
            p._p.getparent().remove(p._p)
        p0 = tf.paragraphs[0]
        for r in list(p0.runs):
            r._r.getparent().remove(r._r)
        r = p0.add_run()
        r.text = "AgentProg"
        set_run(r, size=44, color=WHITE, bold=True, latin=LATIN, ea=LATIN)
        p1 = tf.add_paragraph()
        p1.alignment = PP_ALIGN.CENTER
        r = p1.add_run()
        r.text = "以程序引导的上下文管理"
        set_run(r, size=26, color=WHITE, bold=True)
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r = p2.add_run()
        r.text = "赋能长程 GUI 智能体"
        set_run(r, size=26, color=WHITE, bold=True)

    if sub is not None:
        tf = sub.text_frame
        for p in list(tf.paragraphs)[1:]:
            p._p.getparent().remove(p._p)
        p0 = tf.paragraphs[0]
        for r in list(p0.runs):
            r._r.getparent().remove(r._r)
        p0.alignment = PP_ALIGN.CENTER
        r = p0.add_run()
        r.text = "论文分享 · 组会报告"
        set_run(r, size=20, color=DARK, bold=True)
        for line, size in (("MobiSys 2026  ·  arXiv:2512.10371v2", 14),
                           ("2026 年 11 月 11 日", 14)):
            p = tf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = line
            set_run(r, size=size, color=GRAY)


def build_thanks(slide, layout0):
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text
        if "请老师们" in t:
            sh._element.getparent().remove(sh._element)
        elif "导师" in t or "软件学院" in t:
            sh.top = Inches(3.98)
            sh.height = Inches(0.86)
            _set_box_text(sh, ["论文分享 · 组会报告　|　2026 年 11 月 11 日"])
            for p in sh.text_frame.paragraphs:
                p.alignment = PP_ALIGN.CENTER
                for r in p.runs:
                    set_run(r, size=16, color=GRAY, bold=False)

    band = rect(slide, Inches(0), Inches(2.60), Inches(10), Inches(0.94),
                fill=NAVY, line=None, shape=MSO_SHAPE.RECTANGLE,
                anchor=MSO_ANCHOR.MIDDLE)
    para(band.text_frame, "感谢聆听　欢迎批评指正", size=34, color=WHITE,
         bold=True, first=True, align=PP_ALIGN.CENTER, line=1.0)


# ---------------------------------------------------------------- slides


def slide_toc(prs, page):
    s = content_slide(prs, "目录", page)
    items = [
        ("01", "研究背景与问题", "长程 GUI 任务的三重瓶颈", True),
        ("02", "方法：AgentProg", "STP 程序 · 上下文管理 · 全局信念状态", False),
        ("03", "实验与结果", "AndroidWorld / AW-Extend / 成本分析", False),
        ("04", "点评与展望", "优点 · 不足 · 可推进的方向", False),
    ]
    y = Inches(1.02)
    for num, title, sub, active in items:
        bar = rect(s, Inches(0.62), y, Inches(0.11), Inches(0.46),
                   fill=NAVY if active else RGBColor(0xBF, 0xBF, 0xBF),
                   line=None, radius=0.5)
        box = textbox(s, Inches(0.9), y - Inches(0.02), Inches(5.6), Inches(0.5))
        para(box.text_frame, [(num + "  ", {"color": NAVY if active else LGRAY,
                                            "bold": True, "size": 17}),
                              (title, {"color": NAVY if active else DARK,
                                       "bold": True, "size": 19})],
             first=True, line=1.0)
        box2 = textbox(s, Inches(1.62), y + Inches(0.36), Inches(5.6), Inches(0.3))
        para(box2.text_frame, sub, size=11, color=GRAY, first=True, line=1.0)
        y += Inches(0.86)

    panel = rect(s, Inches(6.85), Inches(1.02), Inches(2.85), Inches(2.62),
                 fill=BG_SOFT, line=BORDER, radius=0.05)
    tf = panel.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.14)
    fill_tf(tf, [
        dict(runs="论文信息", size=12, color=NAVY, bold=True, space_after=4),
        dict(runs="AgentProg: Empowering", size=10, color=DARK, line=1.10),
        dict(runs="Long-Horizon GUI Agents with", size=10, color=DARK, line=1.10),
        dict(runs="Program-Guided Context Management", size=10, color=DARK,
             line=1.10, space_after=8),
        dict(runs=[("作者  ", {"color": GRAY, "size": 9.5}),
                   ("清华 / 北大联合团队", {"size": 9.5})], line=1.14),
        dict(runs=[("单位  ", {"color": GRAY, "size": 9.5}),
                   ("清华大学 软件学院", {"size": 9.5})], line=1.14),
        dict(runs=[("发表  ", {"color": GRAY, "size": 9.5}),
                   ("MobiSys 2026", {"size": 9.5})], line=1.14),
        dict(runs=[("开源  ", {"color": GRAY, "size": 9.5}),
                   ("github.com/MobileLLM/AgentProg",
                    {"size": 9, "mono": True})], line=1.14),
    ])
    hint = rect(s, Inches(6.85), Inches(3.78), Inches(2.85), Inches(1.28),
                fill=BG_ORANGE, line=None, radius=0.05)
    tf = hint.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.09)
    fill_tf(tf, [
        dict(runs="带三个问题来听", size=11, color=ORANGE, bold=True,
             space_after=3),
        dict(runs="① 「程序」这个类比站得住吗？", size=9.5, line=1.28),
        dict(runs="② 增益来自方法，还是来自更强的模型？", size=9.5, line=1.28),
        dict(runs="③ 它的代价，换来了什么？", size=9.5, line=1.28),
    ])
    return s


def slide_background(prs, page):
    s = content_slide(prs, "研究背景", page)
    headline(s, "瓶颈已经从「能不能点对」转向「能不能记住并推进几十步」")
    # three difficulty cards
    cards = [
        ("① 任务规划与分解",
         "长程任务常含组合、重复、递归。序列/树式分解过于简单，"
         "「读完待办再逐条完成」这类任务在开始时无法完整规划，"
         "只能反复重规划，开销与错误一起上升。"),
        ("② 交互历史管理",
         "上下文长度有限，必须决定留什么、忘什么。现有方案缺少"
         "任务感知的判据：要么保留整段历史，要么把关键中间结果"
         "（餐厅信息、待办条目）摘要掉。"),
        ("③ 环境状态理解",
         "界面动态、部分可观测：弹窗、误触、应用被关闭、数据隐式变化。"
         "没有准确的状态认知，智能体会「以为完成了」，"
         "错误在长程中级联放大。"),
    ]
    x = Inches(0.28)
    cw = Inches(2.98)
    for i, (t, b) in enumerate(cards):
        card(s, x + i * (cw + Inches(0.14)), Inches(1.14), cw, Inches(1.62),
             t, b, accent=NAVY, body_size=10.5)
    # mobile-specific strip
    strip = rect(s, Inches(0.28), Inches(2.92), Inches(9.45), Inches(1.16),
                 fill=BG_BLUE, line=None, radius=0.05)
    tf = strip.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.09)
    fill_tf(tf, [
        dict(runs="移动端比 Web / 桌面更难，原因不在模型，而在观测通道",
             size=12, color=NAVY, bold=True, space_after=4),
        dict(runs=[("屏幕小、部分可观测更严重", {"bold": True, "size": 10.5}),
                   ("　只有一小块 UI 可见，剪贴板、返回栈、离屏选中项都不可见；",
                    {"size": 10.5}),
                   ("无障碍树常缺失或被误导", {"bold": True, "size": 10.5}),
                   ("　Web 有完整 DOM，移动端没有，符号化方案因此不可靠；",
                    {"size": 10.5}),
                   ("生态碎片化", {"bold": True, "size": 10.5}),
                   ("　不同 OS 版本、厂商的权限弹窗与交互范式都不同。",
                    {"size": 10.5})], line=1.3),
    ])
    note = rect(s, Inches(0.28), Inches(4.20), Inches(9.45), Inches(0.72),
                fill=BG_ORANGE, line=None, radius=0.06)
    tf = note.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.08)
    fill_tf(tf, [dict(runs=[("论文的出发点　", {"bold": True, "color": ORANGE,
                                              "size": 11}),
                            ("传统程序用有限的栈和堆就能执行极长的任务——它的「上下文管理」就是程序本身。"
                             "把智能体的交互历史也表示成程序，就能借用同一套留/弃机制。",
                             {"size": 11})], line=1.22)])
    return s


def slide_failure_modes(prs, page):
    s = content_slide(prs, "失败模式", page)
    headline(s, "现有方法的失败不是「不会点」，而是「记不住、算不清、看不清」",
             size=14.5)
    picture(s, "pre_case_study_cn.png", Inches(0.22), Inches(1.14),
            h=Inches(3.84))
    caption(s, Inches(0.20), Inches(5.02), Inches(3.60),
            "图 2：AW-Extend 上的三类典型失败（左栏为中文标注）", 8.2)

    x = Inches(3.94)
    cw = Inches(5.80)
    items = [
        ("① 缺乏整体规划", "MarkorTodoList：完成前两项后，模型判断「所有任务都已处理」直接 Finish，"
                          "漏掉第 3 项。", BG_ORANGE, ORANGE),
        ("② 关键信息丢失", "新建事件/联系人时参数错误（图中 Event / Contact Information Error）："
                          "打开笔记时没有把全部条目记进上下文。", BG_BLUE, NAVY),
        ("③ 误解动态环境", "要求删除「本周六」的事件，模型按字面日期删除跨多周的周六事件——"
                          "对手机内日期、系统状态理解错误。", BG_GREEN, GREEN),
    ]
    y = Inches(1.14)
    for t, b, fill, accent in items:
        card(s, x, y, cw, Inches(0.96), t, b, accent=accent, fill=fill,
             title_size=12.5, body_size=10.2)
        y += Inches(1.06)

    note = rect(s, Inches(3.94), Inches(4.56), cw, Inches(0.62),
                fill=BG_SOFT, line=BORDER, radius=0.06,
                anchor=MSO_ANCHOR.MIDDLE)
    tf = note.text_frame
    tf.margin_left = Inches(0.14)
    tf.margin_top = Inches(0.04)
    tf.margin_bottom = Inches(0.04)
    fill_tf(tf, [dict(runs=[("三种失败对应论文的三项设计：", {"size": 10.5}),
                            ("STP 显式控制流", {"bold": True, "color": NAVY, "size": 10.5}),
                            (" / ", {"size": 10.5}),
                            ("变量锚点", {"bold": True, "color": NAVY, "size": 10.5}),
                            (" / ", {"size": 10.5}),
                            ("全局信念状态", {"bold": True, "color": NAVY, "size": 10.5})],
                       line=1.2)])
    return s


def slide_related(prs, page):
    s = content_slide(prs, "相关工作", page)
    headline(s, "四类上下文策略，共同的缺口是「哪些信息该留」没有原则性判据", size=14.5)
    rows = [
        ["范式", "代表方法", "上下文策略", "长程任务下的失效方式"],
        ["滑动窗口", "UI-TARS", "只保留最近 5 张截图，FIFO 丢弃",
         "文本历史仍线性增长；旧截图一走，跨子任务的信息就断了"],
        ["摘要压缩", "M3A", "每步把观察压成一句文本摘要",
         "摘要由模型即时决定，早期关键条目被压掉且无法找回"],
        ["分层规划", "Mobile-Agent-v3", "规划器拆子任务，执行器逐个完成",
         "重规划开销大；子任务列表本身也会被遗忘（提前终止）"],
        ["符号化程序", "AutoDroid-V2", "生成精确 API 脚本并执行",
         "依赖应用文档与无障碍树，未见应用或布局变化即失败"],
    ]
    table(s, Inches(0.28), Inches(1.06), Inches(9.45), rows,
          [1.3, 1.7, 2.85, 3.65], row_h=0.55, head_h=0.30,
          size=9.8, head_size=10.2, first_col_left=True)
    # bottom comparison
    y = Inches(3.80)
    left = rect(s, Inches(0.28), y, Inches(4.62), Inches(1.32),
                fill=BG_SOFT, line=BORDER, radius=0.05)
    tf = left.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.09)
    fill_tf(tf, [
        dict(runs="共同缺陷", size=11.5, color=ORANGE, bold=True, space_after=2),
        dict(runs="前三类都只回答「怎么压缩」，没有回答「凭什么保留」。"
                  "压缩策略与任务语义脱钩，关键信息是否被保留全靠运气。",
             size=10.2, line=1.22),
    ])
    right = rect(s, Inches(5.05), y, Inches(4.68), Inches(1.32),
                 fill=BG_BLUE, line=None, radius=0.05)
    tf = right.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.10)
    fill_tf(tf, [
        dict(runs="符号化程序路线的问题更具体", size=12, color=NAVY, bold=True,
             space_after=3),
        dict(runs="移动端没有可靠 DOM，a11y 树噪声大；精确 API 脚本对语法与应用知识"
                  "要求高，遇到未见应用极易失效——这正是 STP 选择「自然语言步骤」的原因。",
             size=10.5, line=1.25),
    ])
    return s


def slide_architecture(prs, page):
    s = content_slide(prs, "整体架构", page)
    headline(s, "两阶段：先生成「语义任务程序」，再以解释器方式执行", size=15)
    picture(s, "introduction.png", Inches(4.62), Inches(1.14), w=Inches(5.12))
    caption(s, Inches(4.62), Inches(3.98), Inches(5.12),
            "图 3：AgentProg 的整体工作流（Stage 1 生成 / Stage 2 执行）", 8.5)

    items = [
        ("①", "STP 生成", "任务指令 → 带循环、分支、函数与变量的自然语言程序，并标出必须保留的变量。"),
        ("②", "动作生成", "把当前 PC 指向的指令，结合实时截图落成一段 Python 原子 API 调用。"),
        ("③", "PC 更新", "由 LLM 决定下一步跳转：前进、循环下一轮、跳分支——可跳过也可重复。"),
        ("④", "执行树", "历史按程序结构长成树；推理时只保留根到当前节点的活动路径。"),
        ("⑤", "上下文组成", "执行树 + 低层代码历史 + 变量表 + 信念状态，四项拼成每步输入。"),
    ]
    y = Inches(1.14)
    for num, t, b in items:
        box = textbox(s, Inches(0.28), y, Inches(4.16), Inches(0.60))
        tf = box.text_frame
        para(tf, [(num + " ", {"color": CYAN, "bold": True, "size": 12}),
                  (t, {"color": NAVY, "bold": True, "size": 11.5})],
             first=True, line=1.0, space_after=2)
        para(tf, b, size=9.5, color=DARK, line=1.12)
        y += Inches(0.63)

    strip = rect(s, Inches(0.28), Inches(4.42), Inches(9.45), Inches(0.72),
                 fill=BG_ORANGE, line=None, radius=0.06)
    tf = strip.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.08)
    fill_tf(tf, [dict(runs=[("关键类比　", {"bold": True, "color": ORANGE, "size": 11}),
                            ("程序执行时，栈管局部状态、堆管长期数据、函数边界决定作用域——"
                             "上下文管理是「副产品」，不需要额外的压缩策略。"
                             "AgentProg 让执行树扮演栈、变量表扮演堆。",
                             {"size": 11})], line=1.2)])
    return s


def slide_stp(prs, page):
    s = content_slide(prs, "语义任务程序 STP", page)
    headline(s, "STP = 自然语言步骤 + 结构化控制流 + 显式变量；关键在「语义容忍」",
             size=14.5)
    # code block
    code = rect(s, Inches(0.28), Inches(1.14), Inches(4.72), Inches(2.30),
                fill=RGBColor(0xF7, 0xF8, 0xFA), line=BORDER, radius=0.03)
    tf = code.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.12)
    lines = [
        [("# 打开待办笔记", {"color": LGRAY, "mono": True})],
        [("Open the note ", {"mono": True}),
         ('"todo_list.md"', {"mono": True, "color": GREEN}),
         (" in Markor.", {"mono": True})],
        [("Record all tasks as ", {"mono": True}),
         ("{task_list}", {"mono": True, "color": ORANGE, "bold": True}),
         (".", {"mono": True})],
        [("Iterate over ", {"mono": True}),
         ("{task_list}", {"mono": True, "color": ORANGE, "bold": True}),
         (", for each ", {"mono": True}),
         ("{task_item}", {"mono": True, "color": ORANGE, "bold": True}),
         (":", {"mono": True})],
        [("    if the item is a calendar event:", {"mono": True})],
        [("        create it in Simple Calendar Pro", {"mono": True})],
        [("    else:", {"mono": True})],
        [("        Complete the task described in ", {"mono": True}),
         ("{task_item}", {"mono": True, "color": ORANGE, "bold": True}),
         (".", {"mono": True})],
    ]
    for i, ln in enumerate(lines):
        runs = [(t, {**o, "size": 9.4}) for t, o in ln]
        para(tf, runs, size=9.4, first=(i == 0), line=1.30, color=DARK)
    caption(s, Inches(0.28), Inches(3.50), Inches(4.72),
            "论文附录 D 的真实 STP 片段（简化）：外层是严格骨架，内层是模糊指令", 8.5)
    # where STP sits among the four paradigms
    flow = rect(s, Inches(0.28), Inches(3.86), Inches(4.72), Inches(1.38),
                fill=BG_BLUE, line=None, radius=0.05)
    tf = flow.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.09)
    fill_tf(tf, [
        dict(runs="和「符号化程序」的区别在哪", size=11, color=NAVY, bold=True,
             space_after=3),
        dict(runs=[("AutoDroid-V2：", {"bold": True, "size": 9.8}),
                   ("getElement('user Name').text —— 控件名写死，找不到就报错。",
                    {"size": 9.8})], line=1.22),
        dict(runs=[("AgentProg：", {"bold": True, "size": 9.8}),
                   ("get user name as {name} —— 由执行器当场看屏幕决定点哪里。",
                    {"size": 9.8})], line=1.22),
    ])

    # right column
    x = Inches(5.18)
    cw = Inches(4.55)
    card(s, x, Inches(1.14), cw, Inches(1.22), "三条设计原则",
         [dict(runs=[("自然语言为底　", {"bold": True, "size": 10.5, "color": NAVY}),
                     ("步骤读得懂、跨环境通用；", {"size": 10.5})], line=1.20),
          dict(runs=[("结构化控制流　", {"bold": True, "size": 10.5, "color": NAVY}),
                     ("循环/分支/函数表达重复与递归；", {"size": 10.5})], line=1.20),
          dict(runs=[("显式数据流　", {"bold": True, "size": 10.5, "color": NAVY}),
                     ("变量作为锚点，跨步骤传递关键信息。", {"size": 10.5})], line=1.20)],
         accent=NAVY)
    card(s, x, Inches(2.48), cw, Inches(1.72), "什么是「语义容忍」",
         "同一句「Complete the task」在不同界面、不同弹窗下由执行器现场落地成不同操作。"
         "程序只约束「做什么」，不约束「怎么点」——因此对布局变化、弹窗、"
         "未见应用都留了余量，而符号化脚本会在语法/控件名不匹配时直接失败。",
         accent=ORANGE, fill=BG_ORANGE, body_size=10.2)
    card(s, x, Inches(4.32), cw, Inches(0.92), None,
         [dict(runs=[("代价　", {"bold": True, "size": 10.5, "color": ORANGE}),
                     ("「容忍」的另一面是没有形式语义：程序是否合法、能否执行，"
                      "只能靠运行时才知道。", {"size": 10.5})], line=1.22)],
         accent=ORANGE, fill=BG_SOFT)
    return s


def slide_context(prs, page):
    s = content_slide(prs, "程序引导的上下文管理", page)
    headline(s, "两条轴：控制流剪枝（少看）+ 数据流锚定（不忘）", size=15)
    picture(s, "execution_tree.png", Inches(4.55), Inches(1.16), w=Inches(5.19))
    caption(s, Inches(4.55), Inches(4.12), Inches(5.19),
            "图 4：执行树、路径剪枝与历史检索；右侧是真正送入模型的上下文", 8.5)

    blocks = [
        ("执行树：三类节点", "顺序节点挂在前一节点下；分支只记录实际执行的那一支；"
                            "循环每一轮展开一个子节点。"),
        ("路径剪枝", "推理时只取根→当前节点的活动路径，其余分支与已完成的循环轮次全部丢弃。"),
        ("按 step-ID 检索", "重新进入同一步（循环/递归）时，用程序步 ID 精确取回该步历史上的"
                            "动作与结果，作为「上次这么做的后果」提示。"),
        ("变量即锚点", "生成阶段声明关键变量（待办列表、预约时间），剪枝永不丢弃；"
                       "执行阶段还可用 Python 维护迭代器、计数器。"),
    ]
    y = Inches(1.16)
    for t, b in blocks:
        box = textbox(s, Inches(0.28), y, Inches(4.1), Inches(0.82))
        tf = box.text_frame
        para(tf, t, size=11.5, color=NAVY, bold=True, first=True, line=1.0,
             space_after=2)
        para(tf, b, size=9.8, color=DARK, line=1.16)
        y += Inches(0.80)

    strip = rect(s, Inches(0.28), Inches(4.42), Inches(9.45), Inches(0.66),
                 fill=BG_BLUE, line=None, radius=0.06)
    tf = strip.text_frame
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.07)
    fill_tf(tf, [dict(runs=[("为什么有效　", {"bold": True, "color": NAVY, "size": 11}),
                            ("剪枝去掉的是「结构性冗余」（别的分支、旧轮次），"
                             "而不是「语义上重要」的信息；后者由变量单独兜底。"
                             "两类机制互补，才同时做到上下文短与信息全。",
                             {"size": 11})], line=1.2)])
    return s


def slide_gbs(prs, page):
    s = content_slide(prs, "全局信念状态", page)
    headline(s, "全局信念状态：把「我以为」变成「我核对」", size=15)
    picture(s, "fig_gbs.png", Inches(0.28), Inches(1.34), w=Inches(4.40))
    caption(s, Inches(0.28), Inches(4.10), Inches(4.40),
            "图 5：Predict–Verify–Align 闭环，直接嵌在低层执行循环里", 8.5)

    x = Inches(4.92)
    cw = Inches(4.81)
    steps = [
        ("Predict", "维护一组关于环境状态的假设：当前在哪个界面、哪些字段已填、数据是否有效。"),
        ("Verify", "每执行一条原子命令，就把实时截图与假设对照。"),
        ("Align", "发现矛盾即判定 Belief-Reality Gap，作废旧状态，切到恢复例程（如回到目标应用重做）。"),
    ]
    y = Inches(1.14)
    for i, (t, b) in enumerate(steps):
        sh = rect(s, x, y, cw, Inches(0.66), fill=BG_SOFT, line=BORDER, radius=0.08)
        tf = sh.text_frame
        tf.margin_left = Inches(0.14)
        tf.margin_top = Inches(0.06)
        para(tf, [(f"{i+1}  ", {"color": CYAN, "bold": True, "size": 11}),
                  (t, {"color": NAVY, "bold": True, "size": 11}),
                  ("　" + b, {"size": 10})], first=True, line=1.2)
        y += Inches(0.74)

    case = rect(s, x, Inches(3.36), cw, Inches(1.82),
                fill=BG_ORANGE, line=None, radius=0.05)
    tf = case.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.08)
    fill_tf(tf, [
        dict(runs="为什么需要它", size=11, color=ORANGE, bold=True, space_after=2),
        dict(runs="剪贴板、返回栈、离屏选中项、系统日期——这些决定成败的状态根本不在截图里。"
                  "只靠观察做决策，模型会在「假前提」上继续执行，错误级联。",
             size=9.6, line=1.20),
        dict(runs="BrowserMaze 案例", size=11, color=ORANGE, bold=True,
             space_before=4, space_after=2),
        dict(runs="STP 假设无障碍网格，计划「一直向下点到底、再一直向右」。"
                  "执行中右点后位置不变 → 检测到矛盾 → 改为下/右交替，到达右下角。",
             size=9.6, line=1.20),
    ])
    return s


def slide_benchmark(prs, page):
    s = content_slide(prs, "AW-Extend", page)
    headline(s, "自建在线长程基准：19 个任务，平均超过 30 步", size=15)

    card(s, Inches(0.28), Inches(1.14), Inches(4.62), Inches(1.72),
         "组合型任务（Compositional）",
         "多个原子操作串成真实工作流，子任务之间有强依赖：上一步取到的信息"
         "必须带到下一步。考的是跨应用、跨子任务的信息保持。",
         accent=NAVY, title_size=14, body_size=11.2)
    card(s, Inches(0.28), Inches(2.98), Inches(4.62), Inches(1.72),
         "迭代型任务（Iterative）",
         "把子任务数量从 AndroidWorld 的 n=3 扩到 n=10 / n=20，子任务之间弱相关。"
         "考的是抗无关历史干扰，以及重复执行时的一致性。",
         accent=GREEN, fill=BG_GREEN, title_size=14, body_size=11.2)

    # task chips
    x = Inches(5.06)
    box = rect(s, x, Inches(1.14), Inches(4.67), Inches(1.72),
               fill=BG_SOFT, line=BORDER, radius=0.05)
    tf = box.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.10)
    fill_tf(tf, [
        dict(runs="代表任务", size=14, color=NAVY, bold=True, space_after=4),
        dict(runs="MarkorTodoList　逐条完成笔记里的待办", size=10.6, line=1.34),
        dict(runs="ContactsAddMultiple　批量建联系人并逐一发短信", size=10.6, line=1.34),
        dict(runs="ExpenseAddMultiple (n=20)　批量记账", size=10.6, line=1.34),
        dict(runs="DeleteEventsOnRelativeDay (n=20)　删「本周六」日程", size=10.6,
             line=1.34),
    ])
    card(s, x, Inches(2.98), Inches(4.67), Inches(1.72),
         "为什么必须是在线基准",
         "离线基准容易扩规模，但复现不了弹窗、状态漂移、误触这些真实动态，"
         "存在 offline-to-online gap。AW-Extend 跑在真实模拟器上，"
         "直接复用 AndroidWorld 的环境配置与状态校验脚本，评测标准一致。",
         accent=ORANGE, fill=BG_ORANGE, title_size=14, body_size=10.8)

    strip = rect(s, Inches(0.28), Inches(4.82), Inches(9.45), Inches(0.42),
                 fill=BG_BLUE, line=None, radius=0.1, anchor=MSO_ANCHOR.MIDDLE)
    tf = strip.text_frame
    tf.margin_top = 0
    tf.margin_bottom = 0
    para(tf, [("步数对比　", {"bold": True, "color": NAVY, "size": 10.5}),
              ("AW-Extend > 30 步　｜　ColorBench 13.0 步　｜　RealWebAssist 17.6 步",
               {"size": 10.5})], first=True, line=1.0)
    return s


def slide_results(prs, page):
    s = content_slide(prs, "主实验结果", page)
    headline(s, "AndroidWorld 78.0（+4.7），AW-Extend 68.4（+31.6）", size=15)

    rows1 = [
        ["方法（AndroidWorld）", "成功率"],
        ["Mobile-Agent-v3 (GUI-Owl-32B)", "73.3"],
        ["Agent S3", "68.1"],
        ["Mobile-Agent-v3 (GUI-Owl-7B)", "66.4"],
        ["UI-Venus", "65.9"],
        ["UI-TARS-1.5-API", "64.2"],
        ["MobileUse", "62.9"],
        ["M3A (SoM, Gemini-2.5-Pro)", "39.7"],
        ["AgentProg", "78.0"],
    ]
    table(s, Inches(0.28), Inches(1.16), Inches(4.45), rows1,
          [3.3, 1.0], row_h=0.30, head_h=0.30, size=9.4, head_size=9.6,
          highlight_rows=(8,), first_col_left=True)
    caption(s, Inches(0.28), Inches(3.94), Inches(4.45),
            "表 1（节选）：与已发表 SOTA 的对比；其余基线分数引自各自原文", 8.5)
    note1 = rect(s, Inches(0.28), Inches(4.24), Inches(4.45), Inches(0.96),
                 fill=BG_SOFT, line=None, radius=0.05)
    tf = note1.text_frame
    tf.margin_left = Inches(0.14)
    tf.margin_top = Inches(0.07)
    fill_tf(tf, [dict(runs=[("读表 1　", {"bold": True, "color": NAVY, "size": 10}),
                            ("前 8 名都挤在 62–73 区间：在原基准上，单步定位与基础操作已不是瓶颈。"
                             "4.7 个点属于同一梯队内的提升，还不足以单独支撑「方法有效」的结论。",
                             {"size": 10})], line=1.2)])

    rows2 = [
        ["方法（AW-Extend）", "成功率"],
        ["UI-TARS-1.5-API", "36.8"],
        ["Mobile-Agent-v3 (GUI-Owl-32B)", "28.9"],
        ["M3A (SoM)", "28.9"],
        ["Mobile-Agent-v3 (GUI-Owl-7B)", "26.3"],
        ["M3A (a11y)", "23.7"],
        ["AgentProg", "68.4"],
    ]
    table(s, Inches(5.02), Inches(1.16), Inches(4.71), rows2,
          [3.5, 1.0], row_h=0.36, head_h=0.30, size=9.8, head_size=9.6,
          highlight_rows=(6,), first_col_left=True)
    caption(s, Inches(5.02), Inches(3.74), Inches(4.71),
            "表 2：同一扩展集上，三类上下文策略代表方法的对比", 8.5)

    note = rect(s, Inches(5.02), Inches(4.02), Inches(4.71), Inches(1.20),
                fill=BG_ORANGE, line=None, radius=0.05)
    tf = note.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.08)
    fill_tf(tf, [
        dict(runs="长程才是分水岭", size=11.5, color=ORANGE, bold=True,
             space_after=2),
        dict(runs="在原基准上，领先只有 4.7 个点；换成 30+ 步的任务，"
                  "领先扩大到 31.6 个点。作者据此主张：现有方法不是不会做单个任务，"
                  "而是在长程中丢失了任务状态。", size=10, line=1.22),
    ])
    return s


def slide_breakdown(prs, page):
    s = content_slide(prs, "分项分析", page)
    headline(s, "任务越难、越长，优势越大；三个组件各自都有贡献", size=14.5)
    picture(s, "fig_level.png", Inches(0.28), Inches(1.10), w=Inches(4.42))
    caption(s, Inches(0.28), Inches(3.72), Inches(4.42),
            "图 6：AndroidWorld 分难度成功率", 8.5)
    picture(s, "fig_type.png", Inches(5.0), Inches(1.10), w=Inches(4.42))
    caption(s, Inches(5.0), Inches(3.72), Inches(4.42),
            "图 7：AW-Extend 分任务类型成功率", 8.5)

    # reading notes
    note1 = rect(s, Inches(0.28), Inches(4.02), Inches(4.42), Inches(0.60),
                 fill=BG_SOFT, line=None, radius=0.05)
    tf = note1.text_frame
    tf.margin_left = Inches(0.12)
    tf.margin_top = Inches(0.06)
    para(tf, [("读法　", {"bold": True, "color": NAVY, "size": 9.6}),
              ("难度越高差距越大：Easy 93.4 / Medium 72.2 / Hard 39.4；"
               "相对 MobileUse 分别 +9.8 / +25.0 / +13.1。", {"size": 9.6})],
         first=True, line=1.15)

    note2 = rect(s, Inches(5.0), Inches(4.02), Inches(4.42), Inches(0.60),
                 fill=BG_SOFT, line=None, radius=0.05)
    tf = note2.text_frame
    tf.margin_left = Inches(0.12)
    tf.margin_top = Inches(0.06)
    para(tf, [("读法　", {"bold": True, "color": NAVY, "size": 9.6}),
              ("迭代型 64.3 vs 基线 28.6–35.7，说明剪枝确实压住了无关历史；"
               "组合型 80.0 vs UI-TARS 60.0。", {"size": 9.6})],
         first=True, line=1.15)

    # ablation row
    ab = rect(s, Inches(0.28), Inches(4.68), Inches(9.45), Inches(0.58),
              fill=BG_BLUE, line=None, radius=0.05)
    tf = ab.text_frame
    tf.margin_left = Inches(0.14)
    tf.margin_top = Inches(0.06)
    fill_tf(tf, [
        dict(runs=[("消融（AW / AW-Extend）　", {"bold": True, "color": NAVY,
                                              "size": 10}),
                   ("完整 78.0 / 68.4　→　去全局信念状态 ", {"size": 10}),
                   ("53.9 / 35.1", {"bold": True, "color": ORANGE, "size": 10}),
                   ("　→　去执行树 ", {"size": 10}),
                   ("61.6 / 39.5", {"bold": True, "color": ORANGE, "size": 10}),
                   ("　→　去显式变量 ", {"size": 10}),
                   ("64.2 / 50.0", {"bold": True, "color": ORANGE, "size": 10}),
                   ("；STP 生成错误率 2.5%", {"size": 10})], line=1.2),
    ])
    return s


def slide_cost(prs, page):
    s = content_slide(prs, "成本与延迟", page)
    headline(s, "代价是真实的：延迟 8.5×、输出 token 56×，但动态上下文最省", size=14.5)

    rows = [
        ["方法", "静态前缀", "动态输入", "输出", "延迟"],
        ["UI-TARS", "8.1k", "315.5k", "3.2k", "312 s"],
        ["Mobile-Agent-v3", "7.9k", "809.4k", "22.1k", "1604 s"],
        ["AgentProg", "1026.4k", "301.3k", "179.7k", "2662 s"],
    ]
    table(s, Inches(0.28), Inches(1.16), Inches(4.55), rows,
          [1.55, 1.15, 1.1, 0.9, 0.85], row_h=0.34, head_h=0.32,
          size=9.6, head_size=9.4, highlight_rows=(3,), first_col_left=True)
    caption(s, Inches(0.28), Inches(2.72), Inches(4.55),
            "表 3：AW-Extend 上「三家都成功」任务的平均值（每任务）", 8.5)

    notes = rect(s, Inches(0.28), Inches(3.10), Inches(4.55), Inches(2.08),
                 fill=BG_SOFT, line=BORDER, radius=0.05)
    tf = notes.text_frame
    tf.margin_left = Inches(0.15)
    tf.margin_top = Inches(0.09)
    fill_tf(tf, [
        dict(runs="三个读数", size=11, color=NAVY, bold=True, space_after=3),
        dict(runs=[("动态输入最省　", {"bold": True, "size": 9.8}),
                   ("301k，接近 UI-TARS 的 315k，远低于分层规划的 809k。",
                    {"size": 9.8})], line=1.22, bullet="▪", indent=0.16),
        dict(runs=[("静态前缀极大　", {"bold": True, "size": 9.8}),
                   ("每调用约 12.5k token，作者主张可缓存，从而摊薄输入成本。",
                    {"size": 9.8})], line=1.22, bullet="▪", indent=0.16),
        dict(runs=[("输出与延迟翻倍　", {"bold": True, "size": 9.8}),
                   ("每步两次 LLM 调用（动作生成 + PC 更新），并要生成信念状态。",
                    {"size": 9.8})], line=1.22, bullet="▪", indent=0.16),
    ])

    picture(s, "fig_tokens.png", Inches(5.05), Inches(1.16), w=Inches(4.62))
    caption(s, Inches(5.05), Inches(3.98), Inches(4.62),
            "图 8：50 步内动态上下文 token 的增长曲线", 8.5)

    strip = rect(s, Inches(5.05), Inches(4.34), Inches(4.62), Inches(0.84),
                 fill=BG_BLUE, line=None, radius=0.05)
    tf = strip.text_frame
    tf.margin_left = Inches(0.14)
    tf.margin_top = Inches(0.07)
    fill_tf(tf, [dict(runs=[("怎么读这条线　", {"bold": True, "color": NAVY,
                                            "size": 10}),
                            ("AgentProg 全程稳定在约 9k；Mobile-Agent-v3 一直接近 17k；"
                             "UI-TARS 从 1.3k 一路涨到 11.6k——它只是丢截图，"
                             "文本历史仍在累积。", {"size": 10})], line=1.2)])
    return s


def critique_block(slide, items, y0=1.12, row_h=0.66, gap=0.035,
                   x=0.28, w=9.45, title_size=10.4, body_size=9.2):
    """Numbered review points on alternating bands, so the rhythm stays even."""
    y = Inches(y0)
    for i, (t, b) in enumerate(items):
        band = rect(slide, Inches(x), y, Inches(w), Inches(row_h),
                    fill=BG_SOFT if i % 2 == 0 else WHITE,
                    line=None, radius=0.02, anchor=MSO_ANCHOR.MIDDLE)
        tf = band.text_frame
        tf.margin_left = Inches(0.14)
        tf.margin_right = Inches(0.14)
        tf.margin_top = Inches(0.02)
        tf.margin_bottom = Inches(0.02)
        para(tf, t, size=title_size, color=ORANGE, bold=True, first=True,
             line=1.0, space_after=1)
        para(tf, b, size=body_size, color=DARK, line=1.12)
        y += Inches(row_h + gap)


def slide_pros(prs, page):
    s = content_slide(prs, "点评 · 优点", page)
    headline(s, "把「上下文管理」从工程细节提升为一个可讨论的设计问题", size=14.5)
    items = [
        ("问题选得准", "长程 GUI 任务的真实瓶颈是状态保持与成本，不是单步定位。"
                       "论文把这两件事明确为研究对象，而不是当成提示词技巧。"),
        ("类比有解释力", "「程序用栈/堆管理内存」直接给出了「留什么、丢什么」的判据，"
                         "而不是靠相似度或摘要长度拍脑袋。这是本文最有价值的思想。"),
        ("语义容忍切中要害", "移动端没有可靠 DOM、a11y 树噪声大，精确 API 脚本必然脆。"
                             "自然语言步骤 + 严格骨架的折中，方向是对的。"),
        ("消融方向一致", "去执行树、去变量、去信念状态，两套基准上同向下降；"
                         "说明三个组件不是拼凑，各自承担了不同职责。"),
        ("报告诚实", "没有隐藏 2662s 的延迟与 56× 的输出 token；也给出了 2.5% 的 STP 错误率，"
                     "并主动指出重规划尚未接入。"),
        ("数据与工程贡献", "开源完整实现 + AW-Extend 在线长程集（19 任务、可复用 AndroidWorld 校验），"
                           "社区可以直接拿去用或质疑。"),
    ]
    x0, y0 = Inches(0.28), Inches(1.10)
    cw, ch = Inches(4.62), Inches(1.24)
    for i, (t, b) in enumerate(items):
        col, row = i % 2, i // 2
        card(s, x0 + col * (cw + Inches(0.21)), y0 + row * (ch + Inches(0.11)),
             cw, ch, t, b, accent=GREEN if i % 2 else NAVY,
             fill=BG_GREEN if i % 2 else BG_SOFT, title_size=12, body_size=9.6)
    return s


def slide_cons_experiments(prs, page):
    s = content_slide(prs, "点评 · 实验层面的不足", page)
    headline(s, "最核心的一条：78.0 与 73.3 的差距无法归因于方法", size=14.5)

    items = [
        ("① 骨干模型不对等",
         "AgentProg = Gemini-2.5-Pro 规划 + UI-TARS-1.5 定位；对手 UI-TARS 是单一训练模型，"
         "Mobile-Agent-v3 绑 GUI-Owl。表 1 还混用了「自测」与「引自原文」的分数——"
         "不同骨干、不同评测版本放在一张表里比，是典型的苹果比橘子。"),
        ("② 缺关键对照",
         "没有「完全不剪枝、直接喂长上下文」的上界，就无法证明剪枝是必要的；"
         "没有同骨干的 ReAct / 摘要基线，就无法排除模型能力；AW-Extend 上缺 Agent S3（68.1）、"
         "UI-Venus（65.9）与最接近的程序化对手 AutoDroid-V2。"),
        ("③ 统计强度不足",
         "AW-Extend 只有 19 题，一题即 5.3 个点；68.4 vs 36.8 的差距约等于 6 道题。"
         "全文无种子、无重复、无置信区间，也没有报告失败任务的分布。"),
        ("④ 自建自评",
         "AW-Extend 由作者构造并自评，两类任务中迭代型多为「同一原子操作批量化」，"
         "更多考验记忆容量而非长程推理（依赖链、回退、跨应用状态）。"
         "文中引用 ColorBench / VeriWeb 说明长程基准的必要性，却没有与之对比。"),
        ("⑤ 缺失败归因",
         "AW-Extend 上 31.6% 的失败里，定位错误、PC 跳转错误、信念误报各占多少？"
         "只有组件消融，没有误差分解——消融只能说明「去掉会掉」，说不清「为什么掉」。"),
        ("⑥ 成本口径偏乐观",
         "token 只在「三家都成功」的任务上比，存在选择偏差；未报缓存命中率与单位成功成本。"
         "总输入（1026k 静态 + 301k 动态）其实高于 UI-TARS（8k + 315k），"
         "「前缀可缓存」是论证而非测量。"),
    ]
    critique_block(s, items)
    return s

def slide_cons_method(prs, page):
    s = content_slide(prs, "点评 · 方法与设计层面的不足", page)
    headline(s, "「程序」是提示词里的程序：可解释，但不可验证、不可学习", size=14.5)

    items = [
        ("① 纯提示工程，路线偏保守",
         "12.5k 静态前缀 + 每步两次调用，没有任何训练。领域正在转向端到端训练"
         "（UI-TARS、UI-Venus、GUI-Owl），该方案对模型版本漂移很敏感；"
         "「可蒸馏到端侧」只是设想，没有实验。"),
        ("② 没有真正的修复闭环",
         "STP 一次生成、全程不回改。结构错误只能靠 GBS 局部纠偏；"
         "而 2.5% 错误率的定义把「可在执行中恢复的错误假设」排除在外，"
         "这是定义层面的避风港，不是鲁棒性的证据。"),
        ("③ 「Belief MDP」更像修辞",
         "没有概率分布、没有观测模型、没有更新规则；信念是模型自己写的文本草稿。"
         "而且去掉 GBS 就掉 24.1 / 33.3 个点，幅度过大，"
         "论文未说明对照变体是否同时失去了低层代码历史——归因不干净。"),
        ("④ 剪枝会放大控制流错误",
         "PC 一旦跳错，活动路径就是错的，而被剪掉的恰恰是能暴露错误的证据。"
         "剪枝在「程序正确」时是收益，在「程序出错」时是放大器；"
         "全文没有测 PC 更新错误率。"),
        ("⑤ STP 没有形式语义",
         "只有示例、没有文法与类型系统；「语义容忍」的实质是未定义行为。"
         "没有静态校验，也没有测不同模型生成合法程序的比率——"
         "只测了最终任务成功率，掩盖了程序层的质量问题。"),
        ("⑥ 定位能力外包，泛化未验证",
         "「应对噪声 a11y 树」靠的是 UI-TARS 视觉定位，而非程序抽象本身，"
         "增益无法拆分。评测只在 Android；未测未见应用（正是它批评 AutoDroid-V2 的场景），"
         "也未测跨 OS / 厂商碎片化。"),
    ]
    critique_block(s, items)
    return s


def slide_outlook(prs, page):
    s = content_slide(prs, "总结与展望", page)
    headline(s, "从「提示词里的程序」走向「可验证、可学习、可部署的程序化智能体」",
             size=14)
    items = [
        ("① 砍掉调用次数", "PC 更新本质是分类/跳转判断，可合并进动作生成，"
                          "或换一个小模型专职做——这是最直接的成本优化。"),
        ("② 结构化状态替代自述", "把信念状态做成类型化槽位 + 不变量 + 可反驳的校验器，"
                              "让「信念」可查询、可断言，而不是每步重读一段散文。"),
        ("③ 真修复闭环", "用 Belief-Reality Gap 触发局部重规划（Reflexion / AdaPlanner 思路），"
                        "并报告「恢复率」而非只报成功率。"),
        ("④ 学习 STP 而非提示 STP", "对成功程序做 SFT / RL，让生成器学会本领域的分解模式；"
                                  "再按论文设想把执行段蒸馏到端侧 SLM（需要补实验）。"),
        ("⑤ 评测升级", "补「不剪枝的长上下文上界」与单位成功成本；跨平台（Web / 桌面）、"
                     "未见应用、跨厂商碎片化；AW-Extend 需要第三方复用来立住。"),
        ("⑥ 程序即技能库", "把验证过的子程序沉淀为可复用技能，长程任务变成已验证宏的组合——"
                        "这是「程序」类比真正兑现价值的地方。"),
    ]
    x0, y0 = Inches(0.28), Inches(1.10)
    cw, ch = Inches(4.62), Inches(1.14)
    for i, (t, b) in enumerate(items):
        col, row = i % 2, i // 2
        card(s, x0 + col * (cw + Inches(0.21)), y0 + row * (ch + Inches(0.10)),
             cw, ch, t, b, accent=NAVY if i % 2 else CYAN,
             fill=BG_BLUE if i % 2 else BG_SOFT, title_size=11.8,
             body_size=9.6)

    strip = rect(s, Inches(0.28), Inches(4.86), Inches(9.45), Inches(0.42),
                 fill=BG_ORANGE, line=None, radius=0.12,
                 anchor=MSO_ANCHOR.MIDDLE)
    tf = strip.text_frame
    tf.margin_top = 0
    tf.margin_bottom = 0
    para(tf, [("一句话总结　", {"bold": True, "color": ORANGE, "size": 10.5}),
              ("这篇论文最大的价值不是 78.0 这个数字，而是把「智能体该记住什么」"
               "变成了一个可以用程序结构来回答的问题。", {"size": 10.5})],
         first=True, line=1.0)
    return s


# ---------------------------------------------------------------- main


def main():
    prs = Presentation(str(TEMPLATE))
    slides = list(prs.slides)
    cover, thanks = slides[0], slides[-1]

    rel_id = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    sld_ids = prs.slides._sldIdLst

    # locate the closing slide's relationship id before anything moves
    thanks_rid = None
    for rid, rel in prs.part.rels.items():
        if rel.reltype.endswith("/slide") and rel.target_part is thanks.part:
            thanks_rid = rid
            break
    assert thanks_rid, "closing slide relationship not found"

    # drop the 22 template content slides
    for sld in list(sld_ids)[1:-1]:
        prs.part.drop_rel(sld.get(rel_id))
        sld_ids.remove(sld)

    build_cover(cover, prs.slide_layouts[0])

    builders = [
        slide_toc,
        slide_background,
        slide_failure_modes,
        slide_related,
        slide_architecture,
        slide_stp,
        slide_context,
        slide_gbs,
        slide_benchmark,
        slide_results,
        slide_breakdown,
        slide_cost,
        slide_pros,
        slide_cons_experiments,
        slide_cons_method,
        slide_outlook,
    ]
    for i, fn in enumerate(builders, start=2):
        fn(prs, i)

    # move the closing slide to the very end
    for sld in list(sld_ids):
        if sld.get(rel_id) == thanks_rid:
            sld_ids.remove(sld)
            sld_ids.append(sld)
            break

    build_thanks(thanks, prs.slide_layouts[0])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB, "
          f"{len(list(prs.slides))} slides)")


if __name__ == "__main__":
    main()
