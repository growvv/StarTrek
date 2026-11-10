#!/usr/bin/env python3
"""Render the FCG construction journal as an animated graph page.

Input: `graph/journal.jsonl` written by GraphStore.apply_patch, plus the cards
it references. Output: `docs/graph/index.html` — a self-contained page that
replays every patch in order, adding nodes and edges as they actually appeared.

Layout is deterministic (no external JS): nodes are placed on a circle whose
radius grows with the node count, so the same journal always renders the same
picture and the page works offline.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "graph" / "index.html"

TYPE_COLOR = {
    "enables": "#08766f",
    "sequence": "#5d39b8",
    "dataflow": "#315fd3",
    "calls": "#b54708",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def load_journal(root: Path) -> list[dict[str, Any]]:
    path = root / "graph" / "journal.jsonl"
    if not path.exists():
        raise SystemExit(f"no journal at {path}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_card_intents(root: Path) -> dict[str, str]:
    """First sentence of each card's Intent, for the node tooltip."""
    intents: dict[str, str] = {}
    cards_dir = root / "cards"
    if not cards_dir.exists():
        return intents
    for path in sorted(cards_dir.glob("*.md")):
        name = ""
        intent = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                name = line[2:].strip()
            elif line.startswith("**Intent**"):
                intent = line.split(":", 1)[-1].strip()
        if name:
            intents[name] = intent
    return intents


def layout(
    names: list[str],
    edges: list[dict[str, Any]],
    width: int = 820,
    height: int = 470,
) -> dict[str, tuple[float, float]]:
    """Layered left-to-right layout, deterministic for a given graph.

    A ring stops being readable past ~6 nodes and says nothing about flow. This
    assigns each card a column by longest-path depth over execution edges
    (enables/sequence), then spreads nodes vertically inside their column, so
    the picture reads as the pipeline the graph actually describes.
    """
    execution = {"enables", "sequence"}
    nodes = set(names)
    parents: dict[str, set[str]] = {name: set() for name in names}
    for edge in edges:
        if edge.get("type") not in execution:
            continue
        src, dst = edge.get("from"), edge.get("to")
        if src in nodes and dst in nodes and src != dst:
            parents[dst].add(src)

    depth: dict[str, int] = {}

    def resolve(name: str, stack: frozenset[str] = frozenset()) -> int:
        if name in depth:
            return depth[name]
        if name in stack:  # cycle: break it rather than recurse forever
            return 0
        upstream = parents[name]
        value = 0 if not upstream else 1 + max(
            resolve(parent, stack | {name}) for parent in upstream
        )
        depth[name] = value
        return value

    for name in names:
        resolve(name)

    columns: dict[int, list[str]] = {}
    for name in names:
        columns.setdefault(depth[name], []).append(name)
    max_depth = max(columns) if columns else 0
    col_count = max_depth + 1

    margin_x = 92
    margin_y = 54
    usable_w = width - 2 * margin_x
    usable_h = height - 2 * margin_y
    positions: dict[str, tuple[float, float]] = {}
    for col, members in columns.items():
        x = margin_x + (usable_w * col / max(1, col_count - 1) if col_count > 1 else usable_w / 2)
        step = usable_h / max(1, len(members))
        for row, name in enumerate(members):
            y = margin_y + step * (row + 0.5)
            positions[name] = (round(x, 1), round(y, 1))
    return positions


