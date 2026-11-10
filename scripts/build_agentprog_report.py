#!/usr/bin/env python3
"""Build a self-contained HTML acceptance report for the AgentProg baseline.

Reads only real run artifacts under runs/agentprog/ plus the completed AppAgent
comparison run.  Every screenshot embedded in the report is a real device
frame from AgentProg's own step capture or the final capture, not a scripted
recreation.
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

RUNS = ROOT / "runs" / "agentprog"
APPAGENT = ROOT / "runs" / "appagent"
OUT = ROOT / "docs" / "reports" / "agentprog-report.html"


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


def load_results() -> dict[str, dict[str, Any]]:
    """Union per-task result.json with summary.json (summary wins).

    The union matters when the suite is run in batches: summary.json only
    describes the latest batch, while every completed task keeps its own
    result.json.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in RUNS.glob("*/result.json"):
        row = load_json(path, {})
        if isinstance(row, dict) and row.get("id"):
            rows[str(row["id"])] = row
    summary = load_json(RUNS / "summary.json", [])
    if isinstance(summary, list):
        for row in summary:
            if isinstance(row, dict) and row.get("id"):
                rows[str(row["id"])] = row
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


def render_messages(messages: list[dict[str, Any]], limit: int = 8000) -> str:
    chunks = []
    for message in messages:
        content = extract_text(message.get("content", ""))
        chunks.append(
            f"<b>[{esc(message.get('role', message.get('type', '?')))}]</b>\n"
            f"{esc(content[:limit])}"
        )
    return "\n\n".join(chunks)


def load_calls(task_dir: Path) -> list[dict[str, Any]]:
    return [row for row in load_jsonl(task_dir / "llm_calls.jsonl") if "request" in row]


def render_call_detail(call: dict[str, Any]) -> str:
    """One expandable block per real model call: request + response."""
    usage = call.get("usage") or {}
    tokens = (
        f" · {usage.get('prompt_tokens', '—')}/{usage.get('completion_tokens', '—')} tok"
        if usage
        else ""
    )
    request_text = render_messages(call.get("request", []), limit=6000)
    response_text = extract_text(call.get("response", call.get("error", "")))
    return f"""
    <details class="call">
      <summary>#{esc(call.get('call', '—'))} <code>{esc(call.get('purpose', '—'))}</code>
        · {esc(call.get('duration_s', '—'))}s{tokens}</summary>
      <div class="call-grid">
        <div><div class="call-label">模型请求（文本部分；截图以字节数代替）</div>
          <pre>{esc(request_text)}</pre></div>
        <div><div class="call-label">模型响应</div>
          <pre>{esc(response_text)}</pre></div>
      </div>
    </details>
    """


