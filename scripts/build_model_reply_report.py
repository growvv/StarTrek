#!/usr/bin/env python3
"""Build an HTML comparison of auto/* model replies to the same AgentProg request.

Reads runs/model_replies.json (written by scripts/bench_auto_models.py).
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_agentprog_report import CSS, esc  # noqa: E402

RUN = ROOT / "runs" / "repro_agentprog_readme"
REPLIES = ROOT / "runs" / "model_replies.json"
OUT = ROOT / "docs" / "reports" / "model-reply-comparison.html"

EXTRA_CSS = """
.prompt-box { max-height: 420px; overflow:auto; background:#0f172a; color:#e2e8f0;
  border-radius:10px; padding:16px 18px; font:12px/1.55 Consolas,monospace;
  white-space:pre-wrap; word-break:break-word; }
.reply { background:#fbfcfd; color:#101828; border:1px solid var(--line);
  border-radius:10px; padding:14px 16px; font:13px/1.6 Consolas,monospace;
  white-space:pre-wrap; word-break:break-word; margin:10px 0; }
.model-card { background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:18px 20px; margin:20px 0; }
.model-head { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:baseline;
  border-bottom:1px solid var(--line); padding-bottom:10px; margin-bottom:12px; }
.model-head h3 { margin:0; font-size:17px; }
.metric { font-size:13px; color:var(--muted); }
.metric b { color:var(--text); }
.tag { display:inline-block; font-size:12px; padding:2px 8px; border-radius:999px;
  background:#eef2f6; color:#334155; margin-right:6px; }
.tag.good { background:#e7f6ec; color:#067647; }
.tag.warn { background:#fff4e5; color:#b54708; }
details summary { cursor:pointer; color:var(--accent); font-size:13px;
  margin:8px 0; }
.error-box { background:#fff7f6; border:1px solid #f3c0bb; border-radius:10px;
  padding:14px 16px; color:#b42318; font:13px/1.6 Consolas,monospace; }
.expected { background:#f0f7ff; border:1px solid #c8ddf5; border-radius:10px;
  padding:12px 16px; font:13px/1.6 Consolas,monospace; white-space:pre-wrap; }
.callout { background:#fff; border:1px solid var(--line); border-left:5px solid var(--accent);
  border-radius:8px; padding:14px 18px; margin:16px 0; }
.callout ul { margin:8px 0 0; padding-left:22px; }
.callout li { margin:4px 0; }
"""


def form_tags(content: str, finish: str) -> str:
    tags = []
    declares = bool(
        re.search(r"\brecord(?:ed)?\b[^\n{]*\{[^}]+\}", content, re.IGNORECASE)
        or re.search(r"\bSet\s+\{[^}]+\}\s+to\b", content, re.IGNORECASE)
    )
    tags.append(
        '<span class="tag good">有变量声明</span>'
        if declares else '<span class="tag">名称直接内联，无变量</span>'
    )
    if re.search(r'\bIn\s+(the\s+)?["“]?Contacts', content, re.IGNORECASE):
        tags.append('<span class="tag good">显式指定 Contacts App</span>')
    else:
        tags.append('<span class="tag warn">未显式指定 App</span>')
    if "```" in content:
        tags.append('<span class="tag">带 Markdown 代码块</span>')
    if finish == "length":
        tags.append('<span class="tag warn">被 max_tokens 截断</span>')
    return "".join(tags)


def main() -> int:
    replies = json.loads(REPLIES.read_text(encoding="utf-8"))
    calls = [
        json.loads(line)
        for line in (RUN / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    request_text = calls[0]["request"][0]["content"][0]["text"]
    ok = sum(1 for row in replies if "error" not in row)
    fastest = next((row for row in replies if "error" not in row), None)

    summary_rows = []
    cards = []
    for index, row in enumerate(replies, 1):
        if "error" in row:
            summary_rows.append(
                "<tr class='err'><td>—</td>"
                f"<td><code>{esc(row['model'])}</code></td><td>—</td><td>失败</td>"
                "<td colspan='3'></td></tr>"
            )
            cards.append(
                f'<div class="model-card" id="m{index}">'
                f'<div class="model-head"><h3>{esc(row["model"])}</h3>'
                '<span class="tag warn">请求失败</span></div>'
                f'<div class="error-box">{esc(row["error"])}</div></div>'
            )
            continue

        anchor = f"m{index}"
        summary_rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f'<td><a href="#{anchor}"><code>{esc(row["model"])}</code></a></td>'
            f"<td><b>{row['seconds']}s</b></td>"
            f"<td>{esc(row.get('finish_reason'))}</td>"
            f"<td>{esc(row.get('completion_tokens'))}</td>"
            f"<td>{esc(row.get('content_chars'))}</td>"
            f"<td>{esc(row.get('reasoning_chars'))}</td>"
            "</tr>"
        )
        reasoning = row.get("reasoning") or ""
        reasoning_html = ""
        if reasoning:
            reasoning_html = (
                "<details><summary>展开思考过程（"
                f"{len(reasoning)} 字符）</summary>"
                f'<pre class="reply">{esc(reasoning)}</pre></details>'
            )
        cards.append(
            f'<div class="model-card" id="{anchor}">'
            '<div class="model-head">'
            f'<h3>{esc(row["model"])}</h3>'
            f'<span class="metric">耗时 <b>{row["seconds"]}s</b></span>'
            f'<span class="metric">finish <b>{esc(row.get("finish_reason"))}</b></span>'
            f'<span class="metric">输出 <b>{esc(row.get("completion_tokens"))}</b> tokens</span>'
            f'<span class="metric">正文 <b>{row.get("content_chars")}</b> 字符</span>'
            "</div>"
            f'<div>{form_tags(row.get("content") or "", row.get("finish_reason") or "")}</div>'
            f'<pre class="reply">{esc(row.get("content") or "（空回复）")}</pre>'
            f"{reasoning_html}"
            "</div>"
        )

    return_html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>auto/ 模型回复对比 — AgentProg workflow 请求</title>
<style>{CSS}{EXTRA_CSS}</style></head><body>
<main>
<h1>同一请求下 auto/ 模型回复对比</h1>
<p class="muted">请求来自 AgentProg README 示例复现的第 1 次调用
（workflow 生成，{len(request_text)} 字符）。{ok}/{len(replies)} 个模型成功返回；
最快 <code>{esc(fastest['model'] if fastest else '—')}</code>
（{fastest['seconds'] if fastest else '—'}s）。所有模型使用相同 messages、
<code>max_tokens=4000</code>、默认 temperature、非流式；6 路并发。
网关延迟波动很大（同一模型两轮实测可能差数倍），本节耗时只对应本轮回合，
排序请以复现报告第 4 节的并发测速表为主。</p>

<h2>评测基准：期望的 STP 形式</h2>
<p>上游 README 示例任务为 <code>create a new contact named agent prog in contacts app.</code>。
本次复现实际生成的 workflow 是（hy4free，上游 pipeline 用它跑通了点击流程）：</p>
<div class="expected">Record "agent prog" as {{contact_name}}
In the Contacts App, create a new contact named {{contact_name}}, and save the contact.</div>
<p class="muted">DSL 也允许 <code>Set {{contact_name}} to "agent prog"</code> 这种变量声明。
下面标注：是否有变量声明、是否显式指定 Contacts App、是否被 max_tokens 截断；
不自动判定语义正确性，质量请看每个模型的原始正文自行判断。</p>

<div class="callout">
  <b>一眼观察（基于本轮原始回复）：</b>
  16 个成功模型都正确理解了任务；除 hy4free 被 <code>max_tokens</code> 截断外，
  其余回复都包含明确的保存步骤。
  <ul>
    <li><b>最短完整</b>：<code>auto/gpt-6-luna</code>（59 tokens，3 步）；<code>gpt-6-sol</code> /
        <code>gpt-6.1-sol</code> 多一条验证步骤。</li>
    <li><b>变量声明</b>：本轮只有 <code>auto/hy4free</code> 用了
        <code>Set {{contact_name}} to "agent prog"</code>；其余把名称直接写进步骤。
        两种写法 DSL 都允许。</li>
    <li><b>需要留意</b>：<code>glm-5.2</code> 建议拆成 first name “agent” / last name “prog”；
        <code>glm-5.3</code> 系增加了搜索/点击“+”等 UI 细节与验证步骤，执行路径更长。</li>
    <li><b>网关失败</b>：<code>kimi-k3</code>（503）、<code>hy4std</code>（502，输出全耗在思考段）。</li>
  </ul>
</div>

<h2>结果总览</h2>
<table><thead><tr><th>#</th><th>模型</th><th>耗时</th><th>finish</th>
  <th>输出 token</th><th>正文 chars</th><th>思考 chars</th></tr></thead>
  <tbody>{''.join(summary_rows)}</tbody></table>

<div class="callout">
  <b>为什么 GPT 系列的“思考 chars”都是 0？</b>
  这是网关的默认行为，不是报告漏采。实测（<code>runs/gpt_reasoning_probe.json</code>）：
  <ul>
    <li>不传任何开关时，<code>gpt-6-sol</code>、<code>gpt-5.6-sol</code> 的返回里
        连 <code>reasoning_content</code> 字段都没有，completion tokens 只覆盖正文。</li>
    <li><code>gpt-6-sol</code> 传 <code>reasoning_effort=high</code> 后才出现
        <code>reasoning_content</code>，但这段思考只有 24 字符；
        <code>reasoning_effort=low</code>、<code>extra_body.reasoning</code>、
        <code>extra_body.thinking</code> 都没有效果。</li>
    <li><code>gpt-5.6-sol</code> 在上述所有开关下都没有返回思考内容。</li>
    <li>对照：<code>deepseek-v4.1-flash</code>、<code>hy4free</code>、<code>hy3</code>、
        <code>minimax</code> 默认就返回 1k–17k 字符的 reasoning。</li>
  </ul>
  结论：GPT 系列默认是“非思考”模式，且对这个简单任务即使开 high 也几乎不思考；
  这不代表它不能推理，只代表本次请求没有触发/开启。
</div>

<h2>完整请求（原样，未修改）</h2>
<details><summary>展开请求（{len(request_text)} 字符）</summary>
<pre class="prompt-box">{html.escape(request_text)}</pre></details>

<h2>各模型回复（按耗时排序）</h2>
{''.join(cards)}

<p class="muted">说明：耗时包含网关排队与模型生成时间；思考过程默认折叠。
高输出 token 不一定代表质量好，可能是重复或冗长。回复内容原样展示，
HTML 特殊字符已转义。</p>
</main></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(return_html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