def frames(journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn journal entries into animation frames with stable node order."""
    order: list[str] = []
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(journal):
        for name in entry.get("new_cards") or []:
            if name not in seen:
                seen.add(name)
                order.append(name)
        edges = entry.get("edge_list") or []
        for edge in edges:
            for key in ("from", "to"):
                name = edge.get(key)
                if name and name not in seen:
                    seen.add(name)
                    order.append(name)
        result.append(
            {
                "index": index,
                "reason": entry.get("reason", ""),
                "ts": entry.get("ts", ""),
                "cards_added": entry.get("cards_added", 0),
                "cards_updated": entry.get("cards_updated", 0),
                "edges_added": entry.get("edges_added", 0),
                "cards_total": entry.get("cards_total", 0),
                "edges_total": entry.get("edges_total", 0),
                "nodes": list(order),
                "edges": [
                    {"from": e["from"], "to": e["to"], "type": e["type"]}
                    for e in edges
                ],
                "new_cards": list(entry.get("new_cards") or []),
                "new_edges": [
                    {"from": e["from"], "to": e["to"], "type": e["type"]}
                    for e in entry.get("new_edges") or []
                ],
            }
        )
    return result


CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600..800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap");
:root{--paper:#f7f9fc;--ink:#172033;--muted:#647086;--line:#dfe7f0;--violet:#7a48cf;
  --teal:#008c83;--gold:#c7831b;--shadow:0 18px 46px rgba(42,65,100,.10);
  --mono:"JetBrains Mono",Consolas,monospace;--display:"Fraunces",Georgia,serif;
  --sans:"Inter",system-ui,sans-serif;}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);font-family:var(--sans);line-height:1.6;
  background:linear-gradient(180deg,#eef6ff 0,var(--paper) 560px),var(--paper)}
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background-image:linear-gradient(rgba(36,107,254,.045) 1px,transparent 1px),
    linear-gradient(90deg,rgba(36,107,254,.045) 1px,transparent 1px);
  background-size:36px 36px;mask-image:linear-gradient(180deg,#000 0,transparent 720px)}
a{color:var(--teal);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:4px}
.nav{position:fixed;top:0;left:0;right:0;z-index:30;background:rgba(255,255,255,.82);
  backdrop-filter:blur(18px);border-bottom:1px solid rgba(223,231,240,.7)}
.nav-in{width:min(1180px,calc(100% - 40px));margin:0 auto;min-height:64px;
  display:flex;align-items:center;justify-content:space-between}
.brand{font-family:var(--display);font-size:1.25rem;font-weight:780;color:var(--ink)}
.brand span{color:var(--violet)}
.nav a{color:#40506a;font-family:var(--mono);font-size:.76rem;font-weight:700;margin-left:18px}
.hero{padding:106px 0 10px;text-align:center}
.wrap{width:min(1120px,calc(100% - 40px));margin:0 auto}
.kicker{color:var(--violet);font-family:var(--mono);font-size:.76rem;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;margin:0 0 12px}
h1{margin:0 auto;max-width:900px;font-family:var(--display);
  font-size:clamp(2rem,4vw,2.7rem);line-height:1.1}
.sub{margin:14px auto 0;max-width:720px;color:#354258;font-size:1.02rem}
.stage{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px;margin-top:28px;
  align-items:start}
.canvas{background:#fff;border:1px solid var(--line);border-radius:18px;
  box-shadow:var(--shadow);padding:10px;position:relative}
.canvas svg{display:block;width:100%;height:auto}
.counter{position:absolute;top:16px;left:18px;font-family:var(--mono);font-size:.72rem;
  color:var(--muted);background:#f4f8fc;border:1px solid var(--line);
  border-radius:999px;padding:3px 10px}
.panel{background:#fff;border:1px solid var(--line);border-radius:18px;
  box-shadow:var(--shadow);padding:20px 22px}
.panel h3{margin:0 0 6px;font-size:1rem}
.panel .why{color:#334155;font-size:.86rem;min-height:52px;margin:0 0 12px}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
.metric{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.metric b{display:block;font-family:var(--display);font-size:1.35rem;line-height:1.1}
.metric span{color:var(--muted);font-size:.7rem;font-family:var(--mono)}
.controls{display:flex;gap:8px;margin-top:12px}
.controls button{flex:1;border:1px solid var(--line);background:#fff;border-radius:10px;
  padding:9px;font-family:var(--mono);font-size:.72rem;font-weight:700;cursor:pointer}
.controls button:hover{background:#f4f8fc}
.controls button.primary{background:var(--ink);border-color:var(--ink);color:#fff}
.timeline{margin-top:26px;background:#fff;border:1px solid var(--line);border-radius:18px;
  box-shadow:var(--shadow);padding:8px}
.row{display:grid;grid-template-columns:44px 1fr auto auto;gap:12px;align-items:center;
  padding:9px 12px;border-radius:10px;cursor:pointer;border-bottom:1px dashed #eef2f6}
.row:last-child{border-bottom:none}
.row:hover{background:#f8fafc}
.row.active{background:#f4f0ff;box-shadow:inset 0 0 0 1px rgba(122,72,207,.28)}
.row .n{font-family:var(--mono);font-size:.7rem;color:#8d9aad}
.row .why{font-size:.84rem}
.row .delta{font-family:var(--mono);font-size:.7rem;color:var(--muted);white-space:nowrap}
.row .delta b{color:#067647}
@keyframes pop{{
  from{{transform:scale(.4);opacity:0}}
  60%{{transform:scale(1.12)}}
  to{{transform:scale(1);opacity:1}}
}}
@keyframes dash{{
  from{{stroke-dashoffset:26}}
  to{{stroke-dashoffset:0}}
}}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0 0;font-size:.76rem;
  color:var(--muted);font-family:var(--mono)}
.legend i{display:inline-block;width:22px;height:0;border-top:3px solid;margin-right:6px;
  vertical-align:middle}
.note{background:#fffaf0;border:1px solid #f3d9a8;border-left:5px solid var(--gold);
  border-radius:10px;padding:14px 18px;margin:22px 0;color:#5b4420;font-size:.9rem}
.note b{color:#8a5a00}
@media (max-width:900px){
  .stage{grid-template-columns:1fr}
  .row{grid-template-columns:34px 1fr;row-gap:2px}
  .row .delta{grid-column:2}
}
"""


def build_page(
    journal: list[dict[str, Any]],
    intents: dict[str, str],
    root_label: str,
) -> str:
    frames_data = frames(journal)
    if not frames_data:
        raise SystemExit("journal has no entries; nothing to animate")
    last = frames_data[-1]
    positions = layout(sorted(last["nodes"]), last["edges"])
    radius = 22
    rows = []
    for frame in frames_data:
        delta = []
        if frame["cards_added"]:
            delta.append(f"+{frame['cards_added']} card")
        if frame["cards_updated"]:
            delta.append(f"~{frame['cards_updated']} card")
        if frame["edges_added"]:
            delta.append(f"+{frame['edges_added']} edge")
        rows.append(
            f'<div class="row" data-index="{frame["index"]}">'
            f'<span class="n">{frame["index"] + 1:02d}</span>'
            f'<span class="why">{esc(frame["reason"])}</span>'
            f'<span class="delta"><b>{esc(" ".join(delta) or "no change")}</b></span>'
            f'<span class="delta">{frame["cards_total"]} 节点 / {frame["edges_total"]} 边</span>'
            "</div>"
        )

    payload = {
        "frames": frames_data,
        "positions": positions,
        "radius": radius,
        "colors": TYPE_COLOR,
        "intents": {name: intents.get(name, "") for name in positions},
        "width": 820,
        "height": 470,
    }

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>图是怎么长出来的 — SpecFCG</title>
<style>{CSS}</style></head><body>
<nav class="nav"><div class="nav-in">
  <a class="brand" href="../index.html">Spec<span>FCG</span></a>
  <div><a href="../index.html">主页</a><a href="../index.html#results">效果</a>
    <a href="../demo/">执行演示</a></div>
</div></nav>

<header class="hero"><div class="wrap">
  <p class="kicker">Graph Construction · Replay</p>
  <h1>图不是画出来的，是一条轨迹一条轨迹长出来的</h1>
  <p class="sub">下面每一帧都对应一次真实的 <code>apply_patch</code>：归纳出一张卡片、从轨迹里读出顺序边、
  或让 LLM 补一条语义边。数据来自 <code>{esc(root_label)}/graph/journal.jsonl</code>，未做人工编排。</p>
</div></header>

<div class="wrap">
  <div class="stage">
    <div class="canvas">
      <span class="counter" id="counter">1 / {len(frames_data)}</span>
      <svg id="graph" viewBox="0 0 820 470" role="img" aria-label="Function Contract Graph 构建动画"></svg>
      <div class="legend">
        <span><i style="border-color:{TYPE_COLOR['enables']}"></i>enables</span>
        <span><i style="border-color:{TYPE_COLOR['sequence']}"></i>sequence</span>
        <span><i style="border-color:{TYPE_COLOR['dataflow']}"></i>dataflow</span>
        <span><i style="border-color:#c7d2e0;border-top-style:dashed"></i>虚线 = 本帧新增</span>
      </div>
    </div>
    <div class="panel">
      <h3 id="reason">—</h3>
      <p class="why" id="why">—</p>
      <div class="metrics">
        <div class="metric"><b id="m-cards">0</b><span>卡片节点</span></div>
        <div class="metric"><b id="m-edges">0</b><span>契约边</span></div>
      </div>
      <div class="controls">
        <button id="prev">← 上一步</button>
        <button id="play" class="primary">▶ 播放</button>
        <button id="next">下一步 →</button>
      </div>
    </div>
  </div>

  <div class="timeline" id="timeline">{''.join(rows)}</div>

  <div class="note"><b>怎么读：</b>实线是已经存在的边，虚线是这一帧刚加的边；
  紫色高亮的节点是这一帧新归纳出的卡片。点时间轴任意一行可以跳到那一帧，
  按 ← / → 单步，按空格播放/暂停。</div>
</div>

<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const NS = 'http://www.w3.org/2000/svg';
const svg = document.getElementById('graph');
let current = 0;
let timer = null;

function el(name, attrs) {{
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs || {{}})) node.setAttribute(k, v);
  return node;
}}

