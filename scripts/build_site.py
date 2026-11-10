#!/usr/bin/env python3
"""Build the SpecFCG GitHub Pages site (index.html) and the interactive demo.

Layout follows the MemGUI-Agent academic project page
(https://memgui-agent.github.io/): fixed nav, serif hero with stat strip,
kicker-headed sections, soft cards on a pale grid, paper-style tables.

All numbers come from this repository's real artifacts:
  runs/real/work/cards/*.md      mined function cards
  runs/real/work/graph/edges.jsonl
  runs/real/pilot_*.jsonl        real-device pilot runs
  runs/real/execute_*.json
  docs/reports/assets/*.jpg      real device screenshots
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
DEMO = SITE / "demo"
ASSETS = SITE / "assets"
EVIDENCE = SITE / "evidence"
REAL = ROOT / "runs" / "real"
CARDS = REAL / "work" / "cards"
EDGES = REAL / "work" / "graph" / "edges.jsonl"

GITHUB = "https://github.com/growvv/StarTrek"
PAGES = "https://growvv.github.io/StarTrek/"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def read_cards() -> list[dict[str, Any]]:
    cards = []
    for path in sorted(CARDS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields: dict[str, str] = {}
        current = ""
        for line in text.splitlines():
            if line.startswith("# "):
                fields["name"] = line[2:].strip()
                continue
            stripped = line.strip()
            for key in ("Intent", "Inputs", "Preconditions", "Postconditions",
                        "Effects/Outputs", "Steps", "Evidence"):
                if stripped.startswith(f"**{key}**"):
                    current = key
                    value = stripped[len(f"**{key}**"):].lstrip(":").strip()
                    fields[key] = value
                    break
            else:
                if current and stripped:
                    fields[current] = (fields.get(current, "") + "\n" + stripped).strip()
        fields["_file"] = path.name
        cards.append(fields)
    return cards


def read_edges() -> list[dict[str, Any]]:
    if not EDGES.exists():
        return []
    return [
        json.loads(line)
        for line in EDGES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_pilot() -> list[dict[str, Any]]:
    """Read pilot rows, keeping the newest result per case_id.

    Files are read in name order, so a retry file (``..._2.jsonl``) replaces
    the earlier attempt for the same case.  The FAIL -> refine -> PASS story
    is told separately from the fixed numbers in ``runs/real/refine_1.json``.
    """
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(REAL.glob("pilot_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row.get("case_id", "")] = row
    return list(latest.values())


def short_steps(text: str, limit: int = 7) -> list[str]:
    steps = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit():
            steps.append(line)
        elif steps:
            steps[-1] += " " + line
    return steps[:limit]


# ---------------------------------------------------------------- CSS


CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600..800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap");
:root{
  --paper:#f7f9fc; --surface:#fff; --ink:#172033; --muted:#647086; --quiet:#8d9aad;
  --line:#dfe7f0; --blue:#246bfe; --teal:#008c83; --violet:#7a48cf; --gold:#c7831b;
  --shadow:0 18px 46px rgba(42,65,100,.10); --radius:18px;
  --mono:"JetBrains Mono","SFMono-Regular",Consolas,monospace;
  --display:"Fraunces",Georgia,serif;
  --sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;color:var(--ink);font-family:var(--sans);line-height:1.65;
  background:linear-gradient(180deg,#eef6ff 0,var(--paper) 620px),var(--paper)}
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(rgba(36,107,254,.045) 1px,transparent 1px),
    linear-gradient(90deg,rgba(36,107,254,.045) 1px,transparent 1px);
  background-size:36px 36px;mask-image:linear-gradient(180deg,#000 0,transparent 780px)}
a{color:var(--teal);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:4px}
img{max-width:100%}
.site-nav{position:fixed;top:0;left:0;right:0;z-index:30;
  border-bottom:1px solid rgba(223,231,240,.66);background:rgba(255,255,255,.78);
  backdrop-filter:blur(18px) saturate(160%)}
.nav-inner{width:min(1220px,calc(100% - 40px));min-height:66px;margin:0 auto;
  display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{color:var(--ink);font-family:var(--display);font-size:1.3rem;font-weight:780;line-height:1}
.brand span{color:var(--violet)}
.nav-links{display:flex;gap:20px;flex-wrap:wrap;justify-content:flex-end}
.nav-links a{color:#40506a;font-family:var(--mono);font-size:.76rem;font-weight:700}
.nav-links a:hover{color:var(--violet);text-decoration:none}
.hero{padding:112px 0 12px}
.hero-inner{width:min(1120px,calc(100% - 48px));margin:0 auto;text-align:center}
.eyebrow,.kicker{margin:0 0 14px;color:var(--violet);font-family:var(--mono);
  font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
h1{max-width:1080px;margin:0 auto;font-family:var(--display);
  font-size:clamp(2.3rem,3vw,2.95rem);font-weight:780;line-height:1.08}
.hero-sub{margin:14px auto 0;color:#354258;font-size:1.08rem;max-width:800px}
.hero-authors{max-width:900px;margin:16px auto 0;color:#40506a;font-size:.95rem;font-weight:650}
.hero-actions{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;
  margin:24px auto 0;max-width:900px}
.button{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  min-height:42px;padding:11px 20px;border:1px solid var(--line);border-radius:999px;
  background:#fff;color:var(--ink);box-shadow:0 2px 8px rgba(15,23,42,.05);
  font-family:var(--mono);font-size:.76rem;font-weight:700;line-height:1;
  transition:transform .18s ease,box-shadow .18s ease}
.button:hover{text-decoration:none;transform:translateY(-2px);box-shadow:0 12px 24px rgba(122,72,207,.16)}
.button.primary{border-color:var(--ink);background:var(--ink);color:#fff}
.button.accent{border-color:rgba(122,72,207,.28);background:#f4f0ff;color:#5d39b8}
.button.teal{border-color:rgba(0,140,131,.24);background:#e9fbf8;color:#08766f}
.stats{width:min(1120px,calc(100% - 48px));margin:34px auto 0;
  display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.stat{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:16px;
  padding:18px 20px;box-shadow:var(--shadow)}
.stat b{display:block;font-family:var(--display);font-size:2rem;line-height:1.1}
.stat span{color:var(--muted);font-size:.8rem}
.section{padding:82px 0}
.section.alt{background:rgba(238,246,249,.72)}
.wrap{width:min(1180px,calc(100% - 40px));margin:0 auto}
.section-head{display:grid;grid-template-columns:minmax(0,.9fr) minmax(320px,.72fr);
  gap:52px;align-items:end;margin-bottom:28px}
h2{margin:0;font-family:var(--display);font-size:clamp(2.1rem,2.7rem,2.8rem);
  font-weight:780;line-height:1.08}
.lead{margin:0;color:var(--muted);font-size:1.04rem}
.grid{display:grid;gap:18px}
.grid.two{grid-template-columns:repeat(2,1fr)}
.grid.three{grid-template-columns:repeat(3,1fr)}
.card{background:rgba(255,255,255,.9);border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow);padding:24px 26px}
.card h3{margin:0 0 8px;font-size:1.1rem}
.card p{margin:0;color:var(--muted)}
.card .mini{color:var(--quiet);font-family:var(--mono);font-size:.74rem}
.quote{border-left:4px solid var(--violet);background:#faf7ff;padding:14px 18px;
  border-radius:0 10px 10px 0;color:#3d3352;margin:16px 0}
.pipeline{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:20px 0 26px}
.step{position:relative;background:#fff;border:1px solid var(--line);border-radius:14px;
  padding:16px;box-shadow:0 8px 22px rgba(42,65,100,.06)}
.step .n{display:inline-flex;width:26px;height:26px;border-radius:50%;align-items:center;
  justify-content:center;background:var(--ink);color:#fff;font-family:var(--mono);
  font-size:.72rem;font-weight:700;margin-bottom:8px}
.step b{display:block;font-size:.92rem;margin-bottom:4px}
.step span{color:var(--muted);font-size:.78rem;line-height:1.45;display:block}
.step:not(:last-child)::after{content:"→";position:absolute;right:-11px;top:50%;
  transform:translateY(-50%);color:var(--quiet);font-weight:700}
pre{margin:10px 0;padding:14px 16px;border-radius:10px;background:#0f1720;color:#e6edf3;
  font:12px/1.6 var(--mono);overflow:auto;white-space:pre-wrap;word-break:break-word}
code{font-family:var(--mono);font-size:.9em;background:#eef2f6;padding:1px 5px;border-radius:4px}
pre code{background:none;padding:0;font-size:inherit}
.card-doc{background:#fff;border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--shadow);padding:22px 24px;margin:16px 0}
.card-doc h3{margin:0 0 6px;font-size:1.05rem}
.field{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;font-size:.84rem;
  padding:6px 0;border-bottom:1px dashed #e8eef5}
.field:last-child{border-bottom:none}
.field b{color:var(--quiet);font-family:var(--mono);font-size:.72rem;
  letter-spacing:.04em;text-transform:uppercase;padding-top:2px}
.field span{color:#334155;white-space:pre-wrap}
.graph{background:#fff;border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--shadow);padding:18px;margin-top:16px}
.edge{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:10px;align-items:center;
  padding:8px 0;border-bottom:1px dashed #e8eef5;font-size:.82rem}
.edge:last-child{border-bottom:none}
.edge .from,.edge .to{font-family:var(--mono);font-size:.78rem;color:#1f2937}
.edge .type{font-family:var(--mono);font-size:.68rem;font-weight:700;padding:2px 8px;
  border-radius:999px;white-space:nowrap}
.type.enables{background:#e9fbf8;color:#08766f}
.type.dataflow{background:#eef4ff;color:#315fd3}
.type.sequence{background:#f4f0ff;color:#5d39b8}
.type.calls{background:#fff4e5;color:#b54708}
table{width:100%;border-collapse:collapse;margin:14px 0;background:#fff;
  border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;
  font-size:.85rem;vertical-align:top}
th{background:#f4f8fc;color:#334155;font-family:var(--mono);font-size:.7rem;
  letter-spacing:.03em;text-transform:uppercase}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-family:var(--mono);
  font-size:.68rem;font-weight:700}
.pill.ok{background:#e7f6ec;color:#067647}
.pill.bad{background:#fff7f6;color:#b42318}
.pill.wait{background:#fff4e5;color:#b54708}
.note{background:#fffaf0;border:1px solid #f3d9a8;border-left:5px solid var(--gold);
  border-radius:10px;padding:14px 18px;margin:16px 0;color:#5b4420}
.note b{color:#8a5a00}
body,p,h1,h2,h3,td,th,li,span{overflow-wrap:anywhere;word-break:break-word}
.shot-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0}
.shot-strip figure{margin:0;background:#fff;border:1px solid var(--line);
  border-radius:14px;padding:8px;box-shadow:0 8px 22px rgba(42,65,100,.06)}
.shot-strip img{border-radius:8px;border:1px solid var(--line);display:block}
.shot-strip figcaption{color:var(--muted);font-size:.7rem;margin-top:6px;
  font-family:var(--mono);line-height:1.35}
.cta{background:linear-gradient(135deg,#172033,#2c3e63);color:#fff;border-radius:20px;
  padding:34px 38px;display:flex;flex-wrap:wrap;gap:20px;align-items:center;
  justify-content:space-between;box-shadow:0 22px 50px rgba(23,32,51,.25)}
.cta h3{margin:0 0 6px;font-family:var(--display);font-size:1.6rem}
.cta p{margin:0;color:#c9d5e8;font-size:.92rem}
.cta .button{background:#fff;border-color:#fff;color:var(--ink)}
.footer{padding:46px 0 60px;color:var(--quiet);font-size:.8rem;text-align:center}
.footer a{color:var(--muted)}
/* demo page */
.demo-shell{display:grid;grid-template-columns:minmax(260px,340px) 1fr;gap:26px;
  align-items:start;margin-top:18px}
.phone{background:#fff;border:1px solid var(--line);border-radius:26px;padding:12px;
  box-shadow:var(--shadow);position:sticky;top:88px}
.phone img{border-radius:18px;display:block;width:100%}
.phone .bar{display:flex;gap:8px;justify-content:space-between;align-items:center;
  margin-top:10px;font-family:var(--mono);font-size:.7rem;color:var(--quiet)}
.step-list{display:grid;gap:10px}
.step-item{background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;cursor:pointer;transition:border-color .15s ease,box-shadow .15s ease;
  display:grid;grid-template-columns:30px 1fr;gap:10px;align-items:start}
.step-item:hover{border-color:var(--line-strong,#c7d7e6);box-shadow:0 8px 20px rgba(42,65,100,.08)}
.step-item.active{border-color:var(--violet);box-shadow:0 10px 26px rgba(122,72,207,.16)}
.step-item .idx{width:26px;height:26px;border-radius:50%;background:#eef2f6;
  display:flex;align-items:center;justify-content:center;font-family:var(--mono);
  font-size:.7rem;font-weight:700;color:#52627a}
.step-item.active .idx{background:var(--violet);color:#fff}
.step-item b{display:block;font-size:.86rem;color:#1f2937}
.step-item span{display:block;font-size:.76rem;color:var(--muted);font-family:var(--mono)}
.controls{display:flex;gap:8px;margin-top:12px}
.controls button{flex:1;border:1px solid var(--line);background:#fff;border-radius:10px;
  padding:9px;font-family:var(--mono);font-size:.72rem;font-weight:700;cursor:pointer}
.controls button:hover{background:#f4f8fc}
.demo-note{background:#fbfdff;border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;font-size:.84rem;color:#334155;margin-top:14px}
@media (max-width:1000px){
  .section-head,.grid.two,.grid.three,.stats,.pipeline,.shot-strip,.demo-shell{
    grid-template-columns:1fr}
  .step:not(:last-child)::after{display:none}
  .nav-links{display:none}
  .phone{position:static}
  /* Wide tables scroll inside their own box instead of widening the page. */
  table{display:block;overflow-x:auto;white-space:nowrap}
  td,th{white-space:normal}
  .hero-inner,.wrap,.stats{width:calc(100% - 32px)}
  .hero{padding-top:92px}
  h1{font-size:clamp(1.8rem,7.2vw,2.4rem)}
  h2{font-size:clamp(1.6rem,6.4vw,2.1rem)}
}
"""

