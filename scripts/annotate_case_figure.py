"""给论文图 2（AW-Extend 三类失败案例）加中文标注。

原图是一张窄长的竖图，缩到幻灯片里只有 2.4 英寸宽，图里的英文小字实际上看不清。
这里先把原图放大 3 倍，再在左侧加一条中文标注栏：三个失败面板各配一个 ①②③
的中文短标题 + 一句解释，并画一条与右侧卡片同色的竖条做视觉对应。

坐标全部以「原图像素」为单位书写，绘制时统一乘 S。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FIGDIR = ROOT / "docs" / "ppt" / "figures"
SRC = FIGDIR / "pre_case_study.png"
DST = FIGDIR / "pre_case_study_cn.png"

S = 3            # 放大倍率（同时用于字号与坐标）
GUTTER = 192     # 左侧中文栏宽度（原图像素）

NAVY = (21, 73, 154)
ORANGE = (217, 75, 15)
GREEN = (46, 139, 62)
DARK = (38, 45, 56)
GRAY = (110, 118, 130)
WHITE = (255, 255, 255)

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * S, index=0)


# 三个失败面板在原图中的纵向范围（由像素扫描得到的白缝定位）
BLOCKS = [
    dict(y0=197, y1=347, accent=ORANGE,
         title="① 漏掉第 3 项",
         lines=["判定「都做完了」", "直接 Finish"]),
    dict(y0=354, y1=495, accent=NAVY,
         title="② 参数写错",
         lines=["笔记没全进上下文", "联系人信息写错"]),
    dict(y0=502, y1=651, accent=GREEN,
         title="③ 日期理解错",
         lines=["「本周六」按字面删", "误删跨多周的周六"]),
]


def main() -> None:
    src = Image.open(SRC).convert("RGB")
    w, h = src.size
    big = src.resize((w * S, h * S), Image.LANCZOS)

    canvas = Image.new("RGB", ((w + GUTTER) * S, h * S), WHITE)
    canvas.paste(big, (GUTTER * S, 0))

    d = ImageDraw.Draw(canvas)
    f_head = font(FONT_BOLD, 25)
    f_title = font(FONT_BOLD, 22)
    f_body = font(FONT_REG, 18)
    f_small = font(FONT_REG, 17)

    def T(x, y, text, f, fill):
        d.text((x * S, y * S), text, font=f, fill=fill)

    # 顶部：说明图的上下两部分分别是什么
    T(14, 22, "AW-Extend", f_head, NAVY)
    T(14, 52, "三类失败案例", f_head, NAVY)
    T(14, 104, "上半：任务定义", f_small, GRAY)
    T(14, 128, "下半：失败轨迹", f_small, GRAY)

    for b in BLOCKS:
        y0, y1, accent = b["y0"], b["y1"], b["accent"]
        # 与右侧卡片同色的竖条，紧贴原图左边界
        d.rectangle([(GUTTER - 9) * S, (y0 + 8) * S,
                     (GUTTER - 4) * S, (y1 - 8) * S], fill=accent)
        T(14, y0 + 10, b["title"], f_title, DARK)
        for i, line in enumerate(b["lines"]):
            T(14, y0 + 44 + i * 26, line, f_body, GRAY)

    canvas.save(DST)
    print("wrote", DST, canvas.size)


if __name__ == "__main__":
    main()
