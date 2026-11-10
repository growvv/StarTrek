#!/usr/bin/env python3
"""Render the FCG construction journal as an animated graph page.

Input: `graph/journal.jsonl` written by GraphStore.apply_patch, plus the cards
it references. Output: `docs/graph/index.html` — a self-contained page that
replays every patch in order, adding nodes and edges as they actually appeared.

Layout is deterministic (no external JS): each card gets a column from its
longest-path depth over the execution edges, the columns wrap into bands, and
the box sizes come from the card names. The same journal therefore always
renders the same picture, and the page works offline.
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
) -> tuple[dict[str, tuple[float, float]], int, int]:
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

    # Boxes are sized to their label, so the canvas has to be sized to the
    # boxes: a fixed width overlaps once a column holds a long card name.
    widest = max((box_width(name) for name in names), default=120.0)
    margin_x = 30
    margin_y = 34
    col_gap = widest + 52
    row_gap = 62
    band_gap = 34

    # One column per depth is unreadable once a graph is a long chain: eight
    # cards become a 1400px strip that shrinks to 7px text when fitted to the
    # page. Wrap the columns into bands instead, reversing every other band so
    # consecutive depths stay adjacent and the chain reads like text on a page.
    per_band = max(2, min(4, math.ceil(math.sqrt(max(1, col_count)) * 1.6)))
    bands = [
        list(range(start, min(start + per_band, col_count)))
        for start in range(0, col_count, per_band)
    ]
    band_heights = [
        max(
            [len(columns.get(col, [])) for col in band] + [1]
        )
        for band in bands
    ]
    width = int(
        max(
            560,
            2 * margin_x + (per_band - 1) * col_gap + widest,
        )
    )
    height = int(
        max(
            190,
            sum(2 * margin_y + (n - 1) * row_gap + BOX_H for n in band_heights)
            + (len(bands) - 1) * band_gap,
        )
    )
    height += 18  # breathing room between the last band and the legend

    positions: dict[str, tuple[float, float]] = {}
    column_of: dict[str, int] = {}
    band_top = margin_y
    for band_index, band in enumerate(bands):
        band_height = 2 * margin_y + (band_heights[band_index] - 1) * row_gap + BOX_H
        ordered = band if band_index % 2 == 0 else list(reversed(band))
        for slot, col in enumerate(ordered):
            members = columns.get(col, [])
            x = margin_x + widest / 2 + slot * col_gap
            block = (len(members) - 1) * row_gap
            top = band_top + (band_height - block) / 2
            for row, name in enumerate(members):
                positions[name] = (round(x, 1), round(top + row * row_gap, 1))
                column_of[name] = col
        band_top += band_height + band_gap
    return positions, column_of, width, height


BOX_FONT = 13.0
CHAR_W = 7.8
BOX_H = 34.0
BOX_MIN_W = 96.0


def box_width(name: str) -> float:
    lines = wrap_name(name)
    return max(BOX_MIN_W, max(len(line) for line in lines) * CHAR_W + 24)


def box_height(name: str) -> float:
    return BOX_H if len(wrap_name(name)) == 1 else BOX_H + 15


def wrap_name(name: str) -> list[str]:
    """Split a card name into at most two lines, on underscore boundaries.

    Truncating `search_notes_by_keyword` to `search_notes_by_k…` loses the part
    that identifies the card. Wrapping keeps every word and makes the box
    narrower, which matters because the graph is laid out left to right.
    """
    parts = name.split("_")
    if len(parts) == 1:
        return [name]
    best: tuple[int, list[str]] | None = None
    for cut in range(1, len(parts)):
        lines = ["_".join(parts[:cut]), "_".join(parts[cut:])]
        width = max(len(line) for line in lines)
        if best is None or width < best[0]:
            best = (width, lines)
    assert best is not None
    if best[0] > 22:  # still too wide: fall back to one clipped line
        return [name if len(name) <= 26 else name[:25] + "…"]
    return best[1]


def composable_paths(
    nodes: list[str], edges: list[dict[str, Any]], max_depth: int = 4
) -> int:
    """Count distinct multi-card execution paths available in this frame.

    This is the metric that makes graph growth meaningful: one card can only
    do one thing, but two cards plus an execution edge is a *new* test the
    graph can plan without any new exploration. Counts simple paths of length
    2..max_depth over enables/sequence edges, which is exactly what the planner
    walks (`graph/search.py` treats those as the executable transitions).
    """
    execution = {"enables", "sequence"}
    adjacency: dict[str, set[str]] = {name: set() for name in nodes}
    for edge in edges:
        if edge.get("type") not in execution:
            continue
        src, dst = edge.get("from"), edge.get("to")
        if src in adjacency and dst in adjacency and src != dst:
            adjacency[src].add(dst)

    total = 0

    def walk(node: str, path: list[str]) -> None:
        nonlocal total
        if len(path) >= 2:
            total += 1
        if len(path) >= max_depth:
            return
        for nxt in adjacency[node]:
            if nxt in path:
                continue
            walk(nxt, path + [nxt])

    for name in nodes:
        walk(name, [name])
    return total


def explain(reason: str) -> tuple[str, str]:
    """Turn a journal reason into (Chinese title, what the pipeline did).

    The journal stores the reason the pipeline passed to `apply_patch`, which is
    precise but machine-shaped. The page shows a human sentence plus the raw
    reason underneath, so a reader can follow the construction without knowing
    the codebase.
    """
    if reason.startswith("mined trace "):
        body = reason[len("mined trace "):]
        trace_id, _, names = body.partition(" -> ")
        if names.strip() and names.strip() != "no new card":
            return (
                f"探索一条新轨迹：{trace_id}",
                f"回放真实操作，LLM 把它归纳成卡片 {names}。"
                "轨迹里观察到的先后顺序同时变成 sequence 边。",
            )
        return (
            f"再探索一条轨迹：{trace_id}",
            "这条轨迹没有带来新功能，但它和已有卡片之间的顺序关系仍被记录下来。",
        )
    if reason.startswith("semantic edges over "):
        words = reason[len("semantic edges over "):].split()
        number = words[0] if words else "?"
        return (
            "LLM 在已有卡片之间推断语义边",
            f"把当前全部 {number} 张卡片交给模型，判断哪些卡片彼此 enable"
            "（前置条件被满足）、哪些卡片之间传递数据（dataflow）。"
            "这是图从“一条条轨迹”变成“可规划结构”的一步。",
        )
    return (reason or "（无描述）", "")


def example_paths(
    nodes: list[str],
    edges: list[dict[str, Any]],
    max_depth: int = 3,
    limit: int = 5,
) -> list[list[str]]:
    """The first few multi-card paths, as concrete sequences of card names.

    A count is abstract; a path is a test case. Showing `create_note →
    open_note_by_title → archive_note` is what proves the graph can compose
    behaviour nobody explored end to end.
    """
    execution = {"enables", "sequence"}
    adjacency: dict[str, set[str]] = {name: set() for name in nodes}
    for edge in edges:
        if edge.get("type") not in execution:
            continue
        src, dst = edge.get("from"), edge.get("to")
        if src in adjacency and dst in adjacency and src != dst:
            adjacency[src].add(dst)

    found: list[list[str]] = []

    def walk(node: str, path: list[str]) -> bool:
        if len(path) >= 2:
            found.append(list(path))
            if len(found) >= limit:
                return True
        if len(path) >= max_depth:
            return False
        for nxt in sorted(adjacency[node]):
            if nxt in path:
                continue
            if walk(nxt, path + [nxt]):
                return True
        return False

    for name in nodes:
        if walk(name, [name]):
            break
    return found


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
        frame_edges = [
            {"from": e["from"], "to": e["to"], "type": e["type"]}
            for e in edges
        ]
        result.append(
            {
                "index": index,
                "paths": composable_paths(list(order), frame_edges),
                "examples": example_paths(list(order), frame_edges),
                "reason": entry.get("reason", ""),
                "label": explain(entry.get("reason", ""))[0],
                "detail": explain(entry.get("reason", ""))[1],
                "ts": entry.get("ts", ""),
                "cards_added": entry.get("cards_added", 0),
                "cards_updated": entry.get("cards_updated", 0),
                "edges_added": entry.get("edges_added", 0),
                "cards_total": entry.get("cards_total", 0),
                "edges_total": entry.get("edges_total", 0),
                "nodes": list(order),
                "edges": frame_edges,
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
h1{margin:0 auto;max-width:1000px;font-family:var(--display);
  font-size:clamp(1.9rem,3.6vw,2.6rem);line-height:1.14;text-wrap:balance}
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
.panel .why{color:#334155;font-size:.85rem;min-height:104px;margin:0 0 12px;
  overflow-wrap:anywhere}
html,body{max-width:100%;overflow-x:hidden}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
.metric{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.metric b{display:block;font-family:var(--display);font-size:1.35rem;line-height:1.1}
.metric span{color:var(--muted);font-size:.7rem;font-family:var(--mono)}
.paths{margin:0 0 4px;border-top:1px dashed #eef2f6;padding-top:10px}
.paths h4{margin:0 0 6px;font-size:.72rem;font-family:var(--mono);color:var(--muted);
  text-transform:uppercase;letter-spacing:.06em}
.paths ul{margin:0;padding:0;list-style:none;display:grid;gap:5px}
.paths li{font-family:var(--mono);font-size:.7rem;color:#334155;background:#f8fafc;
  border:1px solid var(--line);border-radius:7px;padding:5px 7px;overflow-wrap:anywhere}
.paths li b{color:var(--violet);font-weight:600}
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
.legend .toggle{display:inline-flex;align-items:center;cursor:pointer;user-select:none}
.legend .toggle input{margin:0 6px 0 0;accent-color:var(--violet)}
.note{background:#fffaf0;border:1px solid #f3d9a8;border-left:5px solid var(--gold);
  border-radius:10px;padding:14px 18px;margin:22px 0;color:#5b4420;font-size:.9rem}
.note b{color:#8a5a00}
.grid-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin-top:22px}
.grid-two > *{min-width:0}
@media (max-width:900px){
  .stage{grid-template-columns:minmax(0,1fr)}
  .grid-two{grid-template-columns:minmax(0,1fr)}
  .row{grid-template-columns:34px minmax(0,1fr);row-gap:2px}
  .row .delta{grid-column:2}
  .nav a{margin-left:12px}
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
    positions, column_of, width, height = layout(
        sorted(last["nodes"]), last["edges"]
    )
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
            f'<span class="why">{esc(frame["label"])}'
            f'<br><span style="color:#8d9aad;font-size:.74rem;font-family:var(--mono)">'
            f'{esc(frame["reason"])}</span></span>'
            f'<span class="delta"><b>{esc(" ".join(delta) or "no change")}</b></span>'
            f'<span class="delta">{frame["cards_total"]} 节点 / {frame["edges_total"]} 边'
            f' / {frame["paths"]} 路径</span>'
            "</div>"
        )

    payload = {
        "frames": frames_data,
        "positions": positions,
        "colors": TYPE_COLOR,
        "intents": {name: intents.get(name, "") for name in positions},
        "labels": {name: wrap_name(name) for name in positions},
        "boxFont": BOX_FONT,
        "columns": column_of,
        "sizes": {
            name: [round(box_width(name), 1), round(box_height(name), 1)]
            for name in positions
        },
        "width": width,
        "height": height,
    }

    final = frames_data[-1]
    trace_count = sum(
        1 for f in frames_data if f["reason"].startswith("mined trace")
    )
    card_count = final["cards_total"]
    edge_count = final["edges_total"]
    path_count = final["paths"]

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
      <svg id="graph" viewBox="0 0 {width} {height}" role="img" aria-label="Function Contract Graph 构建动画"></svg>
      <div class="legend">
        <span><i style="border-color:{TYPE_COLOR['enables']}"></i>enables</span>
        <span><i style="border-color:{TYPE_COLOR['sequence']}"></i>sequence</span>
        <label class="toggle"><input type="checkbox" id="show-dataflow">
          <i style="border-color:{TYPE_COLOR['dataflow']}"></i>dataflow（参数供给）</label>
        <span><i style="border-color:#c7d2e0;border-top-style:dashed"></i>虚线 = 本帧新增</span>
      </div>
    </div>
    <div class="panel">
      <h3 id="reason">—</h3>
      <p class="why" id="why">—</p>
      <div class="metrics">
        <div class="metric"><b id="m-cards">0</b><span>卡片节点</span></div>
        <div class="metric"><b id="m-edges">0</b><span>契约边</span></div>
        <div class="metric" style="grid-column:1/-1">
          <b id="m-paths">0</b><span>可规划的多卡路径（2 卡以上，最多 4 卡）</span></div>
      </div>
      <div class="paths">
        <h4 id="paths-head">此刻能直接组合出的路径</h4>
        <ul id="paths-list"></ul>
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

  <div class="grid-two">
    <div class="panel">
      <h3>这个图现在是完整的吗？</h3>
      <p class="why" style="min-height:0">不是。这一轮用 {trace_count} 条真实轨迹把 OmniNotes
      的 {card_count} 个功能长成了 {edge_count} 条契约边、{path_count} 条可组合路径，
      覆盖了“建笔记 → 打开 / 搜索 / 排序 → 分享 / 归档 / 固定 / 待办 / 删除”这条主线。
      完整不是一次采完的，而是靠三件事持续推进：</p>
      <ul style="margin:8px 0 0;padding-left:18px;font-size:.85rem;color:#334155">
        <li><b>再探索一条轨迹</b>：新功能变成新卡片，新顺序变成 sequence 边——就是上面这个动画。</li>
        <li><b>失败驱动修补</b>：执行失败时按失败类型回写卡片的前后条件或边的类型，图越跑越准。</li>
        <li><b>能力补全</b>：目标在图上不可达时，让模型提出缺失能力的探针轨迹，采回来补进图。</li>
      </ul>
    </div>
    <div class="panel">
      <h3>为什么这个图能拿来卖</h3>
      <p class="why" style="min-height:0">单张卡片只能做一件事，测试能力是<b>组合</b>出来的。
      每加一条 enables 边，可规划的测试数量就不是 +1，而是把已有的路径和新的前置条件接起来。
      这就是上面那个“可规划的多卡路径”数字从 0 涨到 {path_count} 的原因——
      这些路径里没有一条是被完整录过的，它们是从图里推出来的。</p>
      <p class="why" style="min-height:0;margin-bottom:0">同一份图可以直接给规划器用：
      <code>planner</code> 在 enables / sequence 上搜索，<code>dataflow</code> 只负责给参数，
      所以“数据上能接、UI 上进不去”的假路径不会被选中。</p>
    </div>
  </div>
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

function boxPad(from, to, name) {{
  const size = DATA.sizes[name] || [96, 30];
  const dx = Math.abs(to[0] - from[0]), dy = Math.abs(to[1] - from[1]);
  const len = Math.hypot(dx, dy) || 1;
  const halfW = size[0] / 2 + 4, halfH = size[1] / 2 + 4;
  const px = dx < 1e-6 ? Infinity : halfW * len / dx;
  const py = dy < 1e-6 ? Infinity : halfH * len / dy;
  return Math.min(px, py);
}}

function draw(frame) {{
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Arrowheads are per edge type so a fresh edge reads as a direction, not a line.
  const defs = el('defs', {{}});
  for (const [type, color] of Object.entries(DATA.colors)) {{
    const marker = el('marker', {{
      id: 'arrow-' + type, viewBox: '0 0 10 10', refX: '9', refY: '5',
      markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse',
    }});
    marker.appendChild(el('path', {{
      d: 'M 0 0 L 10 5 L 0 10 z', fill: color,
    }}));
    defs.appendChild(marker);
  }}
  const dots = el('pattern', {{
    id: 'dots', width: '18', height: '18', patternUnits: 'userSpaceOnUse',
  }});
  dots.appendChild(el('circle', {{
    cx: '1.4', cy: '1.4', r: '1.1', fill: '#dbe6f3',
  }}));
  defs.appendChild(dots);
  svg.appendChild(defs);
  svg.appendChild(el('rect', {{
    x: 0, y: 0, width: DATA.width, height: DATA.height,
    fill: 'url(#dots)', rx: 10,
  }}));

  const positions = DATA.positions;
  const showDataflow = document.getElementById('show-dataflow').checked;
  const visible = frame.edges.filter(
    e => showDataflow || e.type !== 'dataflow'
  );
  const newNode = new Set(frame.new_cards);
  const newEdge = new Set(frame.new_edges.map(e => e.from + '|' + e.to + '|' + e.type));
  const seenEdge = new Set();

  // Group by unordered pair so parallel edges (enables + dataflow between the
  // same two cards) can be curved apart instead of drawn on top of each other.
  const pairIndex = new Map();
  const pairCount = new Map();
  for (const edge of visible) {{
    const key = [edge.from, edge.to].sort().join('|') + '|' + edge.type;
    if (seenEdge.has(key)) continue;
    seenEdge.add(key);
    const pair = [edge.from, edge.to].sort().join('|');
    pairCount.set(pair, (pairCount.get(pair) || 0) + 1);
  }}
  seenEdge.clear();

  // edges first so nodes sit on top
  for (const edge of visible) {{
    const a = positions[edge.from], b = positions[edge.to];
    if (!a || !b) continue;
    const key = edge.from + '|' + edge.to + '|' + edge.type;
    if (seenEdge.has(key)) continue;
    seenEdge.add(key);
    const pair = [edge.from, edge.to].sort().join('|');
    const slot = pairIndex.get(pair) || 0;
    pairIndex.set(pair, slot + 1);
    const total = pairCount.get(pair) || 1;
    const spread = total === 1 ? 0 : (slot - (total - 1) / 2) * 26;
    const span = Math.abs((DATA.columns[edge.to] || 0) - (DATA.columns[edge.from] || 0));
    // A skip edge (span > 1) would otherwise run straight through the boxes in
    // between; push it out so the long-range relationship stays readable.
    const bend = spread + (span > 1 ? (span - 1) * 34 * (slot % 2 ? -1 : 1) : 0);

    const fresh = newEdge.has(key);
    const color = DATA.colors[edge.type] || '#94a3b8';
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    // Stop at each node's own box edge (the boxes differ in width), so the
    // arrow touches the border instead of floating inside or crossing it.
    const padA = boxPad(a, b, edge.from);
    const padB = boxPad(b, a, edge.to);
    const x1 = a[0] + dx / len * padA, y1 = a[1] + dy / len * padA;
    const x2 = b[0] - dx / len * padB, y2 = b[1] - dy / len * padB;
    const mx = (x1 + x2) / 2 - dy / len * bend;
    const my = (y1 + y2) / 2 + dx / len * bend;
    const line = el('path', {{
      d: 'M ' + x1 + ' ' + y1 + ' Q ' + mx + ' ' + my + ' ' + x2 + ' ' + y2,
      fill: 'none',
      stroke: color,
      'stroke-width': fresh ? 3 : 1.6,
      'stroke-opacity': fresh ? 1 : 0.5,
      'stroke-dasharray': fresh ? '7 5' : '',
      'marker-end': 'url(#arrow-' + edge.type + ')',
    }});
    if (fresh) line.style.animation = 'dash .6s linear';
    svg.appendChild(line);
  }}

  for (const name of frame.nodes) {{
    const p = positions[name];
    if (!p) continue;
    const fresh = newNode.has(name);
    const group = el('g', {{}});
    const lines = DATA.labels[name] || [name];
    const size = DATA.sizes[name] || [96, 30];
    const box = el('rect', {{
      x: p[0] - size[0] / 2, y: p[1] - size[1] / 2,
      width: size[0], height: size[1], rx: 8,
      fill: fresh ? '#f4f0ff' : '#ffffff',
      stroke: fresh ? '#7a48cf' : '#b9c7d8',
      'stroke-width': fresh ? 2.6 : 1.5,
    }});
    if (fresh) {{
      box.style.transformOrigin = p[0] + 'px ' + p[1] + 'px';
      box.style.animation = 'pop .45s ease-out';
    }}
    group.appendChild(box);
    const lineH = 15;
    const top = p[1] - ((lines.length - 1) * lineH) / 2 + 4;
    lines.forEach((text, i) => {{
      const label = el('text', {{
        x: p[0], y: top + i * lineH, 'text-anchor': 'middle',
        'font-family': 'JetBrains Mono, Consolas, monospace',
        'font-size': String(DATA.boxFont),
        fill: fresh ? '#5d39b8' : '#334155',
        'font-weight': fresh ? '700' : '500',
      }});
      label.textContent = text;
      group.appendChild(label);
    }});
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
  document.getElementById('reason').textContent = frame.label || frame.reason || '（无描述）';
  const parts = [];
  if (frame.detail) parts.push(frame.detail.replace(/。$/, ''));
  if (frame.cards_added) parts.push('本帧 +' + frame.cards_added + ' 卡片（' + frame.new_cards.join(', ') + '）');
  if (frame.cards_updated) parts.push('更新 ' + frame.cards_updated + ' 张卡片');
  if (frame.edges_added) parts.push('本帧 +' + frame.edges_added + ' 条边');
  if (frame.paths) parts.push('此刻图上可规划 ' + frame.paths + ' 条多卡路径');
  document.getElementById('why').textContent = parts.length ? parts.join('；') + '。' : '这一帧没有改变图结构。';
  document.getElementById('m-cards').textContent = frame.cards_total;
  document.getElementById('m-edges').textContent = frame.edges_total;
  document.getElementById('m-paths').textContent = frame.paths || 0;
  const list = document.getElementById('paths-list');
  while (list.firstChild) list.removeChild(list.firstChild);
  const examples = (frame.examples || []).slice(0, 4);
  document.getElementById('paths-head').textContent =
    '此刻能直接组合出的路径（共 ' + (frame.paths || 0) + ' 条）';
  if (!examples.length) {{
    const li = document.createElement('li');
    li.textContent = '还没有可组合的路径：单张卡片只能做一件事。';
    list.appendChild(li);
  }} else {{
    for (const path of examples) {{
      const li = document.createElement('li');
      path.forEach((name, i) => {{
        if (i) {{
          const arrow = document.createElement('span');
          arrow.textContent = ' → ';
          li.appendChild(arrow);
        }}
        const b = document.createElement('b');
        b.textContent = name;
        li.appendChild(b);
      }});
      list.appendChild(li);
    }}
  }}
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
document.getElementById('show-dataflow').addEventListener('change', () => {{
  draw(DATA.frames[current]);
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
// A `#frame=N` hash lets a link (or a headless screenshot) open on one frame.
const start = Number((location.hash.match(/frame=([0-9]+)/) || [])[1]);
show(Number.isFinite(start) && start > 0 ? start - 1 : 0);
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
