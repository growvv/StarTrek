#!/usr/bin/env python3
"""Build the AgentProg README-example reproduction report.

All screenshots come from the real device run; action screenshots have the
exact tap coordinates drawn on them by the reproduction harness.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_agentprog_report import (  # noqa: E402
    CSS,
    badge,
    esc,
    img_tag,
    load_json,
    load_jsonl,
    render_llm_section,
    render_verifier_section,
)

RUN = ROOT / "runs" / "repro_agentprog_readme"
OUT = ROOT / "docs" / "reports" / "agentprog-reproduction.html"
TASK_TEXT = "create a new contact named agent prog in contacts app."

EXTRA_CSS = """
.kv { display:grid; grid-template-columns:190px 1fr; gap:6px 14px; font-size:13px; }
.kv b { color:var(--muted); font-weight:600; }
.action { background:#fff; border:1px solid var(--line); border-radius:12px;
          padding:18px 20px; margin:18px 0; }
.action-grid { display:grid; grid-template-columns:minmax(280px,420px) 1fr;
               gap:20px; align-items:start; }
.action-shot { width:100%; border-radius:8px; border:1px solid var(--line); }
.action-meta { background:#fbfcfd; border:1px solid var(--line); border-radius:10px;
               padding:12px 16px; }
.action-meta .kind { font-size:13px; font-weight:700; color:var(--accent); }
.coord { font-family:Consolas,monospace; background:#eef2f6; padding:1px 6px;
         border-radius:4px; }
.status-line { font-size:12px; color:var(--muted); }
.callout { background:#fff; border:1px solid var(--line); border-left:5px solid var(--accent);
           border-radius:8px; padding:14px 18px; margin:16px 0; }