def render_llm_section(task_dir: Path) -> str:
    calls = load_calls(task_dir)
    if not calls:
        return '<p class="muted">没有捕获到 AgentProg 模型调用日志。</p>'
    rows = []
    for call in calls:
        usage = call.get("usage") or {}
        rows.append(
            "<tr>"
            f"<td>{call.get('call', '—')}</td>"
            f"<td><code>{esc(call.get('purpose', '—'))}</code></td>"
            f"<td>{esc(call.get('duration_s', '—'))}s</td>"
            f"<td>{esc(usage.get('prompt_tokens', '—'))}/{esc(usage.get('completion_tokens', '—'))}</td>"
            f"<td>{esc(short(call.get('response', call.get('error', '')), 260))}</td>"
            "</tr>"
        )
    table = (
        '<table class="mini"><thead><tr><th>#</th><th>用途</th><th>耗时</th>'
        '<th>输入/输出 token</th><th>响应（截断）</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    grounded = [c for c in calls if c.get("purpose") == "ui_tars_grounding"]
    grounding_rows = []
    for call in grounded:
        request_text = ""
        for message in call.get("request", []):
            text = extract_text(message.get("content", ""))
            if "User Instruction" in text or "Click on" in text:
                request_text = text
                break
        instruction = request_text.split("## User Instruction", 1)[-1].strip()
        grounding_rows.append(
            "<tr>"
            f"<td>{call.get('call', '—')}</td>"
            f"<td><code>{esc(short(instruction, 180))}</code></td>"
            f"<td><code>{esc(short(call.get('response', call.get('error', '')), 220))}</code></td>"
            f"<td>{esc(call.get('duration_s', '—'))}s</td>"
            "</tr>"
        )
    grounding_table = (
        '<table class="mini"><thead><tr><th>#</th><th>定位指令</th>'
        '<th>返回动作</th><th>耗时</th></tr></thead>'
        f"<tbody>{''.join(grounding_rows)}</tbody></table>"
        if grounding_rows
        else '<p class="muted">没有 UI-TARS grounding 调用。</p>'
    )
    call_details = "".join(
        render_call_detail(call) for call in calls
    )
    return f"""
    <details open>
      <summary>模型调用统计（{len(calls)} 次）</summary>
      {table}
    </details>
    <details>
      <summary>UI-TARS 定位调用（{len(grounded)} 次；真机点击坐标由此产生）</summary>
      {grounding_table}
    </details>
    <details>
      <summary>每一步的模型请求与响应（{len(calls)} 次调用，展开查看）</summary>
      {call_details or '<p class="muted">没有记录。</p>'}
    </details>
    """


ACTION_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[info\s+\] (.+?) \[agentprog\."
)
ACTION_MARKERS = (
    "👆 Clicking",
    "👆⏱️ Long clicking",
    "⌨️ Inputting",
    "📋 Inputting",
    "🔙 Navigating back",
    "⏳ Waiting for element",
)


def render_action_timeline(task_dir: Path) -> str:
    """Real device actions AgentProg logged, with timestamps."""
    log_path = task_dir / "agent.log"
    if not log_path.exists():
        return '<p class="muted">没有 agent.log。</p>'
    rows = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ACTION_LINE.match(line)
        if not match:
            continue
        message = match.group(2)
        if not any(marker in message for marker in ACTION_MARKERS):
            continue
        rows.append((match.group(1), message))
    if not rows:
        return '<p class="muted">没有解析到点击/输入/等待动作。</p>'
    body = "".join(
        f"<tr><td><code>{esc(stamp)}</code></td><td>{esc(message)}</td></tr>"
        for stamp, message in rows
    )
    return (
        '<table class="mini"><thead><tr><th>时间</th><th>真机动作</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def render_verifier_section(task_dir: Path) -> str:
    rows = load_jsonl(task_dir / "verifier_llm.jsonl")
    last = rows[-1] if rows else {}
    prompt = ""
    for message in last.get("messages") or []:
        if message.get("role") == "user":
            prompt = extract_text(message.get("content", ""))
            break
    usage = last.get("usage") or {}
    return f"""
    <details>
      <summary>最终状态判定器请求与响应</summary>
      <p><b>模型：</b><code>{esc(last.get('model', '—'))}</code>
         <b>耗时：</b>{esc(last.get('seconds', '—'))}s
         <b>token：</b>{esc(usage.get('prompt', '—'))}/{esc(usage.get('completion', '—'))}</p>
      <pre>{esc(prompt)}</pre>
      <p><b>响应：</b></p>
      <pre>{esc(last.get('content', last.get('error', '')))}</pre>
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
    final_shot = task_dir / "final.png"
    start_shot = task_dir / "start.png"
    appagent_shot = APPAGENT / task_id / "final.jpg"
    deterministic = result.get("deterministic_ok")
    missing = result.get("missing_text") or []
    forbidden = result.get("forbidden_text_present") or []
    program = ""
    workflow_path = task_dir / "workflow.ap"
    if workflow_path.exists():
        program = workflow_path.read_text(encoding="utf-8", errors="replace")

    images = sorted(
        (task_dir / "images").glob("*.png"),
        key=lambda path: int(re.search(r"(\d+)", path.stem).group(1))
        if re.search(r"(\d+)", path.stem)
        else 0,
    )
    step_cards = []
    for image in images:
        step_cards.append(
            '<div class="step-card">'
            f'<div class="step-no">{esc(image.stem)}</div>'
            f"{img_tag(image, 380, 'step-shot')}"
            "</div>"
        )
    steps_html = (
        f'<div class="steps-grid">{"".join(step_cards)}</div>'
        if step_cards
        else '<p class="muted">没有保存到逐步截图。</p>'
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
            <div>{img_tag(final_shot, 260, 'compare-shot')}<div class="cap">AgentProg 最终画面</div></div>
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
    error_html = (
        f'<div class="warn"><b>AgentProg 运行异常：</b>'
        f"<code>{esc(short(result.get('error', ''), 800))}</code></div>"
        if result.get("error")
        else ""
    )
    return f"""
    <section class="task" id="task-{esc(task_id)}">
      <h2>{index}. <code>{esc(task_id)}</code> {badge(success)}</h2>
      <p class="meta">
        App：{esc(task.get('app_name', task.get('app')))} |
        模型调用：{result.get('model_calls', '—')} 次 |
        Agent 耗时：{result.get('agent_seconds', '—')}s |
        逐步截图：{len(images)} 张 |
        timeout：{'是' if result.get('timed_out') else '否'}
      </p>
      <div class="goal"><b>用户目标：</b>{esc(task.get('goal', ''))}</div>
      {error_html}
      <details>
        <summary>任务开始前的真机画面（App 重置/启动后，Agent 尚未动作）</summary>
        <div class="start-shot">{img_tag(start_shot, 320, 'step-shot')}</div>
      </details>
      <div class="final-grid">
        <div class="shot">
          {img_tag(final_shot, 560, 'final-shot')}
          <div class="cap">真机最终截图（AgentProg 运行结束后立即抓取）</div>
        </div>
        <div class="check">
          <h3>最终状态判定</h3>
          <p><b>规则：</b><code>final_state_v1</code>（只看最终可观察状态）</p>
          <p><b>任务成功：</b>{badge(success)}</p>
          <p><b>理由：</b>{esc(result.get('reason', ''))}</p>
          <p><b>视觉证据：</b>{esc(result.get('evidence', '') or '—')}</p>
          {check_detail}
        </div>
      </div>
      {appagent_html}
      <h3>AgentProg 生成的 Task Program（STP）</h3>
      <pre>{esc(program or '（没有生成 workflow.ap）')}</pre>
      <h3>逐步真实截图（AgentProg 自己保存的每一步画面）</h3>
      {steps_html}
      <h3>真机动作时间线（AgentProg 日志中的点击/输入/等待）</h3>
      {render_action_timeline(task_dir)}
      <h3>模型 I/O</h3>
      {render_llm_section(task_dir)}
      {render_verifier_section(task_dir)}
      <p class="files">原始证据：
        <code>runs/agentprog/{esc(task_id)}/final.png</code>,
        <code>runs/agentprog/{esc(task_id)}/workflow.ap</code>,
        <code>runs/agentprog/{esc(task_id)}/images/</code>,
        <code>runs/agentprog/{esc(task_id)}/llm_calls.jsonl</code>,
        <code>runs/agentprog/{esc(task_id)}/agent.log</code>,
        <code>runs/agentprog/{esc(task_id)}/verifier_llm.jsonl</code>
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
.start-shot { max-width:340px; margin:10px 0; }
.compare-card { background:#fbfcfd; border:1px solid var(--line);
                border-radius:10px; padding:14px 16px; margin:16px 0; }
.compare-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px;
                max-width:620px; }
.compare-shot { width:100%; border-radius:7px; border:1px solid var(--line); }
.call { background:#fbfcfd; border:1px solid var(--line); border-radius:8px;
        padding:8px 12px; margin:8px 0; }
.call summary { font-size:12px; }
.call-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:8px; }
.call-label { font-size:11px; color:var(--muted); font-weight:700;
              text-transform:uppercase; letter-spacing:.03em; }