function shortName(name) {{
  return name.length > 22 ? name.slice(0, 21) + '…' : name;
}}

function draw(frame) {{
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const positions = DATA.positions;
  const newNode = new Set(frame.new_cards);
  const newEdge = new Set(frame.new_edges.map(e => e.from + '|' + e.to + '|' + e.type));
  const seenEdge = new Set();

  // edges first so nodes sit on top
  for (const edge of frame.edges) {{
    const a = positions[edge.from], b = positions[edge.to];
    if (!a || !b) continue;
    const key = edge.from + '|' + edge.to + '|' + edge.type;
    if (seenEdge.has(key)) continue;
    seenEdge.add(key);
    const fresh = newEdge.has(key);
    const color = DATA.colors[edge.type] || '#94a3b8';
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    // Stop at the node box edge, not at a fixed radius, so arrows touch boxes.
    const padA = Math.abs(dx / len) * 74 + Math.abs(dy / len) * 17 + 5;
    const padB = padA;
    const x1 = a[0] + dx / len * padA, y1 = a[1] + dy / len * padA;
    const x2 = b[0] - dx / len * padB, y2 = b[1] - dy / len * padB;
    const line = el('line', {{
      x1, y1, x2, y2,
      stroke: fresh ? color : color,
      'stroke-width': fresh ? 3.2 : 1.8,
      'stroke-opacity': fresh ? 1 : 0.55,
      'stroke-dasharray': fresh ? '7 5' : '',
    }});
    if (fresh) line.style.animation = 'dash .6s linear';
    svg.appendChild(line);
  }}

  for (const name of frame.nodes) {{
    const p = positions[name];
    if (!p) continue;
    const fresh = newNode.has(name);
    const group = el('g', {{}});
    const labelText = shortName(name);
    const boxW = Math.max(96, labelText.length * 6.6 + 22);
    const box = el('rect', {{
      x: p[0] - boxW / 2, y: p[1] - 16, width: boxW, height: 32, rx: 9,
      fill: fresh ? '#f4f0ff' : '#ffffff',
      stroke: fresh ? '#7a48cf' : '#b9c7d8',
      'stroke-width': fresh ? 2.6 : 1.5,
    }});
    if (fresh) {{
      box.style.transformOrigin = p[0] + 'px ' + p[1] + 'px';
      box.style.animation = 'pop .45s ease-out';
    }}
    group.appendChild(box);
    const label = el('text', {{
      x: p[0], y: p[1] + 4, 'text-anchor': 'middle',
      'font-family': 'JetBrains Mono, Consolas, monospace',
      'font-size': '10.5',
      fill: fresh ? '#5d39b8' : '#334155',
      'font-weight': fresh ? '700' : '500',
    }});
    label.textContent = labelText;
    group.appendChild(label);
    const title = el('title', {{}});
    title.textContent = name + (DATA.intents[name] ? ' — ' + DATA.intents[name] : '');
    group.appendChild(title);
    svg.appendChild(group);
  }}
}}

