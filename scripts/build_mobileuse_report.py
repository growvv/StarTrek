#!/usr/bin/env python3
"""Build a self-contained HTML acceptance report for the mobile-use baseline.

Reads only real run artifacts under runs/mobileuse/ plus the completed AppAgent
comparison run.  Every screenshot embedded in the report is a real device
frame from the agent's trace (or the final capture), not a scripted recreation.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mobile_agent import prompts  # noqa: E402

RUNS = ROOT / "runs" / "mobileuse"
APPAGENT = ROOT / "runs" / "appagent"
OUT = ROOT / "docs" / "reports" / "mobileuse-report.html"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def b64_image(path: Path, width: int = 420, quality: int = 72) -> str:
    if not path.exists():
        return ""
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.width > width:
                height = round(image.height * width / image.width)
                image = image.resize((width, height), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return ""


def img_tag(path: Path, width: int = 420, css: str = "") -> str:
    data = b64_image(path, width)
    if not data:
        return '<div class="missing">（无截图）</div>'
    return (
        f'<img class="{css}" loading="lazy" '
        f'src="data:image/jpeg;base64,{data}" alt="{esc(path.name)}">'
    )


def load_yaml_tasks() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(
        (ROOT / "benchmark" / "agent_tasks.yaml").read_text(encoding="utf-8")
    )
    return {str(item["id"]): item for item in data.get("tasks", [])}


def load_summary(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" in row:
            latest[str(row["id"])] = row
    return latest


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif part.get("type") == "image_url":
                    parts.append(f"[image omitted, {part.get('bytes', '?')} bytes]")
                else:
                    parts.append(json.dumps(part, ensure_ascii=False))
            else:
                parts.append(str(part))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def pair_llm_calls(path: Path) -> list[dict[str, Any]]:
    requests: dict[int, dict[str, Any]] = {}
    responses: dict[int, dict[str, Any]] = {}
    for row in load_jsonl(path):
        call = int(row.get("call", 0))
        if row.get("event") == "request":
            requests[call] = row
        elif row.get("event") == "response":
            responses[call] = row
    calls = []
    for call in sorted(set(requests) | set(responses)):
        request = requests.get(call, {})
        response = responses.get(call, {})
        calls.append(
            {
                "call": call,
                "model": request.get("model", ""),
                "messages": request.get("messages", []),
                "tool_names": request.get("tool_names", []),
                "content": response.get("content", ""),
                "tool_calls": response.get("tool_calls", []),
                "usage": response.get("usage", {}),
                "failed": not bool(response),
            }
        )
    return calls


def short(value: Any, limit: int = 260) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def badge(success: Any) -> str:
    if success is True:
        return '<span class="badge ok">成功</span>'
    if success is False:
        return '<span class="badge fail">失败</span>'
    return '<span class="badge skip">未判定</span>'


def status_pill(text: str) -> str:
    if text == "PASS":
        return '<span class="pill pass">PASS</span>'
    if text == "FAIL":
        return '<span class="pill fail">FAIL</span>'
    return '<span class="pill">—</span>'


def render_messages(messages: list[dict[str, Any]], limit: int = 8000) -> str:
    chunks = []
    for message in messages:
        content = extract_text(message.get("content", ""))
        chunks.append(
            f"<b>[{esc(message.get('type', '?'))}]</b>\n{esc(content[:limit])}"
        )
    return "\n\n".join(chunks)


def render_llm_section(task_dir: Path) -> str:
    calls = pair_llm_calls(task_dir / "llm_calls.jsonl")
    if not calls:
        return '<p class="muted">没有捕获到 LangChain 模型调用日志。</p>'
    rows = []
    for call in calls:
        rows.append(
            "<tr>"
            f"<td>{call['call']}</td>"
            f"<td><code>{esc(call['model'])}</code></td>"
            f"<td>{len(call['messages'])}</td>"
            f"<td>{len(call['tool_names'])}</td>"
            f"<td>{esc(', '.join(str(t) for t in call['tool_calls']) or '—')}</td>"
            f"<td>{call['usage'].get('input', '—')}/{call['usage'].get('output', '—')}</td>"
            f"<td>{'失败/无响应' if call['failed'] else 'OK'}</td>"
            "</tr>"
        )
    first = calls[0]
    last = calls[-1]
    details = f"""
    <details>
      <summary>模型调用统计（{len(calls)} 次）</summary>
      <table class="mini">
        <thead><tr><th>#</th><th>模型</th><th>消息数</th><th>工具数</th><th>生成的工具调用</th><th>输入/输出 token</th><th>状态</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </details>
    <details>
      <summary>首个模型请求（完整文本；截图以字节数代替）</summary>
      <pre>{render_messages(first['messages'])}</pre>
    </details>
    <details>
      <summary>最后一个模型响应</summary>
      <pre>{esc(extract_text(last['content']))}\n\n工具调用：{esc(json.dumps(last['tool_calls'], ensure_ascii=False, indent=2))}</pre>
    </details>
    """
    return details


def render_verifier_section(task_dir: Path, result: dict[str, Any]) -> str:
    rows = load_jsonl(task_dir / "verifier_llm.jsonl")
    last = rows[-1] if rows else {}
    prompt = ""
    messages = last.get("messages") or []
    for message in messages:
        if message.get("role") == "user":
            prompt = extract_text(message.get("content", ""))
            break
    response = last.get("content", "")
    usage = last.get("usage") or {}
    return f"""
    <details>
      <summary>最终状态判定器请求与响应</summary>
      <p><b>模型：</b><code>{esc(last.get('model', '—'))}</code>
         <b>耗时：</b>{esc(last.get('seconds', '—'))}s
         <b>token：</b>{esc(usage.get('prompt', '—'))}/{esc(usage.get('completion', '—'))}</p>
      <pre>{esc(prompt)}</pre>
      <p><b>响应：</b></p>
      <pre>{esc(response)}</pre>
    </details>
    """


def render_task(
    index: int,
    task: dict[str, Any],
    result: dict[str, Any],
    appagent_row: dict[str, Any] | None,
) -> str:
    task_id = str(task["id"])
    task_dir = RUNS / task_id
    success = result.get("success")
    steps = load_json(task_dir / "steps.json", [])
    actions = load_json(task_dir / "actions.json", [])
    final_shot = task_dir / "final.png"
    appagent_shot = APPAGENT / task_id / "final.jpg"
    deterministic = result.get("deterministic_ok")
    missing = result.get("missing_text") or []
    forbidden = result.get("forbidden_text_present") or []

    action_rows = []
    for i, action in enumerate(actions, 1):
        args = action.get("args", {})
        action_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><code>{esc(action.get('name', '—'))}</code></td>"
            f"<td><code>{esc(short(args, 220))}</code></td>"
            f"<td>{'✅' if action.get('success') else '❌'}</td>"
            "</tr>"
        )
    actions_html = (
        '<table class="mini"><thead><tr><th>#</th><th>动作</th><th>参数</th><th>工具结果</th></tr></thead>'
        f"<tbody>{''.join(action_rows)}</tbody></table>"
        if action_rows
        else '<p class="muted">没有解析到 executor 工具调用日志。</p>'
    )

    step_cards = []
    for step in steps:
        shot = task_dir / str(step.get("screenshot", ""))
        thought = step.get("thought") or "（该步没有文本思考）"
        step_cards.append(
            '<div class="step-card">'
            f'<div class="step-no">Step {step.get("step", "?")}</div>'
            f"{img_tag(shot, 380, 'step-shot')}"
            f'<div class="thought">{esc(short(thought, 1000))}</div>'
            "</div>"
        )
    steps_html = (
        f'<div class="steps-grid">{"".join(step_cards)}</div>'
        if step_cards
        else '<p class="muted">没有可用的 trace 截图。</p>'
    )

    appagent_html = ""
    if appagent_row or appagent_shot.exists():
        old = (appagent_row or {}).get("old_strict_success")
        new = (appagent_row or {}).get("new_rule_success")
        reason = (appagent_row or {}).get("reason", "")
        appagent_html = f"""
        <div class="compare-card">
          <h3>同任务 AppAgent 最终画面（对比）</h3>
          <div class="compare-grid">
            <div>{img_tag(appagent_shot, 260, 'compare-shot')}<div class="cap">AppAgent 最终画面</div></div>
            <div>{img_tag(final_shot, 260, 'compare-shot')}<div class="cap">mobile-use 最终画面</div></div>
          </div>
          <p><b>AppAgent 旧严格规则：</b>{badge(old)} <b>新最终状态规则：</b>{badge(new)}</p>
          <p class="muted">{esc(reason)}</p>
        </div>
        """

    check_detail = (
        f"<p><b>确定性文本检查：</b>{'通过' if deterministic else '未通过'}"
        f"{'；缺失：' + esc(', '.join(missing)) if missing else ''}"
        f"{'；禁止但出现：' + esc(', '.join(forbidden)) if forbidden else ''}</p>"
    )
    return f"""
    <section class="task" id="task-{esc(task_id)}">
      <h2>{index}. <code>{esc(task_id)}</code> {badge(success)}</h2>
      <p class="meta">
        App：{esc(task.get('app_name', task.get('app')))} |
        trace：{status_pill(str(result.get('agent_trace_status', '')))} |
        trace 步数：{result.get('steps', 0)} |
        executor 动作：{result.get('actions', 0)} |
        Agent 耗时：{result.get('agent_seconds', '—')}s |
        总墙钟：{result.get('elapsed_s', '—')}s |
        recursion limit：{result.get('recursion_limit', '—')}
      </p>
      <div class="goal"><b>用户目标：</b>{esc(task.get('goal', ''))}</div>
      <div class="final-grid">
        <div class="shot">
          {img_tag(final_shot, 560, 'final-shot')}
          <div class="cap">真机最终截图（agent 运行结束后立即抓取）</div>
        </div>
        <div class="check">
          <h3>最终状态判定</h3>
          <p><b>规则：</b><code>final_state_v1</code>（只看最终可观察状态）</p>
          <p><b>外部 VLM：</b>{badge(result.get('vlm_success'))}</p>
          <p><b>任务成功：</b>{badge(success)}</p>
          <p><b>理由：</b>{esc(result.get('reason', ''))}</p>
          <p><b>视觉证据：</b>{esc(result.get('evidence', '') or '—')}</p>
          {check_detail}
          <p><b>最终焦点窗口：</b><code>{esc(result.get('final_focus', '—'))}</code></p>
          <p><b>Agent 内部 trace 状态：</b>{status_pill(str(result.get('agent_trace_status', '')))}（仅记录，不参与评分）</p>
        </div>
      </div>
      {appagent_html}
      <h3>Executor 动作序列</h3>
      {actions_html}
      <h3>逐步真实截图 + 模型思考</h3>
      {steps_html}
      <h3>模型 I/O</h3>
      {render_llm_section(task_dir)}
      {render_verifier_section(task_dir, result)}
      <p class="files">原始证据：
        <code>runs/mobileuse/{esc(task_id)}/final.png</code>,
        <code>runs/mobileuse/{esc(task_id)}/steps.json</code>,
        <code>runs/mobileuse/{esc(task_id)}/actions.json</code>,
        <code>runs/mobileuse/{esc(task_id)}/llm_calls.jsonl</code>,
        <code>runs/mobileuse/{esc(task_id)}/verifier_llm.jsonl</code>
      </p>
    </section>
    """


CSS = """
:root { --ink:#17202a; --muted:#65727f; --line:#e2e8ee; --bg:#f6f8fa;
        --ok:#137a3f; --ok-bg:#e6f5ec; --fail:#b42318; --fail-bg:#fdecea;
        --accent:#1f5fbf; --accent-bg:#eaf1fb; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif;
       line-height:1.65; }
