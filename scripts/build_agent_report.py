#!/usr/bin/env python3
"""Build the screenshot-native agent acceptance report from real runs."""

from __future__ import annotations

import base64
import html
import io
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "agent"
OUT = ROOT / "docs" / "reports" / "agentic-report.html"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def badge(ok: bool, good: str = "成功", bad: str = "失败") -> str:
    return f'<span class="badge {"ok" if ok else "bad"}">{good if ok else bad}</span>'


def table(headers: list[str], rows: list[list[Any]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def thumb(path: Path, width: int = 200, quality: int = 70) -> str:
    image = Image.open(path).convert("RGB")
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def message_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in entry.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
    return "\n".join(parts)


def llm_excerpt(entry: dict[str, Any], max_chars: int = 1800) -> str:
    text = message_text(entry)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（截断）"
    calls = entry.get("tool_calls") or []
    if calls:
        text += "\n\n[tool_calls]\n" + json.dumps(calls, ensure_ascii=False, indent=2)
    if entry.get("content"):
        text += "\n\n[response]\n" + str(entry["content"])[:1200]
    return text


def benchmark_order() -> list[str]:
    import yaml

    path = ROOT / "benchmark" / "agent_tasks.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return [str(item["id"]) for item in data.get("tasks", [])]
    except Exception:
        return []


def load_tasks() -> list[dict[str, Any]]:
    order = benchmark_order()
    tasks = []
    for result_path in sorted(RUNS.glob("*/result.json")):
        result = read_json(result_path)
        if not isinstance(result, dict):
            continue
        task_dir = result_path.parent
        steps = read_json(task_dir / "steps.json") or []
        llm = read_jsonl(task_dir / "llm_calls.jsonl")
        tasks.append(
            {
                "result": result,
                "dir": task_dir,
                "steps": steps,
                "llm": llm,
            }
        )
    tasks.sort(
        key=lambda task: (
            order.index(task["result"].get("id"))
            if task["result"].get("id") in order
            else len(order)
        )
    )
    return tasks


def task_section(task: dict[str, Any], index: int) -> str:
    result = task["result"]
    task_dir = task["dir"]
    steps = task["steps"]
    ok = bool(result.get("success"))
    final = task_dir / "final.jpg"
    final_html = (
        f'<figure class="final"><img src="{thumb(final, 360, 78)}" alt="final">'
        f"<figcaption>最终界面（运行实拍）</figcaption></figure>"
        if final.exists()
        else ""
    )
    frames = []
    for step in steps:
        before = task_dir / step.get("before", "")
        if not before.exists() or before.name.startswith("00"):
            continue
        action = step.get("tool", "?")
        args = json.dumps(step.get("args") or {}, ensure_ascii=False)
        caption = f"#{step.get('step')} {action} {args}"
        frames.append(
            '<figure class="frame">'
            f'<img src="{thumb(before)}" alt="{esc(caption)}">'
            f"<figcaption>{esc(caption)}<br><span>{esc(str(step.get('result', ''))[:70])}</span></figcaption>"
            "</figure>"
        )
    film = f'<div class="film">{"".join(frames)}</div>' if frames else "<p>无截图。</p>"
    step_rows = [
        [
            str(step.get("step")),
            f"<code>{esc(step.get('tool'))}</code>",
            f"<code>{esc(json.dumps(step.get('args') or {}, ensure_ascii=False))}</code>",
            esc(str(step.get("thought", ""))[:160]),
            esc(str(step.get("result", ""))[:100]),
        ]
        for step in steps
    ]
    step_table = table(["#", "工具", "参数", "模型这一步的想法", "执行结果"], step_rows)

    planner = next((e for e in task["llm"] if e.get("purpose") == "planner"), None)
    executor = next(
        (e for e in task["llm"] if str(e.get("purpose", "")).startswith("executor")),
        None,
    )
    verifier = next((e for e in task["llm"] if e.get("purpose") == "verifier"), None)
    experience = next((e for e in task["llm"] if e.get("purpose") == "experience"), None)
    io_blocks = []
    for label, entry in (
        ("Planner prompt / response", planner),
        ("Executor observation / tool call", executor),
        ("Verifier response", verifier),
        ("Experience distillation", experience),
    ):
        if entry:
            io_blocks.append(
                f"<h4>{esc(label)}</h4><pre>{esc(llm_excerpt(entry))}</pre>"
            )
    io_html = "".join(io_blocks) or "<p>无模型日志。</p>"
    used_models = sorted(
        {str(entry.get("model")) for entry in task["llm"] if entry.get("model")}
    )
    models_html = ", ".join(used_models) or "无"

    hits = read_json(task_dir / "memory.json") or []
    if hits:
        memory_html = "<ul>" + "".join(
            f"<li><strong>{esc(hit.get('goal'))}</strong> — {esc(str(hit.get('lessons'))[:300])}</li>"
            for hit in hits[:3]
        ) + "</ul>"
    else:
        memory_html = "<p class=\"muted\">本次没有检索到历史经验（首个任务时为空）。</p>"

    return f"""
<section class="task">
  <div class="task-head">
    <h2>{index}. <code>{esc(result.get('id'))}</code> {badge(ok)}</h2>
    <div class="metrics">
      <span>App: {esc(result.get('app_name'))}</span>
      <span>Steps: {result.get('steps')}</span>
      <span>Verifier: {result.get('verifier_success')}</span>
      <span>Text check: {result.get('deterministic_ok')}</span>
      <span>LLM calls: {result.get('llm_calls')}</span>
      <span>实际模型: {esc(models_html)}</span>
      <span>LLM time: {result.get('llm_seconds')}s</span>
      <span>Wall: {result.get('elapsed_s')}s</span>
    </div>
  </div>
  <p><strong>目标：</strong>{esc(result.get('goal'))}</p>
  <p><strong>模型计划：</strong></p>
  <pre>{esc(result.get('plan'))}</pre>
  <p><strong>最终判定：</strong>{esc(result.get('reason'))}</p>
  <p><strong>注入的历史经验：</strong></p>
  {memory_html}
  <div class="final-wrap">{final_html}</div>
  <h3>每一步的真实截图与动作</h3>
  {film}
  <details open><summary>逐步动作与模型工具调用</summary>{step_table}</details>
  <details><summary>查看该任务的模型请求 / 输出（抽样）</summary>{io_html}</details>
</section>
"""


def main() -> int:
    tasks = load_tasks()
    if not tasks:
        print("no agent results found")
        return 1
    successes = sum(1 for task in tasks if task["result"].get("success"))
    total_steps = sum(task["result"].get("steps", 0) for task in tasks)
    total_calls = sum(task["result"].get("llm_calls", 0) for task in tasks)
    total_wall = sum(task["result"].get("elapsed_s", 0) for task in tasks)

    rows = []
    for task in tasks:
        result = task["result"]
        rows.append(
            [
                f"<code>{esc(result.get('id'))}</code>",
                esc(result.get("app_name")),
                badge(bool(result.get("success"))),
                str(result.get("steps")),
                str(result.get("llm_calls")),
                f"{result.get('llm_seconds')}s",
                f"{result.get('elapsed_s')}s",
                esc(str(result.get("reason"))[:110]),
            ]
        )
    result_table = table(
        ["任务", "App", "结果", "步数", "LLM 调用", "模型耗时", "总耗时", "判定理由"],
        rows,
        "results",
    )

    related = table(
        ["工作", "年份/venue", "输入模态", "与本题相关点"],
        [
            ["ProphetAgent", "FSE 2025", "UI 页面信息 + 事件区域截图 → GPT-4o", "CUTG + 自然语言测试用例；文本+视觉混合"],
            ["FuncDroid", "ISSTA 2026", "FFG + MLLM + 实时截图恢复", "功能间 flow；截图用于执行与 oracle"],
            ["ScenGen", "2025/2026", "截图 + CV/OCR + 多模态 LLM", "Observer/Supervisor；每步记录截图路径"],
            ["DroidAgent", "2023/2024", "widget/UI 表示 + 长短期记忆", "偏文本；没有强调视觉"],
            ["Agent-S", "开源 CUA", "截图 + accessibility tree", "Planner/Executor/Reflection + 记忆"],
            ["ASPEC", "ICLR 2026", "agent 架构 + 持久反思记忆", "specialist + 状态化经验积累"],
        ],
        "related",
    )

    memory_path = RUNS / "experience.jsonl"
    memory_entries = read_jsonl(memory_path)
    memory_html = (
        "<pre>"
        + esc(
            "\n\n".join(
                f"[{'success' if e.get('success') else 'failure'}] {e.get('goal')}\n{e.get('lessons')}"
                for e in memory_entries[-6:]
            )
        )
        + "</pre>"
        if memory_entries
        else "<p>尚无经验条目。</p>"
    )

    comparison = table(
        ["四卡任务：create → search → open → share", "旧 FCG 方案", "新截图 Agent"],
        [
            ["设计结构", "功能卡 + 图 + 绑定器 + 编译器 + postcondition", "Planner + ReAct 工具循环 + Verifier + 经验记忆"],
            ["动作/步数", "11 个编译动作", "真实运行步数见任务表"],
            ["LLM 调用", "11", "见任务表"],
            ["规划+执行耗时", "688.8s + 105.7s", "见任务表"],
            ["截图证据", "脚本复现", "每一步真实截图"],
        ],
        "compare",
    )

    generated = time.strftime("%Y-%m-%d %H:%M")
    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>截图原生 GUI Agent 真机验收报告</title>
<style>
:root {{ --ink:#17212b; --muted:#667085; --line:#e4e7ec; --bg:#f6f8fb; --card:#fff;
  --ok:#067647; --okbg:#ecfdf3; --bad:#b42318; --badbg:#fef3f2; --accent:#1d4ed8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:30px 26px 70px; }}
header.hero {{ background:linear-gradient(135deg,#0f172a,#1e3a8a); color:#fff;
  padding:36px 32px; border-radius:16px; margin-bottom:22px; }}
header.hero h1 {{ margin:0 0 8px; font-size:29px; }}
header.hero p {{ margin:4px 0; opacity:.88; }}
.meta {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:14px; }}
.meta span {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.18);
  padding:3px 10px; border-radius:999px; font-size:12.5px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:24px 26px; margin:18px 0; }}
h2 {{ margin:0 0 12px; font-size:20px; }}
h3 {{ margin:22px 0 8px; font-size:16px; }}
h4 {{ margin:16px 0 6px; font-size:14px; color:#344054; }}
code {{ background:#f1f5f9; padding:1px 5px; border-radius:5px;
  font:13px/1.5 "Cascadia Code",Consolas,monospace; }}
pre {{ background:#0b1220; color:#dbeafe; padding:14px; border-radius:10px;
  white-space:pre-wrap; word-break:break-word;
  font:12px/1.55 "Cascadia Code",Consolas,monospace; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:13px; }}
th,td {{ border-bottom:1px solid var(--line); padding:8px 7px; text-align:left; vertical-align:top; }}
th {{ background:#f8fafc; color:#475467; font-size:12.5px; white-space:nowrap; }}
.badge {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }}
.badge.ok {{ color:var(--ok); background:var(--okbg); }}
.badge.bad {{ color:var(--bad); background:var(--badbg); }}
.kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
.kv div {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:10px 12px; }}
.kv b {{ display:block; font-size:20px; }}
.task-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:14px; flex-wrap:wrap; }}
.metrics {{ display:flex; gap:10px; flex-wrap:wrap; color:var(--muted); font-size:12.5px; }}
.metrics span {{ background:#f8fafc; border:1px solid var(--line); padding:3px 9px; border-radius:999px; }}
.final-wrap {{ display:flex; justify-content:center; margin:14px 0; }}
figure.final {{ margin:0; border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
figure.final img {{ display:block; width:360px; max-width:100%; }}
figure.final figcaption {{ padding:6px 9px; font-size:12px; color:var(--muted); }}
.film {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; margin:10px 0; }}
figure.frame {{ margin:0; border:1px solid var(--line); border-radius:9px; overflow:hidden; background:#fff; }}
figure.frame img {{ display:block; width:100%; height:auto; }}
figure.frame figcaption {{ padding:6px 8px; font-size:11.5px; color:var(--ink); }}
figure.frame figcaption span {{ color:var(--muted); }}
details {{ margin:12px 0; }}
summary {{ cursor:pointer; color:var(--accent); font-size:13.5px; }}
footer {{ color:var(--muted); font-size:12px; text-align:center; margin-top:24px; }}
</style></head><body><main>
<header class="hero">
  <h1>截图原生 GUI Agent 真机验收报告</h1>
  <p>Planner → Executor → Verifier → 经验记忆：不再使用 function card / FCG / 手工 JSON schema。</p>
  <div class="meta">
    <span>日期 {generated}</span><span>Pixel 9 Pro XL · Android 16</span>
    <span>模型 auto/gpt-6-luna</span><span>magpie 127.0.0.1:3425</span>
    <span>完成任务 {successes}/{len(tasks)}</span>
  </div>
</header>

<section>
  <h2>结论</h2>
  <p>这一版把方法缩成“看截图 → 选一个工具 → 执行 → 再截图”，加上 Planner、Verifier 和
  跨任务经验记忆。任务从 4 个扩到 {len(tasks)} 个，包含多笔记、搜索、编辑、置顶、删除、
  归档、标签、分享、第二个 app（Activity Diary）和第三个 app（Tasks.org）。</p>
  <div class="kv">
    <div><span class="muted">任务成功</span><b>{successes}/{len(tasks)}</b></div>
    <div><span class="muted">总步数</span><b>{total_steps}</b></div>
    <div><span class="muted">LLM 调用</span><b>{total_calls}</b></div>
    <div><span class="muted">总墙钟</span><b>{int(total_wall)}s</b></div>
    <div><span class="muted">经验条目</span><b>{len(memory_entries)}</b></div>
  </div>
  <p class="muted">每一步的截图都来自真实运行（<code>runs/agent/&lt;task&gt;/step_*.jpg</code>），
  不是脚本复现；这一点直接回应“脚本没法保证下次完整执行”的问题。</p>
</section>

<section>
  <h2>对比方法到底用不用截图？</h2>
  {related}
  <p class="muted">结论：最近的相关工作大多已经使用截图/多模态；只有 DroidAgent 偏 widget/文本。
  我们之前纯文本 UI 树的做法确实落后，这一版改成截图优先，UI 元素列表只用于精确定位。</p>
</section>

<section>
  <h2>简化后的架构</h2>
  <div class="kv">
    <div><b>① Planner</b><span class="muted">看首屏 + 目标，写 3–6 条自然语言计划</span></div>
    <div><b>② Executor</b><span class="muted">每步截图 + 控件列表 → 一个 tool call</span></div>
    <div><b>③ Verifier</b><span class="muted">终屏截图 + 期望文本 → 成功/失败与理由</span></div>
    <div><b>④ Reflector</b><span class="muted">每 6 步检查进度，卡住则重规划</span></div>
    <div><b>⑤ Memory</b><span class="muted">任务后写经验，下次相似任务检索注入</span></div>
  </div>
  <p>没有 function card、没有图、没有绑定器/编译器、没有逐卡 postcondition。
  工具只有 tap / tap_xy / type_text / press / swipe / wait / done；每一步的模型输出就是一个
  标准 tool call，不需要自定义 JSON 结构。</p>
  <p><strong>成功判定：</strong>最终截图交给 Verifier 判断，同时要求最终 UI 文本里出现
  <code>expect_text</code>、不出现 <code>expect_absent</code>；两者都通过才算成功。
  这比单纯让模型自评更严格，但隐藏状态（例如“已归档”本身）仍只能从终屏推断。</p>
  <p class="muted">思想来源：Agent-S 的 planner/executor/reflection + 截图 ACI；
  ScenGen 的 Observer/Supervisor 与截图记录；ASPEC 的 specialist + 持久反思记忆。</p>
</section>

<section>
  <h2>任务结果</h2>
  {result_table}
</section>

{''.join(task_section(task, i) for i, task in enumerate(tasks, 1))}

<section>
  <h2>经验记忆（RSI-lite）</h2>
  <p>每个任务结束后，模型把可复用的做法写成自然语言经验；下一个相似任务开始时按关键词检索注入。
  没有向量数据库，也没有新的 schema。</p>
  {memory_html}
</section>

<section>
  <h2>与旧方案的直接对比</h2>
  {comparison}
  <p class="muted">旧方案的四卡任务结果来自 <code>runs/real/pilot_complex_flow.jsonl</code>；
  新方案的任务结果见上表。两条链路都在同一台真机上完成。</p>
</section>

<section>
  <h2>局限</h2>
  <ul>
    <li>任务数仍只有 {len(tasks)} 个，且主要是 OmniNotes；这是 idea validation，不是完整 benchmark。</li>
    <li>还没有与 ProphetAgent / FuncDroid / ScenGen 在相同任务集上做对照实验。</li>
    <li>模型是 <code>auto/gpt-6-luna</code>；换模型会改变步数与稳定性，需要复测。</li>
    <li>经验记忆只用关键词检索；任务规模变大后需要更好的检索与去重。</li>
    <li>Tasks.org 的界面是中文且首次启动有 onboarding，长程任务更容易受 UI 变化影响。</li>
    <li>截图会包含系统通知等无关信息；当前不影响判断，但正式评测应做隐私/噪声处理。</li>
  </ul>
</section>

<section>
  <h2>复现</h2>
<pre># 跑全部任务
python scripts/run_agent_tasks.py \\
  --tasks benchmark/agent_tasks.yaml \\
  --out runs/agent \\
  --memory runs/agent/experience.jsonl

# 只跑一个任务
python scripts/run_agent_tasks.py --only omni_four_card_share

# 重新生成报告
python scripts/build_agent_report.py</pre>
  <p class="muted">证据目录：<code>runs/agent/&lt;task&gt;/</code>（result.json、steps.json、
  llm_calls.jsonl、step_*.jpg、final.jpg）。</p>
</section>
<footer>截图原生 GUI Agent · 真机验收报告 · 由 scripts/build_agent_report.py 生成</footer>
</main></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