.call pre { max-height:360px; }
@media (max-width:860px) { .call-grid { grid-template-columns:1fr; } }
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


def main(argv: list[str] | None = None) -> int:
    import argparse

    global RUNS, APPAGENT, OUT
    parser = argparse.ArgumentParser(description="Build the AgentProg acceptance report")
    parser.add_argument("--runs", type=Path, default=RUNS)
    parser.add_argument("--appagent", type=Path, default=APPAGENT)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    RUNS, APPAGENT, OUT = args.runs, args.appagent, args.out

    tasks = load_yaml_tasks()
    results = load_results()
    appagent_new = {
        str(row["id"]): row
        for row in load_json(APPAGENT / "state_reeval.json", [])
    }
    appagent_old = {
        str(row["id"]): row
        for row in load_json(APPAGENT / "summary.json", [])
    } if (APPAGENT / "summary.json").exists() else {}
    if not appagent_old and (APPAGENT / "summary.jsonl").exists():
        appagent_old = {}
        for row in load_jsonl(APPAGENT / "summary.jsonl"):
            if row.get("id"):
                appagent_old[str(row["id"])] = row

    ordered_ids = [task_id for task_id in tasks if task_id in results]
    rows = [results[task_id] for task_id in ordered_ids]
    success_count = sum(1 for row in rows if row.get("success") is True)
    total_calls = sum(int(row.get("model_calls") or 0) for row in rows)
    total_agent_s = sum(float(row.get("agent_seconds") or 0) for row in rows)
    total_images = sum(
        len(list((RUNS / str(row.get("id")) / "images").glob("*.png"))) for row in rows
    )
    appagent_new_success = sum(
        1 for task_id in ordered_ids
        if (appagent_new.get(task_id) or {}).get("new_rule_success") is True
    )
    appagent_old_success = sum(
        1 for task_id in ordered_ids
        if (appagent_old.get(task_id) or {}).get("success") is True
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
            f"<td>{row.get('model_calls', '—')}</td>"
            f"<td>{row.get('agent_seconds', '—')}s</td>"
            f"<td>{esc(short(row.get('reason', ''), 220))}</td>"
            "</tr>"
        )

    compare_rows = []
    for task_id in ordered_ids:
        task = tasks[task_id]
        old = appagent_old.get(task_id, {})
        new = appagent_new.get(task_id, {})
        row = results.get(task_id, {})
        compare_rows.append(
            "<tr>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td>{esc(task.get('app_name', task.get('app')))}</td>"
            f"<td>{badge(old.get('success'))}</td>"
            f"<td>{badge(new.get('new_rule_success'))}</td>"
            f"<td>{badge(row.get('success'))}</td>"
            f"<td>{esc(short(new.get('reason', ''), 180))}</td>"
            "</tr>"
        )

    task_sections = "".join(
        render_task(
            index,
            tasks[task_id],
            results.get(task_id, {}),
            appagent_new.get(task_id),
        )
        for index, task_id in enumerate(ordered_ids, 1)
    )
    toc = "".join(
        f'<li><a href="#task-{esc(task_id)}">{index}. {esc(task_id)}</a></li>'
        for index, task_id in enumerate(ordered_ids, 1)
    )

    report = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentProg 真机基线验收报告</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>AgentProg 真机基线验收报告</h1>