function show(index) {{
  current = Math.max(0, Math.min(DATA.frames.length - 1, index));
  const frame = DATA.frames[current];
  draw(frame);
  document.getElementById('counter').textContent = (current + 1) + ' / ' + DATA.frames.length;
  document.getElementById('reason').textContent = frame.reason || '（无描述）';
  const parts = [];
  if (frame.cards_added) parts.push('新增 ' + frame.cards_added + ' 张卡片：' + frame.new_cards.join(', '));
  if (frame.cards_updated) parts.push('更新 ' + frame.cards_updated + ' 张卡片');
  if (frame.edges_added) parts.push('新增 ' + frame.edges_added + ' 条边');
  document.getElementById('why').textContent = parts.length ? parts.join('；') + '。' : '这一帧没有改变图结构。';
  document.getElementById('m-cards').textContent = frame.cards_total;
  document.getElementById('m-edges').textContent = frame.edges_total;
  document.querySelectorAll('.row').forEach((row, i) => {{
    row.classList.toggle('active', i === current);
  }});
}}

function stop() {{
  if (timer) {{ clearInterval(timer); timer = null; }}
  document.getElementById('play').textContent = '▶ 播放';
}}

document.getElementById('prev').addEventListener('click', () => {{ stop(); show(current - 1); }});
document.getElementById('next').addEventListener('click', () => {{ stop(); show(current + 1); }});
document.getElementById('play').addEventListener('click', () => {{
  if (timer) {{ stop(); return; }}
  if (current >= DATA.frames.length - 1) show(0);
  document.getElementById('play').textContent = '⏸ 暂停';
  timer = setInterval(() => {{
    if (current >= DATA.frames.length - 1) {{ stop(); return; }}
    show(current + 1);
  }}, 1500);
}});
document.querySelectorAll('.row').forEach((row) => {{
  row.addEventListener('click', () => {{
    stop();
    show(Number(row.dataset.index));
  }});
}});
document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowLeft') {{ stop(); show(current - 1); }}
  if (e.key === 'ArrowRight') {{ stop(); show(current + 1); }}
  if (e.key === ' ') {{ e.preventDefault(); document.getElementById('play').click(); }}
}});
show(0);
</script>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-graph-page")
    parser.add_argument(
        "--root", default=str(ROOT / "runs" / "real" / "demo_graph")
    )
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    root = Path(args.root)
    journal = load_journal(root)
    intents = load_card_intents(root)
    page = build_page(journal, intents, root.name)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(journal)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