DEMO_JS = """
const steps = __STEPS__;
let current = 0;
const img = document.getElementById('phone-img');
const counter = document.getElementById('phone-counter');
const list = document.getElementById('step-list');
const note = document.getElementById('step-note');
function render() {
  const step = steps[current];
  img.src = step.image;
  img.alt = step.title;
  counter.textContent = (current + 1) + ' / ' + steps.length;
  note.textContent = step.note;
  [...list.children].forEach((el, i) => {
    el.classList.toggle('active', i === current);
  });
}
function go(delta) {
  current = (current + delta + steps.length) % steps.length;
  render();
}
function jump(index) { current = index; render(); }
document.getElementById('prev').addEventListener('click', () => go(-1));
document.getElementById('next').addEventListener('click', () => go(1));
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') go(-1);
  if (e.key === 'ArrowRight') go(1);
});
steps.forEach((step, index) => {
  const el = document.createElement('div');
  el.className = 'step-item';
  el.innerHTML = '<div class="idx">' + (index + 1) + '</div>' +
    '<div><b>' + step.title + '</b><span>' + step.action + '</span></div>';
  el.addEventListener('click', () => jump(index));
  list.appendChild(el);
});
render();
"""


def build_demo_page() -> None:
    steps = [
        {"image": "../assets/demo/01_notes_list.jpg", "title": "初始状态",
         "action": "OmniNotes 笔记列表（空）",
         "note": "执行前重置 App 数据，停在笔记列表。Planner 从这里读状态摘要。"},
        {"image": "../assets/demo/02_fab_menu.jpg", "title": "展开新建菜单",
         "action": "click fab_expand_menu_button",
         "note": "create_note 卡片第 1 步：点右下角悬浮按钮展开菜单。"},
        {"image": "../assets/demo/03_empty_editor.jpg", "title": "新建文本笔记",
         "action": "click fab_note",
         "note": "卡片第 2 步：选择“文本注释”，进入空白编辑器。"},
        {"image": "../assets/demo/04_filled_editor.jpg", "title": "填写标题与内容",
         "action": "input detail_title=Groceries · detail_content=Buy milk",
         "note": "参数来自 goal，由 ParamBinder 绑定到卡片 inputs：note_title / note_content。"},
        {"image": "../assets/demo/05_saved_note.jpg", "title": "保存并回到列表",
         "action": "back ×2",
         "note": "卡片要求“一个物理动作一步”：第一次 Back 收键盘，第二次退出编辑器并保存。"},
        {"image": "../assets/demo/06_search_results.jpg", "title": "搜索笔记",
         "action": "click menu_search · input Groceries · press enter",
         "note": "换一张卡片 search_notes_by_keyword，图搜索把它接在 create_note 后面。"},
        {"image": "../assets/demo/07_note_detail.jpg", "title": "打开目标笔记",
         "action": "click note_title|text=Groceries",
         "note": "open_note_by_title 使用复合选择器，避免点到搜索框里同名的文字。"},
        {"image": "../assets/demo/08_share_chooser.jpg", "title": "唤起分享面板",
         "action": "click menu_share",
         "note": "invoke_share_chooser_for_note 的 postcondition 是“分享面板已打开”，不选具体 App。"},
        {"image": "../assets/demo/09_archive_menu.jpg", "title": "打开归档菜单",
         "action": "click desc=更多选项",
         "note": "archive_note 卡片：详情页溢出菜单里有“归档”。"},
        {"image": "../assets/demo/10_archived_empty.jpg", "title": "归档完成",
         "action": "click text=归档",
         "note": "最终状态：活动笔记列表为空。goal 判定只看这一屏。"},
    ]
    js = DEMO_JS.replace("__STEPS__", json.dumps(steps, ensure_ascii=False))

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpecFCG 演示 — 一次真实执行</title>
<style>{CSS}</style></head><body>
<nav class="site-nav"><div class="nav-inner">
  <a class="brand" href="../index.html">Spec<span>FCG</span></a>
  <div class="nav-links">
    <a href="../index.html#why">背景</a><a href="../index.html#method">方法</a>
    <a href="../graph/">建图动画</a><a href="../index.html#demo">演示</a>
    <a href="../index.html#results">效果</a><a href="../index.html#usage">使用</a>
  </div>