<p class="sub">
  真机：Pixel 9 Pro XL（Android 16，1008×2244，serial 47261FDAS00DTQ）·
  Baseline：<code>MobileLLM/AgentProg</code>（Tsinghua AIR，arXiv 2512.10371，2025-12，开源）·
  模型网关：本地 magpie，<code>auto/gpt-6.1-sol</code>（fallback <code>auto/gpt-6-luna</code>）·
  判定：<code>final_state_v1</code>（最终可观察状态）·
  生成日期：2026-11-10
</p>

<div class="cards">
  <div class="card"><div class="n">{success_count}/{len(ordered_ids)}</div><div class="l">最终状态成功</div></div>
  <div class="card"><div class="n">{total_calls}</div><div class="l">模型调用</div></div>
  <div class="card"><div class="n">{total_images}</div><div class="l">逐步真实截图</div></div>
  <div class="card"><div class="n">{total_agent_s/60:.1f} min</div><div class="l">Agent 累计耗时</div></div>
  <div class="card"><div class="n">{appagent_new_success}/{len(ordered_ids)}</div><div class="l">AppAgent 同规则（对比）</div></div>
  <div class="card"><div class="n">{appagent_old_success}/{len(ordered_ids)}</div><div class="l">AppAgent 旧严格规则</div></div>