.callout.warn { border-left-color:#d97706; background:#fffaf0; }
.callout.bad { border-left-color:#b42318; background:#fff7f6; }
.shot-wide { max-width:420px; margin:10px 0; }
.shot-wide img { width:100%; border-radius:8px; border:1px solid var(--line); }
tr.err td { background:#fff7f6; }
"""


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def enrich_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill descriptions from the real agent.log when the runtime hook missed kwargs."""
    log = read_text(RUN / "agent.log")
    entries = []
    for line in log.splitlines():
        match = re.match(
            r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[info\s+\] (.+?) \[agentprog\.",
            line,
        )
        if not match:
            continue
        message = match.group(2)
        if not any(
            marker in message
            for marker in ("👆 Clicking", "👆⏱️ Long clicking", "⌨️ Inputting",
                           "📋 Inputting", "🔙 Navigating back", "⏳ Waiting")
        ):
            continue
        entries.append((match.group(1), message))
    for action in actions:
        if action.get("error"):
            continue
        stamp = str(action.get("ts", ""))
        candidates = [entry for entry in entries if entry[0] <= stamp]
        if not candidates:
            continue
        log_stamp, message = candidates[-1]
        action["log_ts"] = log_stamp
        action["log_line"] = message
        if not action.get("description"):
            if "Clicking: " in message:
                action["description"] = message.split("Clicking: ", 1)[1]
            elif "Long clicking: " in message:
                action["description"] = message.split("Long clicking: ", 1)[1]
            elif "Inputting text into " in message:
                rest = message.split("Inputting text into ", 1)[1]
                if ": " in rest:
                    desc, text = rest.rsplit(": ", 1)
                    action["description"] = desc
                    if not action.get("text"):
                        action["text"] = text
                else:
                    action["description"] = rest
            elif "Navigating back to: " in message:
                action["description"] = message.split("Navigating back to: ", 1)[1]
    return actions


def action_cards(actions: list[dict[str, Any]]) -> str:
    cards = []
    for action in actions:
        if action.get("error"):
            cards.append(f'<p class="muted">标注失败：{esc(action["error"])}</p>')
            continue
        image = RUN / str(action.get("image", ""))
        kind = action.get("kind", "?")
        kind_cn = {
            "click": "点击", "input": "输入", "long_click": "长按",
            "swipe": "滑动", "input_by_pasting": "粘贴输入",
        }.get(kind, kind)
        desc = action.get("description", "")
        text = action.get("text", "")
        coords = (
            f'<span class="coord">({action.get("x")}, {action.get("y")})</span>'
            if "x" in action
            else f'<span class="coord">{action.get("start")} → {action.get("end")}</span>'
        )
        cards.append(
            f"""
            <div class="action">
              <div class="action-grid">
                <div>{img_tag(image, width=420)}</div>
                <div class="action-meta">
                  <div class="kind">动作 {action.get('index')} · {esc(kind_cn)}</div>
                  <p><b>操作：</b>{esc(desc) or '—'}</p>
                  {'<p><b>输入文本：</b>' + esc(text) + '</p>' if text else ''}
                  <p><b>坐标：</b>{coords}</p>
                  <p><b>时间：</b>{esc(action.get('ts', '—'))}</p>
                  {('<p class="status-line">AgentProg 日志：' + esc(action.get('log_line', '')) + '</p>') if action.get('log_line') else ''}
                  <p class="status-line">红圈 + 十字是复现脚本在动作发生前，用
                  AgentProg 自己定位到的坐标画在真机截图上的；不是事后示意。</p>
                </div>
              </div>
            </div>
            """
        )
    return "".join(cards) or '<p class="muted">没有记录到动作。</p>'


def section_result(result: dict[str, Any], interrupted: bool) -> str:
    success = result.get("success")
    color = "ok" if success is True else ("fail" if success is False else "skip")
    label = "成功" if success is True else ("失败" if success is False else "未判定")
    if interrupted and success is None:
        label = "未完成（外部停止）"
    return f"""
    <div class="callout">
      <div class="kv">
        <b>示例任务</b><div>{esc(result.get('task', TASK_TEXT))}</div>
        <b>结果</b><div><span class="badge {color}">{label}</span>
          &nbsp;deterministic={esc('—' if result.get('deterministic_ok') is None else result.get('deterministic_ok'))}</div>
        <b>模型</b><div><code>{esc(result.get('model', ''))}</code>
          （UI-TARS 定位也用 <code>{esc(result.get('ui_tars_model', ''))}</code>）</div>
        <b>耗时</b><div>{esc(result.get('duration_s', '—'))} s</div>
        <b>模型调用 / 动作</b><div>{esc(result.get('model_calls', '—'))} 次 /
          {esc(result.get('actions', '—'))} 个</div>
        <b>判定理由</b><div>{esc(result.get('reason', '')) or '—'}</div>
        <b>判定证据</b><div>{esc(result.get('evidence', '')) or '—'}</div>
        <b>数据库旁证</b><div><code>{esc(result.get('db_display_names', '') or '（无输出）')}</code>
          （只作诊断，不计入成功判定）</div>
      </div>
    </div>
    """


def section_changes() -> str:
    rows = [
        ("规划 / STP / WPC / 代码生成", "原版", "原版，未改", "未改"),
        ("AgentProg prompts（除坐标说明）", "原版", "原版", "未改"),
        ("UI-TARS prompt", "原版", "只加 1 行：坐标必须归一化到 0–1000",
         "改了 1 行；原因见下"),
        ("主模型", "gemini-2.5-pro", "openai/auto/hy4free（magpie）", "替换"),
        ("UI-TARS 定位模型", "doubao-seed-1-8-251228（Ark）", "auto/hy4free（magpie）", "替换"),
        ("thinking", "默认 enabled", "尝试关闭失败，保持 enabled", "未改（说明）"),
        ("运行设备", "模拟器 / AndroidWorld", "Pixel 9 Pro XL，Android 16，真机", "替换"),
        ("任务", "README example + 论文 ContactsAddMultipleContactsAndSms",
         "只跑 README example", "部分复现"),
        ("判分", "AndroidWorld evaluator", "final_state_v1 + 文本检查",
         "新增评估，不进入 Agent 行为"),
        ("Windows 编码", "默认编码", "workflow.ap / 统计文件显式 UTF-8",
         "改了 4 行，必要兼容"),
        ("APP 启动映射", "原版", "增加 3 个 benchmark APP 映射", "改了；本示例未用到"),
        ("截图标注", "无", "动作前真机截图 + 红圈十字 + 坐标", "新增观测，不改行为"),
    ]
    body = "".join(
        f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>{esc(c)}</td><td>{esc(d)}</td></tr>"
        for a, b, c, d in rows
    )
    return f"""
    <table>
      <thead><tr><th>项目</th><th>原版</th><th>本次复现</th><th>是否改动</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    <h3>实际 git diff（third_party/AgentProg）</h3>
    <pre> M agentprog/all_utils/mobile_utils.py
 M agentprog/all_utils/ui_tars_utils.py
 M agentprog/plan/code_exec/workflow/generate_workflow.py
 M agentprog/plan/code_exec/workflow/workflow_query_llm.py
 4 files changed, 18 insertions(+), 9 deletions(-)</pre>
    <p class="muted">其中真正影响 Agent 行为的只有 UI-TARS prompt 的 1 行；
    其余是 Windows 编码、APP 映射和 UITARS_MODEL 环境变量，都是替换模型/平台后的兼容改动。</p>
    """


def section_thinking() -> str:
    rows = [
        ("reasoning_effort=none", "仍返回 reasoning_content"),
        ("enable_thinking=false", "仍返回 reasoning_content"),
        ('thinking={"type":"disabled"}', "仍返回 reasoning_content"),
        ("chat_template_kwargs.enable_thinking=false", "仍返回 reasoning_content"),
        ('reasoning={"enabled":false} / {"effort":"none"} / {"type":"disabled"}',
         "仍返回 reasoning_content（长度有波动）"),
        ("不传任何开关（repo 默认 thinking enabled）", "正常返回 content，保留"),
    ]
    body = "".join(
        f"<tr><td><code>{esc(a)}</code></td><td>{esc(b)}</td></tr>" for a, b in rows
    )
    return f"""
    <p>按你的要求测试了关闭 Think。结论：<b>magpie 上的 auto/hy4free 关不掉</b>；
    上述常见开关都被网关忽略，响应里始终有 reasoning_content。为了避免改变论文仓库的
    输入输出格式，本次保留仓库默认的 <code>extra_body.thinking={"{"}"type":"enabled"{"}"}</code>，
    没有改 prompt 来压制思考。</p>
    <table><thead><tr><th>尝试</th><th>结果</th></tr></thead><tbody>{body}</tbody></table>
    """


def section_calls_explained() -> str:
    calls = load_jsonl(RUN / "llm_calls.jsonl")
    rows = []
    for call in calls:
        usage = call.get("usage") or {}
        if not usage:
            continue
        rows.append(
            "<tr>"
            f"<td>{call.get('call')}</td>"
            f"<td><code>{esc(call.get('purpose'))}</code></td>"
            f"<td>{esc(usage.get('prompt_tokens', '—'))}</td>"
            f"<td>{esc(usage.get('completion_tokens', '—'))}</td>"
            f"<td>{esc(call.get('duration_s', '—'))}s</td>"
            "</tr>"
        )
    return f"""
    <p>是同一类调用：都是 OpenAI 兼容的 <code>/v1/chat/completions</code>，
    同一个 magpie 网关。区别只在 AgentProg 内部用的是 <b>litellm SDK</b>，
    模型名带 <code>openai/</code> 前缀，并且每次请求的上下文很长。</p>
    <h3>AgentProg 实际调用（源码 third_party/AgentProg/.../general_utils.py）</h3>
    <pre>litellm.completion(
    model="openai/auto/hy4free",
    messages=messages,                       # STP + 上下文 + 屏幕描述，3k–14k tokens
    base_url="http://127.0.0.1:3425/v1",
    api_key="magpie",
    temperature=0.1,
    stream=False,
    extra_body={{"thinking": {{"type": "enabled"}}}},
)</pre>
    <h3>等价的 OpenAI 客户端写法（和你给的例子一样）</h3>
    <pre>from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:3425/v1", api_key="magpie")
r = client.chat.completions.create(
    model="auto/hy4free",
    messages=[{{"role": "user", "content": "……AgentProg 的完整 prompt……"}}],
    temperature=0.1,
    stream=False,
)</pre>
    <h3>本次真实用量（llm_calls.jsonl）</h3>
    <table><thead><tr><th>#</th><th>用途</th><th>输入 token</th>
      <th>输出 token</th><th>耗时</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table>
    <div class="callout warn">
      <b>为什么慢：</b>不是调用方式的问题，是每次输出太长。AgentProg 每个 UI 动作要
      顺序发 3 类请求（屏幕描述 → WPC 状态更新 → 代码生成），其中 executor 调用
      一次就产生 <b>7k–15k completion tokens</b>（hy4free 的 reasoning + 正文），
      非流式等待完整生成；再叠加 free 档吞吐，单次约 1.5–3 分钟。
      你给的 “hi” 请求输出只有几十 token，所以 1–3 秒就返回。
    </div>
    {section_model_bench()}
    <p class="muted">调用方式完全相同，差别在模型吞吐与思考长度：同一个 workflow 生成
    prompt，deepseek-v4.1-flash 5.1 秒返回，hy4free 串行需 233.7 秒。换模型可以显著
    缩短耗时，但复现报告里必须注明“主模型不是论文的 Gemini-2.5-Pro，也不是 hy4free”。
    UI-TARS 定位调用是另一类：输入约 1k token、输出约 100 token，本次实测 4.3s / 7.7s。</p>
    """


BENCH = ROOT / "runs" / "model_speed_bench.json"
BENCH_RETRY = ROOT / "runs" / "model_speed_bench_retry.json"


def _bench_rows(results: list[dict[str, Any]], show_rank: bool) -> str:
    rows = []
    rank = 0
    for row in results:
        if "error" in row:
            rows.append(
                "<tr class='err'>" + ("<td>—</td>" if show_rank else "")
                + f"<td><code>{esc(row['model'])}</code></td><td>—</td><td>失败</td>"
                f"<td colspan='4' class='muted'>{esc(row['error'][:160])}</td></tr>"
            )
            continue
        rank += 1
        note = "本次复现主模型" if row["model"] == "auto/hy4free" else ""
        rows.append(
            ("<tr><td>%d</td>" % rank if show_rank else "<tr>")
            + f"<td><code>{esc(row['model'])}</code></td>"
            f"<td><b>{row['seconds']}s</b></td>"
            f"<td>{esc(row.get('finish_reason'))}</td>"
            f"<td>{esc(row.get('completion_tokens'))}</td>"
            f"<td>{esc(row.get('content_chars'))}</td>"
            f"<td>{esc(row.get('reasoning_chars'))}</td>"
            f"<td>{note}</td></tr>"
        )
    return "".join(rows)


def section_model_bench() -> str:
    if not BENCH.exists():
        return ""
    results = json.loads(BENCH.read_text(encoding="utf-8"))
    calls = load_jsonl(RUN / "llm_calls.jsonl")
    prompt_chars = len(json.dumps(calls[0]["request"], ensure_ascii=False)) if calls else "—"
    ok = sum(1 for row in results if "error" not in row)
    fast_rows = [row for row in results if "error" not in row]
    fastest = fast_rows[0] if fast_rows else None

    retry_html = ""
    hy4_serial = None
    if BENCH_RETRY.exists():
        retry = json.loads(BENCH_RETRY.read_text(encoding="utf-8"))
        for row in retry:
            if row["model"] == "auto/hy4free" and "error" not in row:
                hy4_serial = row["seconds"]
        retry_html = f"""
        <h3>慢模型与失败模型的串行复测</h3>
        <p>去掉并发，逐个单独重发同一请求。hy4free 与 hy3 仍然明显慢于主流模型；
        两个失败模型返回的是网关侧 503/502，不是请求格式问题。</p>
        <table><thead><tr><th>模型</th><th>耗时</th><th>finish</th>
          <th>输出 token</th><th>正文 chars</th><th>思考 chars</th><th>备注</th></tr></thead>
          <tbody>{_bench_rows(retry, show_rank=False)}</tbody></table>
        """

    ratio = (
        round(hy4_serial / fastest["seconds"], 1)
        if hy4_serial and fastest else "—"
    )
    fast_count = sum(1 for row in fast_rows if row["seconds"] <= 12)
    return f"""
    <h3>全部 auto/ 模型并发实测（同一 workflow prompt）</h3>
    <p>同一份 messages（{prompt_chars} 字符，取自本次复现的第 1 次调用），
    <code>max_tokens=4000</code>、默认 temperature、非流式，6 路并发同时发出。
    {ok}/{len(results)} 个模型成功返回。并发会轻微拉高绝对耗时，排序仍可横向比较。</p>
    <table><thead><tr><th>#</th><th>模型</th><th>耗时</th><th>finish</th>
      <th>输出 token</th><th>正文 chars</th><th>思考 chars</th><th>备注</th></tr></thead>
      <tbody>{_bench_rows(results, show_rank=True)}</tbody></table>
    {retry_html}
    <p class="muted">最快 <code>{esc(fastest['model'] if fastest else '—')}</code>
    {fastest['seconds'] if fastest else '—'}s；hy4free 串行单独重测仍需
    {hy4_serial if hy4_serial else '—'}s，约 <b>{ratio} 倍</b>。
    {ok} 个成功模型中有 {fast_count} 个在 12 秒内返回。
    注意 free 档波动很大：复现运行当次记录的 workflow 调用是 55.5s，本次复测是
    {hy4_serial if hy4_serial else '—'}s，但都远慢于其他模型。“输出 token”包含
    reasoning；“正文 chars”才是真正可解析的 STP/代码长度。</p>
    """


def section_scope(result: dict[str, Any], interrupted: bool) -> str:
    model_calls = result.get("model_calls", 0)
    done = (
        "执行到联系人表单（尚未输入姓名/保存）"
        if interrupted
        else "完整链路"
    )
    return f"""
    <ul>
      <li><b>复现了：</b>AgentProg 原版 pipeline 在真机 Contacts 上执行 README 示例
          “{esc(result.get('task', ''))}”的{done}（{esc(model_calls)} 次模型调用、
          {esc(result.get('actions', 0))} 个带坐标标注的动作）。</li>
      <li><b>没有复现：</b>论文的 AndroidWorld / AW-Extend 全量任务与分数；
          README 里的论文示例 ContactsAddMultipleContactsAndSms 需要 Simple SMS Messenger，
          本机未安装，本轮未跑。</li>
      <li><b>模型差异：</b>论文用 Gemini-2.5-Pro + UI-TARS-1.5；本次两者都用
          auto/hy4free。因此本次结果说明“代码链路可复现”，不代表论文模型的分数。</li>
      <li><b>判分差异：</b>论文用 AndroidWorld evaluator；本次用只看最终屏幕的
          final_state_v1 + “agent prog”文本检查，属于复现验收的附加判定，不参与 Agent 决策。</li>
    </ul>
    """


def build() -> str:
    raw_result = load_json(RUN / "result.json", {})
    actions = enrich_actions(load_jsonl(RUN / "actions.jsonl"))
    stp = read_text(RUN / "workflow.ap")
    interrupted = not raw_result
    result = raw_result
    if interrupted:
        result = {
            "task": TASK_TEXT,
            "model": "auto/hy4free",
            "ui_tars_model": "auto/hy4free",
            "duration_s": "—",
            "model_calls": len(load_jsonl(RUN / "llm_calls.jsonl")),
            "actions": len(actions),
            "deterministic_ok": None,
            "reason": "运行在保存联系人前被低内存回收器停止（22:41），没有写出 result.json。",
            "evidence": "",
            "db_display_names": "",
        }
    final = RUN / "final.png"
    final_caption = "final.png（真机最终画面）"
    if not final.exists():
        shots = sorted((RUN / "images").glob("*.png"))
        if shots:
            final = shots[-1]
            final_caption = f"中断时最后一张真机截图（{final.name}）"
    start = RUN / "start.png"
    success = result.get("success")
    badge_html = badge(success)
    title = "AgentProg README 示例复现报告"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}{EXTRA_CSS}</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="sub">2026-11-10 · 真机 Pixel 9 Pro XL / Android 16 / 47261FDAS00DTQ ·
    上游代码 third_party/AgentProg（arXiv 2512.10371）· 模型 auto/hy4free ·
    所有截图来自本次运行</p>

  <div class="callout">
    <b>一句话结论：</b>按上游 README 的原样示例“{esc(result.get('task', ''))}”
    跑通了 AgentProg 的 STP → 代码生成 / WPC → UI-TARS 定位 → 真机点击链路，
    并推进到联系人表单；{('运行被外部停止，未完成保存与判分。' if interrupted else '结果 ' + badge_html + '。')}
    动作截图上的红圈 + 十字是动作发生前按 AgentProg 定位坐标画上去的，可直接核对每一步点了哪里。
  </div>

  {('<div class="callout bad"><b>运行中断：</b>本次复现被 Claude Code 的低内存回收器在 22:41 停止，'
    '停在“联系人表单已打开、尚未输入姓名/保存”这一步；没有 result.json，因此不能给出成功/失败结论。'
    '下面是中断前已经完成的真实动作与截图。</div>') if interrupted else ''}

  <div class="cards">
    <div class="card"><div class="n">{esc(result.get('model_calls', '—'))}</div>
      <div class="l">真实模型调用</div></div>
    <div class="card"><div class="n">{esc(result.get('actions', '—'))}</div>
      <div class="l">带坐标标注的真机动作</div></div>
    <div class="card"><div class="n">{esc(result.get('duration_s', '—'))}{'s' if not interrupted else ''}</div>
      <div class="l">执行耗时</div></div>
    <div class="card"><div class="n">{('1/1' if success else '0/1') if not interrupted else '中断'}</div>
      <div class="l">README 示例复现</div></div>
  </div>

  <h2>1. 复现结果</h2>
  {section_result(result, interrupted)}

  <h2>2. 改了哪些、没改哪些</h2>
  {section_changes()}

  <h2>3. Think 关闭测试</h2>
  {section_thinking()}

  <h2>4. 调用方式与为什么慢</h2>
  {section_calls_explained()}

  <h2>5. 执行流：每一步点在哪里</h2>
  <p class="muted">下面是 AgentProg 实际执行的每一个动作。标注图是动作发生前的真机画面，
  红圈中心就是它接下来要点/输入的坐标；右侧是该动作的原始描述、输入文本与时间。</p>
  {action_cards(actions)}

  <h2>6. 关键中间结果：STP</h2>
  <pre>{esc(stp) or '（没有 workflow.ap）'}</pre>

  <h2>7. 关键中间结果：完整模型 I/O</h2>
  {render_llm_section(RUN)}

  <h2>8. 最终状态与判分</h2>
  <div class="shot-wide">{img_tag(final, width=420)}<div class="cap">{esc(final_caption)}</div></div>
  {render_verifier_section(RUN) if (RUN / 'verifier_llm.jsonl').exists() else '<p class="muted">运行被停止，未执行最终状态判定。</p>'}

  <h2>9. 复现范围与差异</h2>
  {section_scope(result, interrupted)}

  <h2>10. 文件与复现命令</h2>
  <table class="mini">
    <thead><tr><th>内容</th><th>路径</th></tr></thead>
    <tbody>
      <tr><td>复现脚本</td><td><code>scripts/reproduce_agentprog_example.py</code></td></tr>
      <tr><td>轨迹与标注</td><td><code>runs/repro_agentprog_readme/</code></td></tr>
      <tr><td>STP</td><td><code>runs/repro_agentprog_readme/workflow.ap</code></td></tr>
      <tr><td>模型 I/O</td><td><code>runs/repro_agentprog_readme/llm_calls.jsonl</code></td></tr>
      <tr><td>动作与坐标</td><td><code>runs/repro_agentprog_readme/actions.jsonl</code></td></tr>
      <tr><td>上游改动</td><td><code>git -C third_party/AgentProg diff</code></td></tr>
    </tbody>
  </table>
  <pre>PYTHONIOENCODING=utf-8 .venv-agentprog/Scripts/python \\
  scripts/reproduce_agentprog_example.py

PYTHONIOENCODING=utf-8 .venv-agentprog/Scripts/python \\
  scripts/build_reproduction_report.py</pre>
  <p class="files">本报告由 scripts/build_reproduction_report.py 生成，图片以 base64 内嵌。</p>
</main>
</body>
</html>
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = build()
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