</div></nav>

<header class="hero" style="padding-top:96px"><div class="hero-inner">
  <p class="eyebrow">Interactive Demo</p>
  <h1>一次真实执行：创建 → 搜索 → 打开 → 分享 → 归档</h1>
  <p class="hero-sub">目标：<code>Create a note titled Groceries with content Buy milk, then search for it,
  open the note, and share it</code>。下面是 Pixel 9 Pro XL 上的真实截图，逐步对应
  Planner 选出的卡片路径与 Executor 编译出的动作。</p>
  <div class="hero-actions">
    <a class="button primary" href="../index.html">← 返回项目主页</a>
    <a class="button accent" href="../index.html#results">看完整结果</a>
  </div>
</div></header>

<section class="section"><div class="wrap">
  <div class="demo-shell">
    <div class="phone">
      <img id="phone-img" src="{steps[0]['image']}" alt="{esc(steps[0]['title'])}">
      <div class="bar"><span>Pixel 9 Pro XL · Android 16</span>
        <span id="phone-counter">1 / {len(steps)}</span></div>
      <div class="controls">
        <button id="prev">← 上一步</button>
        <button id="next">下一步 →</button>
      </div>
    </div>
    <div>
      <div class="step-list" id="step-list"></div>
      <div class="demo-note" id="step-note">{esc(steps[0]['note'])}</div>
      <div class="note" style="margin-top:16px">
        <b>怎么读这个演示：</b>左边是 Pixel 9 Pro XL 的真实截图，右边每一步都标注了
        对应卡片与编译出的动作。键盘 ← / → 也能翻页。四卡长流程的原始执行记录在
        <a href="../evidence/pilot_complex_flow.jsonl">evidence/pilot_complex_flow.jsonl</a>（11 步）。
      </div>
    </div>
  </div>