main { max-width:1240px; margin:0 auto; padding:32px 24px 80px; }
h1 { font-size:30px; line-height:1.25; margin:0 0 8px; }
h2 { font-size:21px; margin:34px 0 12px; padding-bottom:8px;
     border-bottom:2px solid var(--line); }
h3 { font-size:16px; margin:20px 0 8px; }
p { margin:8px 0; }
code, pre { font-family:"Cascadia Code",Consolas,monospace; }
code { background:#eef2f6; padding:1px 5px; border-radius:4px; font-size:0.92em; }
pre { background:#0f1720; color:#e6edf3; padding:14px 16px; border-radius:8px;
      overflow:auto; font-size:12px; line-height:1.55; max-height:520px; }
details { background:#fff; border:1px solid var(--line); border-radius:8px;
          padding:10px 14px; margin:10px 0; }
summary { cursor:pointer; font-weight:600; }
.sub { color:var(--muted); font-size:14px; margin-bottom:24px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px; margin:20px 0 8px; }
.card { background:#fff; border:1px solid var(--line); border-radius:10px;
        padding:14px 16px; }
.card .n { font-size:26px; font-weight:700; }
.card .l { color:var(--muted); font-size:13px; }
.badge { display:inline-block; padding:2px 9px; border-radius:999px;
         font-size:12px; font-weight:700; vertical-align:middle; }
.badge.ok { color:var(--ok); background:var(--ok-bg); }
.badge.fail { color:var(--fail); background:var(--fail-bg); }
.badge.skip { color:var(--muted); background:#eef2f6; }
.pill { display:inline-block; padding:1px 8px; border-radius:999px;
        font-size:12px; font-weight:700; background:#eef2f6; color:var(--muted); }
.pill.pass { background:var(--ok-bg); color:var(--ok); }
.pill.fail { background:var(--fail-bg); color:var(--fail); }
table { width:100%; border-collapse:collapse; background:#fff;
        border:1px solid var(--line); border-radius:8px; overflow:hidden;
        margin:12px 0 18px; font-size:13px; }
th, td { padding:8px 10px; border-bottom:1px solid var(--line);
         text-align:left; vertical-align:top; }
th { background:#f0f4f8; font-size:12px; text-transform:uppercase;
     letter-spacing:.03em; color:#40505f; }
tr:last-child td { border-bottom:0; }
table.mini { font-size:12px; }
table.mini code { font-size:11px; word-break:break-all; }
.task { background:#fff; border:1px solid var(--line); border-radius:12px;
        padding:20px 22px; margin:22px 0; }
.goal { background:var(--accent-bg); border-left:4px solid var(--accent);
        padding:10px 14px; border-radius:6px; margin:12px 0 16px; }
.meta { color:var(--muted); font-size:13px; }
.final-grid { display:grid; grid-template-columns:minmax(260px,560px) 1fr;
              gap:20px; align-items:start; }
.check { background:#fbfcfd; border:1px solid var(--line); border-radius:10px;
         padding:14px 16px; }
.shot img, .final-shot { width:100%; height:auto; border-radius:8px;
                         border:1px solid var(--line); }
.cap { color:var(--muted); font-size:12px; margin-top:6px; }
.steps-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
              gap:14px; }
.step-card { border:1px solid var(--line); border-radius:10px; padding:10px;
             background:#fbfcfd; }
.step-no { font-weight:700; color:var(--accent); font-size:13px; margin-bottom:6px; }
.step-shot { width:100%; height:auto; border-radius:7px; border:1px solid var(--line); }
.thought { font-size:12px; color:#384553; margin-top:8px; max-height:150px;
           overflow:auto; white-space:pre-wrap; }
.compare-card { background:#fbfcfd; border:1px solid var(--line);
                border-radius:10px; padding:14px 16px; margin:16px 0; }
.compare-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px;
                max-width:620px; }
.compare-shot { width:100%; border-radius:7px; border:1px solid var(--line); }
.files { color:var(--muted); font-size:12px; margin-top:16px; }
.muted { color:var(--muted); }
.missing { background:#f1f5f9; color:var(--muted); padding:20px;
           border-radius:8px; text-align:center; }
.warn { background:#fff7e6; border-left:4px solid #d97706;
        padding:10px 14px; border-radius:6px; margin:12px 0; }
.toc a { color:var(--accent); text-decoration:none; }
.toc li { margin:3px 0; }
@media (max-width:860px) { .final-grid, .compare-grid { grid-template-columns:1fr; } }
"""


def main() -> int:
    tasks = load_yaml_tasks()
    results = load_summary(RUNS / "summary.jsonl")
    appagent_new = {
        str(row["id"]): row
        for row in load_json(APPAGENT / "state_reeval.json", [])
    }
    appagent_old = load_summary(APPAGENT / "summary.jsonl")

    ordered_ids = list(tasks.keys())
    mobile_rows = [results.get(task_id, {}) for task_id in ordered_ids]
    success_count = sum(1 for row in mobile_rows if row.get("success") is True)
    trace_pass = sum(
        1 for row in mobile_rows if row.get("agent_trace_status") == "PASS"
    )
    total_steps = sum(int(row.get("steps", 0)) for row in mobile_rows)
    total_actions = sum(int(row.get("actions", 0)) for row in mobile_rows)
    total_agent_s = sum(float(row.get("agent_seconds", 0)) for row in mobile_rows)
    total_wall_s = sum(float(row.get("elapsed_s", 0)) for row in mobile_rows)
    appagent_new_success = sum(
        1 for task_id in ordered_ids
        if (appagent_new.get(task_id) or {}).get("new_rule_success") is True
    )
    appagent_old_success = sum(
        1 for task_id in ordered_ids
        if (appagent_old.get(task_id) or {}).get("success") is True
    )
    appagent_text_ok = sum(
        1 for task_id in ordered_ids
        if (appagent_old.get(task_id) or {}).get("deterministic_ok") is True
    )

    result_rows = []
    for index, task_id in enumerate(ordered_ids, 1):
        task = tasks[task_id]
        row = results.get(task_id, {})
        result_rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td><a href=\"#task-{esc(task_id)}\"><code>{esc(task_id)}</code></a></td>"
            f"<td>{esc(task.get('app_name', task.get('app')))}</td>"
            f"<td>{badge(row.get('success'))}</td>"
            f"<td>{status_pill(str(row.get('agent_trace_status', '')))}</td>"
            f"<td>{row.get('steps', '—')}</td>"
            f"<td>{row.get('actions', '—')}</td>"
            f"<td>{row.get('agent_seconds', '—')}s</td>"
            f"<td>{esc(short(row.get('reason', ''), 220))}</td>"
            "</tr>"
        )

    compare_rows = []
    for task_id in ordered_ids:
        task = tasks[task_id]
        old = appagent_old.get(task_id, {})
        new = appagent_new.get(task_id, {})
        mob = results.get(task_id, {})
        compare_rows.append(
            "<tr>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td>{esc(task.get('app_name', task.get('app')))}</td>"
            f"<td>{badge(old.get('success'))}</td>"
            f"<td>{badge(new.get('new_rule_success'))}</td>"
            f"<td>{badge(mob.get('success'))}</td>"
            f"<td>{esc(short(new.get('reason', ''), 180))}</td>"
            "</tr>"
        )

    task_sections = "".join(
        render_task(index, tasks[task_id], results.get(task_id, {}), appagent_new.get(task_id))
        for index, task_id in enumerate(ordered_ids, 1)
        if task_id in results
    )

    toc = "".join(
        f'<li><a href="#task-{esc(task_id)}">{index}. {esc(task_id)}</a></li>'
        for index, task_id in enumerate(ordered_ids, 1)
        if task_id in results
    )

    report = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mobile-use 真机基线验收报告</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>mobile-use 真机基线验收报告</h1>
<p class="sub">
  真机：Pixel 9 Pro XL（Android 16，BP3A.251105.015，1008×2244，serial 47261FDAS00DTQ）·
  Baseline：<code>minitap-ai/mobile-use</code> 4.0.0（Apache-2.0，commit ef059d6，2026-11-04）·
  模型网关：本地 magpie，<code>auto/gpt-6.1-sol</code>（fallback <code>auto/gpt-6-luna</code>）·
  判定：<code>final_state_v1</code>（最终可观察状态）·
  生成日期：2026-11-10
</p>

<div class="cards">
  <div class="card"><div class="n">{success_count}/{len(ordered_ids)}</div><div class="l">最终状态成功</div></div>
  <div class="card"><div class="n">{trace_pass}/{len(ordered_ids)}</div><div class="l">Agent 内部 trace PASS</div></div>
  <div class="card"><div class="n">{total_steps}</div><div class="l">trace 步数（真实截图）</div></div>
  <div class="card"><div class="n">{total_actions}</div><div class="l">executor 动作</div></div>
  <div class="card"><div class="n">{total_agent_s/60:.1f} min</div><div class="l">Agent 累计耗时</div></div>
  <div class="card"><div class="n">{total_wall_s/60:.1f} min</div><div class="l">总墙钟</div></div>
</div>

<h2>1. 为什么换 baseline</h2>
<p>
上一版使用 AppAgent（CHI 2025）。它没有显式的 Back / Wait / press_key / stop_app 动作，
没有独立 planner，也不会主动检测循环；在 8 个长程任务上，最终只能完成 2/8（旧严格规则）。
这不符合“先找一个近一年、效果好的开源 GUI Agent 作为基础”的要求。
</p>
<table>
  <thead><tr><th>候选</th><th>时间/许可</th><th>与本地的兼容性</th><th>结论</th></tr></thead>
  <tbody>
    <tr><td><b>mobile-use</b> 4.0.0</td><td>2026-11，Apache-2.0</td>
        <td>Python 3.12；uiautomator2 + adb；OpenAI-compatible base URL；planner/orchestrator/cortex/executor 多 Agent；
        动作含 back、wait_for_delay、press_key、launch_app、stop_app、scratchpad；论文声称 AndroidWorld 100%</td>
        <td><b>采用</b></td></tr>
    <tr><td>Mobile-Agent-v3</td><td>2025</td><td>依赖 Qwen-VL / GUI-Owl 专用模型；本地 magpie 没有对应模型</td><td>不作为基线</td></tr>
    <tr><td>DroidRun</td><td>2026，MIT</td><td>声称 AndroidWorld 91.4%；本机网络 clone 失败，未完成验证</td><td>备选</td></tr>
    <tr><td>UI-TARS / AgentCPM-GUI</td><td>2025–2026</td><td>依赖专用 GUI 模型与推理栈</td><td>不作为基线</td></tr>
    <tr><td>AppAgent</td><td>CHI 2025</td><td>截图 + 标注元素 ReAct；无 Back/Wait；无 planner/循环检测</td><td>保留为旧对照</td></tr>
  </tbody>
</table>

<h2>2. 成功/失败判定规则（已更换）</h2>
<div class="warn">
旧规则要求“最终截图必须同时显示完整目标的过程证据”，例如要求任务 1 的最终列表还能看到
被归档的 Work 内容；这对“归档/删除/完成”类任务天然不可能，导致 6/8 文本检查通过却只判 2/8。
</div>
<p><b>新规则 <code>final_state_v1</code>：</b>只判断 Agent 停止后、App 的最终可观察状态是否满足目标。
不要求看到中间步骤、不要求复现路径、不要求读取隐藏数据库；如果目标是“归档/删除/完成”，
最终列表/完成视图中的状态即可作为证据。最终截图 + final UI 文本交给外部 VLM，按下面提示词判定。</p>
<pre>{esc(prompts.STATE_VERIFIER)}</pre>
<p class="muted">确定性文本检查仍会记录（required / forbidden），但只作为辅助信号；最终判定以最终状态 VLM 为准，
且如果 final UI 中出现了 forbidden 文本，直接判失败。Agent 自己的 trace PASS/FAIL 只记录，不参与评分。</p>

<h2>3. 结果总览（mobile-use，新规则）</h2>
<table>
  <thead><tr><th>#</th><th>任务</th><th>App</th><th>成功</th><th>trace</th><th>步数</th><th>动作</th><th>Agent 耗时</th><th>判定理由（截断）</th></tr></thead>
  <tbody>{''.join(result_rows)}</tbody>
</table>

<h2>4. 与 AppAgent 的对比（同一批 8 个任务）</h2>
<table>
  <thead><tr><th>任务</th><th>App</th><th>AppAgent 旧严格规则</th><th>AppAgent 新最终状态规则</th><th>mobile-use 新规则</th><th>AppAgent 新规则理由（截断）</th></tr></thead>
  <tbody>{''.join(compare_rows)}</tbody>
</table>
<p class="muted">
汇总：AppAgent 旧严格 {appagent_old_success}/8；AppAgent 仅换判定规则（不重跑）{appagent_new_success}/8；
AppAgent 确定性文本检查通过 {appagent_text_ok}/8；mobile-use 新规则 {success_count}/8。
AppAgent 的新规则分数来自其已完成的最终截图 + final UI 重新判定，不是重跑结果。
</p>

<h2>5. 逐任务证据</h2>
<p class="toc">目录：<ul class="toc">{toc}</ul></p>
{task_sections}

<h2>6. Agent 架构与动作空间（来自 mobile-use 源码）</h2>
<p>
mobile-use 使用 LangGraph 多 Agent 图：planner 生成子目标，orchestrator 选择当前子目标，
contextor 抓取 UI 层级/截图/前台 App，cortex 产生结构化决策，executor 选择并调用工具；
utils.hopper 负责长上下文压缩，utils.outputter 负责最终输出。每个任务有独立 scratchpad 持久记忆。
</p>
<p>
Executor 动作空间（<code>minitap/mobile_use/tools/index.py</code>）：
<code>back</code>、<code>open_link</code>、<code>tap</code>、<code>long_press_on</code>、
<code>swipe</code>、<code>focus_and_input_text</code>、<code>erase_one_char</code>、
<code>launch_app</code>、<code>stop_app</code>、<code>focus_and_clear_text</code>、
<code>press_key</code>、<code>wait_for_delay</code>、scratchpad 的
<code>save_note</code>/<code>read_note</code>/<code>list_notes</code>。
这正好覆盖了上一版缺失的 Back / Wait / Home / 启动/停止 App。
</p>

<h2>7. 配置与最小改动</h2>
<ul>
  <li><b>Agent 代码未重写。</b>直接使用 <code>third_party/mobile-use</code> 的 SDK 与 LangGraph 实现。</li>
  <li><b>模型配置：</b><code>llm-config.override.jsonc</code> 只把 7 个节点的 provider/model 改成
      <code>openai</code> + <code>auto/gpt-6.1-sol</code>，fallback <code>auto/gpt-6-luna</code>；
      未改 prompt、图结构或动作实现。</li>
  <li><b>网关：</b><code>.env</code> 设置 <code>OPENAI_BASE_URL=http://127.0.0.1:3425/v1</code>、
      <code>OPENAI_API_KEY=magpie</code>、关闭 telemetry。</li>
  <li><b>证据补丁（非 Agent 逻辑）：</b><code>utils/media.py</code> 的
      <code>remove_images_from_trace_folder()</code> 在
      <code>MOBILE_USE_KEEP_TRACE_IMAGES=1</code> 时保留每步 JPEG；默认行为不变。
      这是为了报告能嵌入真机逐步截图，不影响 Agent 决策。</li>
  <li><b>运行器：</b><code>scripts/run_mobileuse_tasks.py</code> 只做 App 重置/启动、SDK 调用、
      最终截图/UI 抓取、trace 复制和判定；没有实现 Agent 策略。</li>
</ul>

<h2>8. 局限与诚实说明</h2>
<ul>
  <li>每个任务只跑 1 次；真机存在动画、网络、通知、输入法差异，单次结果不等于统计成功率。</li>
  <li>最终状态判定依赖外部 VLM（<code>auto/gpt-6.1-sol</code>），可能存在视觉误读；报告同时保留确定性文本检查和原始截图，便于人工复核。</li>
  <li>没有读取 App 的 SQLite/SharedPreferences 等隐藏状态，只按用户可见的最终界面判定；这符合“用户可观察状态”的验收口径，但对“已完成但未打开完成视图”的情况可能偏严。</li>
  <li>AndroidWorld 论文的 100% 结果来自其 benchmark 配置与模型栈；本报告不是 AndroidWorld 复现，而是同一批 8 个长程任务上的本地真机基线验证。</li>
  <li>AppAgent 的新规则分数是对旧最终截图的离线重判，不是重跑；旧严格结果仍保留在 <code>runs/appagent/</code>。</li>
</ul>

<h2>9. 复现</h2>
<pre>cd E:/CodeE/vibe51/StarTrek
# 1) 安装（Python 3.12）
python -m venv .venv-mobileuse
.venv-mobileuse/Scripts/python -m pip install -e third_party/mobile-use
# 2) 配置网关
#    third_party/mobile-use/.env
#    third_party/mobile-use/llm-config.override.jsonc
# 3) 跑一个任务
.venv-mobileuse/Scripts/python scripts/run_mobileuse_tasks.py --only diary_officework_session
# 4) 跑全部 8 个任务
.venv-mobileuse/Scripts/python scripts/run_mobileuse_tasks.py
# 5) 重新判定 AppAgent 旧最终画面（同一新规则）
.venv-mobileuse/Scripts/python scripts/reeval_appagent_state.py
# 6) 生成报告
.venv-mobileuse/Scripts/python scripts/build_mobileuse_report.py</pre>

<h2>10. 文件清单</h2>
<ul>
  <li><code>benchmark/agent_tasks.yaml</code> — 8 个任务与最终状态检查</li>
  <li><code>third_party/mobile-use/</code> — 开源 baseline（Apache-2.0）</li>
  <li><code>scripts/run_mobileuse_tasks.py</code> — 薄运行器 + 最终状态判定</li>
  <li><code>scripts/reeval_appagent_state.py</code> — AppAgent 旧最终画面按新规则重判</li>
  <li><code>scripts/build_mobileuse_report.py</code> — 本报告生成器</li>
  <li><code>runs/mobileuse/&lt;task&gt;/</code> — 最终截图、final UI、trace JPEG、动作日志、模型 I/O、判定器日志</li>
  <li><code>runs/appagent/</code> — 旧 baseline 的原始结果与重判结果</li>
</ul>
</main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size/1024/1024:.2f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