</div>

<h2>1. 为什么用 AgentProg 作为 baseline</h2>
<p>
要求是“学术界论文里用的、代码开源的 Agent，后续可以改、可以看实现”。
AgentProg 来自清华 AIR（Tsinghua AIR），论文
<a href="https://arxiv.org/abs/2512.10371">arXiv 2512.10371</a>（2025-12），
代码在 <code>github.com/MobileLLM/AgentProg</code>，是面向长程 GUI 任务的
program-guided context management 工作；它用 Semantic Task Program（STP）把执行过程
表示成带变量和控制流的程序，从而在长任务中裁掉无关历史、保留关键数据。
它支持真实 Android（adb），动作覆盖 click / long_press / type / scroll / open_app /
drag / press_home / press_back 等。
</p>
<table>
  <thead><tr><th>候选</th><th>时间/许可</th><th>与本地的兼容性</th><th>结论</th></tr></thead>
  <tbody>
    <tr><td><b>AgentProg</b></td><td>2025-12，开源（Tsinghua AIR）</td>
        <td>Python 3.12；litellm + OpenAI-compatible base URL；真实 adb；STP 程序执行；
        UI-TARS grounding 可替换为本地 VLM；论文 arXiv 2512.10371</td>
        <td><b>采用</b></td></tr>
    <tr><td>mobile-use</td><td>2026-02，Apache-2.0（Minitap 商业公司）</td>
        <td>能跑通真机，planner/orchestrator/cortex/executor 多 Agent；但属于商业应用，
        不符合“学术界的、论文里用的”要求</td>
        <td>不作为最终 baseline</td></tr>
    <tr><td>Mobile-Agent-v3</td><td>2025-08，arXiv 2508.15144</td>
        <td>学术开源；但依赖 GUI-Owl-7B/32B 与 vLLM，本地 magpie 没有对应模型</td>
        <td>备选，未运行</td></tr>
    <tr><td>V-Droid</td><td>MobiCom'26，arXiv 2503.15937</td>
        <td>学术开源；依赖 V-Droid-8B 专用模型</td>
        <td>备选，未运行</td></tr>
    <tr><td>AppAgent</td><td>CHI 2025</td>
        <td>截图 + 标注元素 ReAct；无 Back/Wait/planner/循环检测，长任务弱</td>
        <td>保留为旧对照</td></tr>
  </tbody>
</table>

<h2>2. 成功/失败判定规则</h2>
<p><b>旧规则</b>要求最终截图同时显示完整目标的过程证据，对“归档/删除/完成”类任务天然不可能，
导致 AppAgent 在 8 个任务上只有 2/8（旧严格规则）。</p>
<p><b>新规则 <code>final_state_v1</code>：</b>只判断 Agent 停止后、App 的最终可观察状态是否满足目标。
不要求看到中间步骤、不要求复现路径、不要求读取隐藏数据库；如果目标是“归档/删除/完成”，
最终列表/完成视图中的状态即可作为证据。最终截图 + final UI 文本交给外部 VLM，按下面提示词判定。</p>
<pre>{esc(prompts.STATE_VERIFIER)}</pre>
<p class="muted">确定性文本检查仍会记录（required / forbidden），但只作为辅助信号；最终判定以最终状态 VLM 为准，
且如果 final UI 中出现了 forbidden 文本，直接判失败。AgentProg 自己的程序执行状态只记录，不参与评分。</p>

<h2>3. 结果总览（AgentProg，新规则）</h2>
<table>
  <thead><tr><th>#</th><th>任务</th><th>App</th><th>成功</th><th>模型调用</th><th>Agent 耗时</th><th>判定理由（截断）</th></tr></thead>
  <tbody>{''.join(result_rows)}</tbody>
</table>