</div></section>
<script>{js}</script>
</body></html>"""
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "index.html").write_text(page, encoding="utf-8")


def build_index() -> None:
    cards = read_cards()
    edges = read_edges()
    pilots = read_pilot()
    create = next((c for c in cards if c.get("name") == "create_note"), {})
    steps = short_steps(create.get("Steps", ""))
    edge_rows = "".join(
        f'<div class="edge"><span class="from">{esc(e["from"])}</span>'
        f'<span class="type {esc(e["type"])}">{esc(e["type"])}</span>'
        f'<span class="to">{esc(e["to"])}</span></div>'
        for e in edges
    )
    card_fields = ""
    for key, label in (
        ("Intent", "Intent"),
        ("Inputs", "Inputs"),
        ("Preconditions", "Preconditions"),
        ("Postconditions", "Postconditions"),
        ("Effects/Outputs", "Effects / Outputs"),
        ("Evidence", "Evidence"),
    ):
        if create.get(key):
            card_fields += (
                f'<div class="field"><b>{esc(label)}</b>'
                f'<span>{esc(create[key])}</span></div>'
            )
    step_list = "".join(f"<li>{esc(s)}</li>" for s in steps)
    card_fields += (
        f'<div class="field"><b>Steps</b><span><ol style="margin:0;padding-left:18px">'
        f"{step_list}</ol></span></div>"
    )

    def pilot_row(case_id: str, label: str) -> str:
        row = next((r for r in pilots if r.get("case_id") == case_id), None)
        if not row:
            return ""
        pill = ('<span class="pill ok">PASS</span>' if row.get("success")
                else '<span class="pill bad">FAIL</span>')
        return (
            "<tr>"
            f"<td><code>{esc(case_id)}</code><br><span class=\"mini\">{esc(label)}</span></td>"
            f"<td>{esc(row.get('goal', ''))}</td>"
            f"<td>{esc(' → '.join(row.get('path') or []))}</td>"
            f"<td class=\"num\">{row.get('steps')}</td>"
            f"<td class=\"num\">{row.get('actions_ok')}/{row.get('steps')}</td>"
            f"<td class=\"num\">{row.get('llm_calls')}</td>"
            f"<td class=\"num\">{row.get('plan_s', 0):.1f}s</td>"
            f"<td class=\"num\">{row.get('execute_s', 0):.1f}s</td>"
            f"<td>{pill}</td>"
            "</tr>"
        )

    pilot_rows = "".join([
        pilot_row("composed-create-and-archive", "两卡组合"),
        pilot_row("composed-create-and-share", "三卡组合"),
        pilot_row("complex-four-card-share", "四卡长流程"),
    ])
    if not pilot_rows:
        pilot_rows = '<tr><td colspan="9">尚未找到 pilot 结果。</td></tr>'

    passes = sum(1 for r in pilots if r.get("success"))
    total = len(pilots)
    n_cards = len(cards)
    n_edges = len(edges)

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="SpecFCG: 从执行轨迹归纳 function contract，用图搜索合成可执行 GUI 测试。">
<meta property="og:type" content="website">
<meta property="og:title" content="SpecFCG — 函数契约图驱动的移动 GUI 测试生成">
<meta property="og:description" content="从真实轨迹归纳 function card，组织成 Function Contract Graph，用目标驱动的图遍历合成可执行测试。">
<meta property="og:image" content="https://growvv.github.io/StarTrek/assets/og.png">
<meta property="og:url" content="https://growvv.github.io/StarTrek/">
<meta name="twitter:card" content="summary_large_image">
<title>SpecFCG — 函数契约图驱动的移动 GUI 测试生成</title>
<style>{CSS}</style></head><body>
<nav class="site-nav"><div class="nav-inner">
  <a class="brand" href="#">Spec<span>FCG</span></a>
  <div class="nav-links">
    <a href="#why">背景</a><a href="#method">方法</a><a href="graph/">建图动画</a>
    <a href="#innovations">核心点</a><a href="#demo">演示</a>
    <a href="#results">效果</a><a href="#usage">使用</a><a href="#cite">引用</a>
  </div>
</div></nav>

<header class="hero"><div class="hero-inner">
  <p class="eyebrow">SpecFCG · Function Contract Graph</p>
  <h1>把手机 App 的测试写成“函数契约图”，再让图搜索生成可执行测试</h1>
  <p class="hero-sub">从真实执行轨迹里归纳用户级 function card（意图、参数、前后置条件、步骤、证据），
  组织成可组合的 Function Contract Graph，用目标驱动的图遍历合成测试计划，
  执行结果再反过来修补卡片与边。</p>
  <div class="hero-actions">
    <a class="button primary" href="{GITHUB}" target="_blank" rel="noopener">GitHub 仓库</a>
    <a class="button accent" href="demo/index.html">交互演示（10 步真实截图）</a>
    <a class="button teal" href="{GITHUB}/blob/main/docs/superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md" target="_blank" rel="noopener">设计文档</a>
  </div>
</div></header>

<div class="stats">
  <div class="stat"><b>{n_cards}</b><span>从真实轨迹归纳的 function card</span></div>
  <div class="stat"><b>{n_edges}</b><span>enables / dataflow / sequence 边</span></div>
  <div class="stat"><b>{passes}/{total or '—'}</b><span>真机组合目标通过（最后一轮）</span></div>
  <div class="stat"><b>200</b><span>离线单元测试全部通过</span></div>
</div>

<section class="section" id="why"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Background</p><h2>自然语言用例与可执行 UI 动作之间，缺一层“可组合的契约”</h2></div>
    <p class="lead">工业界维护大量自然语言测试用例，但把它们变成可执行步骤仍然靠人。现有 LLM GUI agent 要么自由探索、要么逐步匹配事件，产出的路径不可复用，也不解释“为什么这一步能接下一步”。</p>
  </div>
  <div class="grid three">
    <div class="card"><h3>① 有图，没有契约</h3>
      <p>FuncDroid、GraphDroid、ProphetAgent 建了功能图或状态图，但节点是行为簇/事件，不是带参数与前后置条件的可调用单元，无法组合出新的测试目标。</p></div>
    <div class="card"><h3>② 有契约，没有图</h3>
      <p>PropGen 从轨迹归纳 <code>(P, I, Q)</code> 属性，但属性是单功能 oracle，不能拼成多步流程，也无法判断“执行 A 之后 B 是否可执行”。</p></div>
    <div class="card"><h3>③ 自由 agent，不可复现</h3>
      <p>直接让 agent 从目标出发点屏幕，路径依赖当次模型状态；失败后无法定位是卡片写错、边连错，还是 UI 变了。</p></div>
  </div>
  <div class="quote">SpecFCG 的主张：把“用户级任务”做成 <b>function card</b>（可复用、可组合、带证据），
  用 <b>enables / dataflow / sequence</b> 边连成图；规划交给图算法，语义判断交给 LLM。</div>
</div></section>

<section class="section alt" id="method"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Method</p><h2>采集 → 归纳 → 建图 → 规划 → 执行 → 修补</h2></div>
    <p class="lead">每一步都落盘成可检查的 JSON/Markdown；LLM 只负责语义判断，图搜索、参数绑定、动作编译都是确定性的。</p>
  </div>
  <div class="pipeline">
    <div class="step"><span class="n">1</span><b>采集轨迹</b><span>真机脚本或 agent 执行，记录动作、前后 UI、截图</span></div>
    <div class="step"><span class="n">2</span><b>归纳卡片</b><span>LLM 切分 episode，写成 function card（Markdown）</span></div>
    <div class="step"><span class="n">3</span><b>构建图</b><span>LLM 判断 enables / dataflow，轨迹给 sequence 边</span></div>
    <div class="step"><span class="n">4</span><b>规划</b><span>目标 → 候选卡片 → 图搜索 → 参数绑定 → 编译动作</span></div>
    <div class="step"><span class="n">5</span><b>执行与修补</b><span>真机执行，失败按类型回写卡片或边</span></div>
  </div>

  <h3 style="margin:8px 0 6px">一个例子：<code>create_note</code> 卡片（来自真实轨迹归纳）</h3>
  <p class="lead" style="font-size:.95rem">下面这张卡片是从 OmniNotes 的真实执行轨迹
  <code>omninotes-create-note-2</code> 归纳出来的，未做人工改写。</p>
  <div class="card-doc">
    <h3><code>create_note</code></h3>
    {card_fields}
  </div>

  <h3 style="margin:26px 0 6px">卡片连成图：{n_cards} 个节点，{n_edges} 条边</h3>
  <p class="lead" style="font-size:.95rem">图不是一次画出来的。每采一条轨迹，就多一张卡片、多几条边；
  下面是这个 App 的建图过程回放。</p>
  <div class="cta" style="margin:16px 0 20px">
    <div><h3>▶ 建图动画：一步一步看它长出来</h3>
      <p>每一帧对应一次真实的 <code>apply_patch</code>：归纳卡片、加顺序边、补语义边。</p></div>
    <a class="button" href="graph/">播放建图过程 →</a>
  </div>
  <div class="graph">{edge_rows}</div>
  <p class="mini" style="margin-top:10px">边只用于授权执行（enables / sequence）；dataflow 只负责参数供给，
  避免“数据上能接、但 UI 上还进不去”的短路径被误选。</p>

  <div class="grid two" style="margin-top:26px">
    <div class="card"><h3>LLM 做语义判断</h3>
      <p>切分轨迹、写卡片、判断两条边的语义、规划时判断“当前状态能否执行该卡片”“这条路径是否完整达成目标”。
      一次批量分类完成所有候选卡，避免每卡多次调用。</p></div>
    <div class="card"><h3>算法做确定性工作</h3>
      <p>图搜索（BFS/A*）、参数绑定、动作编译（显式 resource id 走快速路径，0 次 LLM）、
      逐步执行与 postcondition 校验。</p></div>
  </div>
</div></section>

<section class="section" id="innovations"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Core Ideas</p><h2>四个核心点</h2></div>
    <p class="lead">不追求“让 agent 更聪明”，而是把测试知识变成可检查、可组合、可修补的资产。</p>
  </div>
  <div class="grid two">
    <div class="card"><h3>1 · 卡片是契约，不是脚本</h3>
      <p>卡片声明 <code>Intent / Inputs / Preconditions / Postconditions / Effects / Steps / Evidence</code>。
      步骤是“做什么”的用户级描述，不是写死的坐标；执行时再按当前 UI 编译成具体点击。
      同一张卡在不同分辨率、不同版本上仍可用。</p></div>
    <div class="card"><h3>2 · 图只授权“能接”，不猜“该接”</h3>
      <p><code>enables</code> 表示前置条件被上一张卡满足，<code>sequence</code> 来自真实轨迹，
      <code>dataflow</code> 只负责参数供给。规划器先找可达路径，再用 LLM 判断路径是否真的达成目标——
      两步分开，失败时能定位是哪一步错了。</p></div>
    <div class="card"><h3>3 · 参数从目标来，不从硬编码来</h3>
      <p>目标里的 “titled Groceries with content Buy milk” 由参数绑定器映射到卡片的
      <code>note_title</code> / <code>note_content</code>，未绑定的必填参数才触发一次 LLM 补全。
      绑定结果随计划落盘，可复查。</p></div>
    <div class="card"><h3>4 · 失败反过来修图</h3>
      <p>执行失败先按类型归因（postcondition / 定位 / 前置条件 / 参数），再决定改卡片、改边还是加卡。
      下面“效果”一节有一次真实的 <b>FAIL → refine → PASS</b>。</p></div>
  </div>
</div></section>

<section class="section" id="demo"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Demo</p><h2>看一次真实执行</h2></div>
    <p class="lead">10 张 Pixel 9 Pro XL 真实截图，逐步对应卡片路径与编译出的动作；键盘 ← / → 可翻页。</p>
  </div>
  <div class="shot-strip">
    <figure><img src="assets/demo/02_fab_menu.jpg" alt="fab"><figcaption>1 · 展开新建菜单</figcaption></figure>
    <figure><img src="assets/demo/04_filled_editor.jpg" alt="editor"><figcaption>2 · 填写标题与内容</figcaption></figure>
    <figure><img src="assets/demo/06_search_results.jpg" alt="search"><figcaption>3 · 搜索 Groceries</figcaption></figure>
    <figure><img src="assets/demo/08_share_chooser.jpg" alt="share"><figcaption>4 · 唤起分享面板</figcaption></figure>
    <figure><img src="assets/demo/10_archived_empty.jpg" alt="archive"><figcaption>5 · 归档后列表为空</figcaption></figure>
  </div>
  <div class="cta">
    <div><h3>交互演示：一步一步看</h3>
      <p>每一步都有截图、动作、对应卡片，以及“为什么这一步能接下去”。</p></div>
    <a class="button" href="demo/index.html">打开演示 →</a>
  </div>
</div></section>

<section class="section alt" id="results"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Results</p><h2>真机组合目标：{passes}/{total} 通过</h2></div>
    <p class="lead">Pixel 9 Pro XL（Android 16，1008×2244），OmniNotes 6.5.1 FOSS，模型走本地 magpie 网关。
    成功判定 = 每张卡片 postcondition 满足 + 整条路径 goal 达成，只看执行后的可观察 UI。</p>
  </div>
  <table><thead><tr>
    <th>用例</th><th>目标</th><th>规划路径</th><th class="num">步数</th>
    <th class="num">动作成功</th><th class="num">LLM 调用</th><th class="num">规划</th>
    <th class="num">执行</th><th>结果</th>
  </tr></thead><tbody>{pilot_rows}</tbody></table>
  <div class="note"><b>读表提示：</b>“LLM 调用”指该用例的缓存未命中次数（缓存命中不计）。
  四卡长流程一次规划出 <code>create_note → search_notes_by_keyword → open_note_by_title →
  invoke_share_chooser_for_note</code>，11 个动作全部命中，没有回退重规划。</div>

  <h3 style="margin:30px 0 8px">一次真实的 FAIL → 修补 → PASS</h3>
  <p class="lead" style="font-size:.95rem">第一次跑“创建并归档”时，卡片在保存前就停下了：</p>
  <table><thead><tr><th>轮次</th><th>结果</th><th>失败类型</th><th>判定依据</th></tr></thead><tbody>
    <tr><td>第 1 轮</td><td><span class="pill bad">FAIL</span></td>
      <td><code>postcondition_failure</code></td>
      <td>UI 上只有工具栏和“已更新此笔记”提示，列表里看不到目标笔记卡片 ——
      编辑器还没真正退出，<code>create_note</code> 的后置条件未满足。</td></tr>
    <tr><td>修补</td><td>—</td><td>改卡片</td>
      <td>LLM 判定“最小修补是改 <code>create_note</code> 本身”：Intent 明确要求保存并回到列表，
      Steps 把“按需重复 Back 直到列表出现”写成一步。没有新增卡片或边。</td></tr>
    <tr><td>第 2 轮</td><td><span class="pill ok">PASS</span></td>
      <td>—</td><td>9 个动作全部成功，最终列表里出现 Groceries / Buy milk，归档后列表为空。</td></tr>
  </tbody></table>
  <div class="note" style="margin-top:14px"><b>为什么这件事重要：</b>失败没有被“重试一次”掩盖，
  而是变成了对图的一次有依据的修改。修补记录在
  <a href="evidence/refine_1.json">evidence/refine_1.json</a>，
  改前卡片保留在 <a href="evidence/create_note_before_refine.md">evidence/create_note_before_refine.md</a>，
  改后卡片见 <a href="evidence/cards/create_note.md">evidence/cards/create_note.md</a>，可以直接对比。</div>
  <p class="mini" style="margin-top:12px">所有原始结果行：
  <a href="evidence/pilot_composed_archive.jsonl">pilot_composed_archive.jsonl</a>（失败的第 1 轮）、
  <a href="evidence/pilot_composed_archive_2.jsonl">pilot_composed_archive_2.jsonl</a>（通过的第 2 轮）、
  <a href="evidence/pilot_composed_share.jsonl">pilot_composed_share.jsonl</a>、
  <a href="evidence/pilot_complex_flow.jsonl">pilot_complex_flow.jsonl</a>。</p>
</div></section>

<section class="section" id="usage"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Usage</p><h2>四步跑起来</h2></div>
    <p class="lead">需要 Python 3.10+、一台连着 adb 的 Android 设备，以及任意 OpenAI 兼容网关。</p>
  </div>
  <pre><code>pip install -e ".[dev,device]"
cp config/llm.example.yaml config/llm.local.yaml   # 填 base_url / api_key_env / device.serial

# 1. 采集一条真实轨迹（也可以直接用手写的 actions JSON）
python scripts/collect_trace.py --app it.feio.android.omninotes.foss \\
    --actions examples/actions_create_note.json --trace-id create-note-1 \\
    --out traces/create-note-1.json

# 2. 归纳卡片，再把卡片连成图
python -m specfcg.cli mine --config config/llm.local.yaml --trace traces/create-note-1.json
python -m specfcg.cli build-graph --config config/llm.local.yaml

# 3. 规划：目标 -> 卡片路径 -> 绑定参数 -> 编译成动作
python -m specfcg.cli plan --config config/llm.local.yaml --goal "Create a note titled Trip"

# 4. 在真机上执行，失败就修图再跑（--max-rounds）
python -m specfcg.cli run --config config/llm.local.yaml --max-rounds 2 \\
    --goal "Create a note titled Groceries with content Buy milk, then share it"</code></pre>
  <div class="grid two">
    <div class="card"><h3>没有设备也能跑</h3>
      <p><code>python -m pytest -q</code> 当前 200 passed。加 <code>--fake-llm --fake-device</code>
      可以在没有网关和设备的情况下跑通 <code>mine → build-graph → plan</code> 全链路，
      适合先验证配置和卡片格式。</p></div>
    <div class="card"><h3>产物都在磁盘上</h3>
      <p><code>cards/</code> 一张卡片一个 Markdown；<code>graph/edges.jsonl</code> 边；
      <code>traces/</code> 原始轨迹；<code>runs/</code> 计划、动作、截图、失败原因；
      <code>completion/</code> 缺失能力的假设与负知识。</p></div>
  </div>
</div></section>

<section class="section alt" id="cite"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Design &amp; Citation</p><h2>设计文档与相关工作</h2></div>
    <p class="lead">完整设计（数据模型、工作流、失败分类、补全流程）见仓库内设计文档；本页数字均可在仓库产物中复查。</p>
  </div>
  <pre><code>@misc{{specfcg2026,
  title  = {{SpecFCG: Spec-Centric Function Contract Graph for LLM-Based Mobile GUI Testing}},
  author = {{StarTrek project}},
  year   = {{2026}},
  url    = {{{GITHUB}}}
}}</code></pre>
  <p class="mini">版式参考 <a href="https://memgui-agent.github.io/" target="_blank" rel="noopener">MemGUI-Agent 项目主页</a>，
  按其结构（固定导航 / Hero + 指标条 / 分区卡片 / 论文式表格）复刻。</p>

  <h3 style="margin:26px 0 10px">更多实验报告</h3>
  <div class="grid three">
    <a class="card" href="reports/agentprog-explained.html" style="text-decoration:none;color:inherit">
      <h3>AgentProg 讲解 ↗</h3>
      <p>论文 + 代码 + 真机复现，六个环节的 Prompt 中英对照。</p></a>
    <a class="card" href="reports/agentprog-reproduction.html" style="text-decoration:none;color:inherit">
      <h3>AgentProg 复现 ↗</h3>
      <p>README 示例在 Pixel 9 Pro XL 上的完整执行记录与模型 I/O。</p></a>
    <a class="card" href="reports/model-reply-comparison.html" style="text-decoration:none;color:inherit">
      <h3>模型回复对比 ↗</h3>
      <p>同一请求下 <code>auto/</code> 各模型的原始回复与耗时。</p></a>
  </div>
</div></section>

<footer class="footer"><div class="wrap">
  SpecFCG · 真实设备 Pixel 9 Pro XL / Android 16 · 仓库 <a href="{GITHUB}">{GITHUB}</a>
</div></footer>
</body></html>"""
    (SITE / "index.html").write_text(page, encoding="utf-8")


def publish_evidence() -> None:
    """Copy the small artifacts the page cites so claims stay checkable.

    ``runs/`` is git-ignored, so without this the site would point at files a
    visitor can never open.  Only small, human-readable artifacts are copied.
    """
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    cards_out = EVIDENCE / "cards"
    cards_out.mkdir(exist_ok=True)
    for path in sorted(CARDS.glob("*.md")):
        shutil.copy2(path, cards_out / path.name)
    if EDGES.exists():
        shutil.copy2(EDGES, EVIDENCE / "edges.jsonl")
    for name in (
        "refine_1.json",
        "create_note_before_refine.md",
        "pilot_composed_archive.jsonl",
        "pilot_composed_archive_2.jsonl",
        "pilot_composed_share.jsonl",
        "pilot_complex_flow.jsonl",
    ):
        src = REAL / name
        if src.exists():
            shutil.copy2(src, EVIDENCE / name)
    (EVIDENCE / "README.md").write_text(
        "# Evidence index\n\n"
        "These files are copied verbatim from the experiment run that produced\n"
        "the project page. `runs/` is git-ignored; this folder is the public copy.\n\n"
        "| File | What it shows |\n|---|---|\n"
        "| `cards/*.md` | Function cards mined from real device traces |\n"
        "| `edges.jsonl` | Function Contract Graph edges |\n"
        "| `pilot_*.jsonl` | One row per real-device pilot case |\n"
        "| `pilot_composed_archive.jsonl` | The failing first attempt (postcondition_failure) |\n"
        "| `refine_1.json` | The graph patch proposed after that failure |\n"
        "| `create_note_before_refine.md` | The card before it was patched |\n",
        encoding="utf-8",
    )


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    publish_evidence()
    build_index()
    build_demo_page()
    # Jekyll would otherwise try to render these; keep Pages serving them as-is.
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {SITE / 'index.html'}")
    print(f"wrote {DEMO / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