<h2>4. 与 AppAgent 的对比（同一批任务、同一最终状态规则）</h2>
<table>
  <thead><tr><th>任务</th><th>App</th><th>AppAgent 旧严格规则</th><th>AppAgent 新最终状态规则</th><th>AgentProg 新规则</th><th>AppAgent 新规则理由（截断）</th></tr></thead>
  <tbody>{''.join(compare_rows)}</tbody>
</table>
<p class="muted">
汇总：AppAgent 旧严格 {appagent_old_success}/{len(ordered_ids)}；AppAgent 仅换判定规则（不重跑）
{appagent_new_success}/{len(ordered_ids)}；AgentProg 新规则 {success_count}/{len(ordered_ids)}。
AppAgent 的新规则分数来自其已完成的最终截图 + final UI 重新判定，不是重跑结果。
</p>

<h2>5. 逐任务证据</h2>
<p class="toc">目录：<ul class="toc">{toc}</ul></p>
{task_sections}

<h2>6. AgentProg 架构（来自源码）</h2>
<p>
AgentProg 的核心是 <b>Semantic Task Program (STP)</b>：模型先把任务写成一段带自然语言步骤、
条件和循环的程序（<code>workflow.ap</code>），执行器再把当前程序行翻译成 Python GUI 动作。
每一步有两个模型阶段：
</p>
<ul>
  <li><b>Code Generation：</b>给定当前程序行、变量、屏幕描述和 belief state，生成一段可执行 Python
      （例如 <code>mobile.click(view_description=...)</code>、<code>time.sleep(3)</code>）。</li>
  <li><b>Workflow Status Update：</b>根据执行结果决定程序计数器（WPC）是继续、跳过、跳出循环还是暂停修复。</li>
</ul>
<p>
上下文管理由执行树完成：已完成的分支、循环迭代和函数调用细节会被裁剪，变量通过 STP 的显式声明持久化；
belief state 维护“隐藏 UI 状态”的假设并在运行时校验。Grounding 使用 UI-TARS 风格的视觉定位：
把当前截图和 “Click on ….” 指令交给定位模型，返回点击坐标，再由 <code>mobile.click</code> 执行。
</p>

<h2>7. 配置与最小改动</h2>
<ul>
  <li><b>Agent 代码未重写。</b>直接调用 <code>third_party/AgentProg</code> 的
      <code>agentprog_pipeline</code>；STP、prompt、执行器、belief state、上下文管理均未改。</li>
  <li><b>主模型：</b>通过 CLI 参数 <code>--workflow_model_args.*</code> 与
      <code>--executor_model_args.*</code> 把默认的 <code>gemini/gemini-2.5-pro</code>
      改为 <code>openai/auto/gpt-6.1-sol</code>，base URL 指向本地 magpie；
      <code>completion_kwargs</code> 设为 <code>{{"temperature":1,"stream":false}}</code>，
      去掉默认的 Gemini <code>extra_body.thinking</code>。未改源码。</li>
  <li><b>UI-TARS grounding：</b><code>mobile_utils.py</code> 增加一个 <code>UITARS_MODEL</code>
      环境变量覆盖（默认仍是 <code>doubao-seed-1-8-251228</code>），本地设为
      <code>auto/gpt-6.1-sol</code>；<code>DOUBAO_BASE_URL</code>/<code>ARK_API_KEY</code>
      指向 magpie。</li>
  <li><b>接地 prompt 兼容：</b><code>ui_tars_utils.py</code> 的 API prompt 增加一行
      “坐标必须归一化到 0–1000”。这是为了让通用 VLM 按 doubao API 的坐标约定输出；
      不加这一行时本地 VLM 返回截图像素坐标，解析后会偏移约 2 倍。</li>
  <li><b>测试 App 映射：</b><code>mobile_utils.py</code> 的 <code>_PATTERN_TO_ACTIVITY</code>
      增加 Activity Diary、OmniNotes，并修正 Tasks.org 的 launcher activity；
      只影响 <code>start_app</code>/<code>kill_app</code> 的包名解析。</li>
  <li><b>运行器：</b><code>scripts/run_agentprog_tasks.py</code> 只做 App 重置/启动、pipeline 调用、
      模型 I/O 记录、最终截图/UI 抓取和判定；没有实现 Agent 策略。</li>
  <li><b>环境 setup：</b>每个任务前 <code>pm clear</code> + 启动；OmniNotes 的首次启动引导
      （6 页）和 Android 13+ 通知权限由 runner 在启动后处理
      （<code>dismiss_known_intro</code>、<code>pm grant POST_NOTIFICATIONS</code>），
      属于测试环境准备，不计入任务步骤，也不改变任何任务目标。</li>
</ul>

<h2>8. 局限与诚实说明</h2>
<ul>
  <li>每个任务只跑 1 次；真机存在动画、通知、输入法差异，单次结果不等于统计成功率。</li>
  <li>AgentProg 论文默认使用 Gemini-2.5-Pro 与 Volcengine Ark 的 UI-TARS-1.5；本报告改用本地
      magpie 的 <code>auto/gpt-6.1-sol</code> 作为主模型和 grounding 模型，属于兼容性替换，
      不能直接与论文数字对比。</li>
  <li>UI-TARS API prompt 增加了一行坐标归一化说明；这是本地 VLM 与 doubao API 坐标约定不一致导致的
      兼容性改动，不属于 AgentProg 原始 prompt。</li>
  <li>AgentProg 的 text-augmented 截图路径会先用一个描述模型读取真实截图并生成详细画面描述；
      后续 code generation / WPC 调用的 prompt 中，图片占位符没有注册成
      <code>Prompt.images</code>，日志显示为本地图片路径，模型依赖上一步的详细文本描述。
      UI-TARS grounding 始终使用真实截图。本报告未修改这一上游行为。</li>
  <li>最终状态判定依赖外部 VLM（<code>auto/gpt-6.1-sol</code>），可能存在视觉误读；报告同时保留
      确定性文本检查和原始截图，便于人工复核。</li>
  <li>没有读取 App 的 SQLite/SharedPreferences 等隐藏状态，只按用户可见的最终界面判定。</li>
  <li>AppAgent 的新规则分数是对旧最终截图的离线重判，不是重跑；旧严格结果仍保留在
      <code>runs/appagent/</code>。</li>
</ul>

<h2>9. 复现</h2>
<pre>cd E:/CodeE/vibe51/StarTrek
# 1) 安装（Python 3.12）
python -m venv .venv-agentprog
.venv-agentprog/Scripts/python -m pip install -e third_party/AgentProg
# 2) 配置网关
#    third_party/AgentProg/.env
#    GEMINI_BASE_URL=http://127.0.0.1:3425/v1
#    GEMINI_API_KEY=magpie
#    DOUBAO_BASE_URL=http://127.0.0.1:3425/v1
#    ARK_API_KEY=magpie
#    MODEL=openai/auto/gpt-6.1-sol
#    UITARS_MODEL=auto/gpt-6.1-sol
# 3) 跑一个任务
.venv-agentprog/Scripts/python scripts/run_agentprog_tasks.py --tasks diary_officework_session
# 4) 跑全部 8 个任务
.venv-agentprog/Scripts/python scripts/run_agentprog_tasks.py --tasks all
# 5) 生成报告
python scripts/build_agentprog_report.py</pre>

<h2>10. 文件清单</h2>
<ul>
  <li><code>benchmark/agent_tasks.yaml</code> — 8 个任务与最终状态检查</li>
  <li><code>third_party/AgentProg/</code> — 开源 baseline（Tsinghua AIR，arXiv 2512.10371）</li>
  <li><code>scripts/run_agentprog_tasks.py</code> — 薄运行器 + 模型 I/O 记录 + 最终状态判定</li>
  <li><code>scripts/build_agentprog_report.py</code> — 本报告生成器</li>
  <li><code>runs/agentprog/&lt;task&gt;/</code> — 最终截图、final UI、逐步截图、workflow.ap、
      模型 I/O、AgentProg 日志、判定器日志</li>
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
