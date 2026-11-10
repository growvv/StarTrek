#!/usr/bin/env python3
"""Build the AgentProg explainer page.

Layout is modelled on the MemGUI-Agent academic project page
(https://memgui-agent.github.io/): fixed nav, serif hero, kickered sections,
soft cards over a pale grid background. All claims are tied to the paper
(arXiv 2512.10371) and to our real device runs.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "repro_agentprog_readme"
LUNA = ROOT / "runs" / "agentprog_luna"
OUT = ROOT / "docs" / "reports" / "agentprog-explained.html"

ARXIV = "https://arxiv.org/abs/2512.10371"
CODE = "https://github.com/MobileLLM/AgentProg"
REFERENCE = "https://memgui-agent.github.io/"

CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600..800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap");
:root {
  --paper:#f7f9fc; --surface:#fff; --ink:#172033; --muted:#647086; --quiet:#8d9aad;
  --line:#dfe7f0; --blue:#246bfe; --teal:#008c83; --violet:#7a48cf;
  --gold:#c7831b; --rose:#d64d82; --shadow:0 18px 46px rgba(42,65,100,.10);
  --radius:18px; --mono:"JetBrains Mono","SFMono-Regular",Consolas,monospace;
  --display:"Fraunces",Georgia,serif;
  --sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; color:var(--ink); font-family:var(--sans); line-height:1.65;
  background:linear-gradient(180deg,#eef6ff 0,var(--paper) 620px),var(--paper); }
body::before { content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
  background-image:linear-gradient(rgba(36,107,254,.045) 1px,transparent 1px),
    linear-gradient(90deg,rgba(36,107,254,.045) 1px,transparent 1px);
  background-size:36px 36px; mask-image:linear-gradient(180deg,#000 0,transparent 780px); }
a { color:var(--teal); text-decoration:none; }
a:hover { text-decoration:underline; text-underline-offset:4px; }
img { max-width:100%; }
.site-nav { position:fixed; top:0; left:0; right:0; z-index:30;
  border-bottom:1px solid rgba(223,231,240,.66); background:rgba(255,255,255,.78);
  backdrop-filter:blur(18px) saturate(160%); }
.nav-inner { width:min(1220px,calc(100% - 40px)); min-height:66px; margin:0 auto;
  display:flex; align-items:center; justify-content:space-between; gap:18px; }
.brand { color:var(--ink); font-family:var(--display); font-size:1.3rem;
  font-weight:780; line-height:1; }
.brand span { color:var(--violet); }
.nav-links { display:flex; gap:20px; flex-wrap:wrap; justify-content:flex-end; }
.nav-links a { color:#40506a; font-family:var(--mono); font-size:.76rem;
  font-weight:700; letter-spacing:.02em; }
.nav-links a:hover { color:var(--violet); text-decoration:none; }
.hero { padding:112px 0 12px; }
.hero-inner { width:min(1120px,calc(100% - 48px)); margin:0 auto; text-align:center; }
.eyebrow,.kicker { margin:0 0 14px; color:var(--violet); font-family:var(--mono);
  font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
h1 { max-width:1080px; margin:0 auto; font-family:var(--display);
  font-size:clamp(2.3rem,3vw,2.95rem); font-weight:780; line-height:1.08; }
.hero-sub { margin:14px auto 0; color:#354258; font-size:1.08rem; max-width:780px; }
.hero-authors { max-width:900px; margin:16px auto 0; color:#40506a;
  font-size:.96rem; font-weight:650; line-height:1.58; }
.hero-authors sup,.hero-affiliations sup { color:var(--violet); font-size:.72em; }
.hero-affiliations { margin:8px auto 0; color:var(--muted); font-size:.94rem; font-weight:600; }
.hero-actions { display:flex; flex-wrap:wrap; justify-content:center; gap:12px;
  margin:24px auto 0; max-width:900px; }
.button { display:inline-flex; align-items:center; justify-content:center; gap:8px;
  min-height:42px; padding:11px 20px; border:1px solid var(--line); border-radius:999px;
  background:#fff; color:var(--ink); box-shadow:0 2px 8px rgba(15,23,42,.05);
  font-family:var(--mono); font-size:.76rem; font-weight:700; line-height:1;
  transition:transform .18s ease, box-shadow .18s ease; }
.button:hover { text-decoration:none; transform:translateY(-2px);
  box-shadow:0 12px 24px rgba(122,72,207,.16); }
.button.primary { border-color:var(--ink); background:var(--ink); color:#fff; }
.button.accent { border-color:rgba(122,72,207,.28); background:#f4f0ff; color:#5d39b8; }
.button.teal { border-color:rgba(0,140,131,.24); background:#e9fbf8; color:#08766f; }
.stats { width:min(1120px,calc(100% - 48px)); margin:34px auto 0;
  display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.stat { background:rgba(255,255,255,.88); border:1px solid var(--line);
  border-radius:16px; padding:18px 20px; box-shadow:var(--shadow); text-align:left; }
.stat b { display:block; font-family:var(--display); font-size:2rem; line-height:1.1; }
.stat span { color:var(--muted); font-size:.82rem; }
.section { padding:82px 0; }
.section.alt { background:rgba(238,246,249,.72); }
.wrap { width:min(1180px,calc(100% - 40px)); margin:0 auto; }
.section-head { display:grid; grid-template-columns:minmax(0,.9fr) minmax(320px,.72fr);
  gap:52px; align-items:end; margin-bottom:28px; }
h2 { margin:0; font-family:var(--display); font-size:clamp(2.1rem,2.7rem,2.8rem);
  font-weight:780; line-height:1.08; }
.lead { margin:0; color:var(--muted); font-size:1.04rem; }
.grid { display:grid; gap:18px; }
.grid.two { grid-template-columns:repeat(2,1fr); }
.grid.three { grid-template-columns:repeat(3,1fr); }
.card { background:rgba(255,255,255,.9); border:1px solid var(--line);
  border-radius:var(--radius); box-shadow:var(--shadow); padding:24px 26px; }
.card h3 { margin:0 0 8px; font-size:1.1rem; }
.card p { margin:0; color:var(--muted); }
.card .mini { color:var(--quiet); font-family:var(--mono); font-size:.74rem; }
.quote { border-left:4px solid var(--violet); background:#faf7ff; padding:14px 18px;
  border-radius:0 10px 10px 0; color:#3d3352; margin:16px 0; }
.pipeline { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:20px 0 26px; }
.step { position:relative; background:#fff; border:1px solid var(--line);
  border-radius:14px; padding:16px 16px 14px; box-shadow:0 8px 22px rgba(42,65,100,.06); }
.step .n { display:inline-flex; width:26px; height:26px; border-radius:50%;
  align-items:center; justify-content:center; background:var(--ink); color:#fff;
  font-family:var(--mono); font-size:.72rem; font-weight:700; margin-bottom:8px; }
.step b { display:block; font-size:.95rem; margin-bottom:4px; }
.step span { color:var(--muted); font-size:.8rem; line-height:1.45; display:block; }
.step:not(:last-child)::after { content:"→"; position:absolute; right:-12px; top:50%;
  transform:translateY(-50%); color:var(--quiet); font-weight:700; }
pre { margin:10px 0; padding:14px 16px; border-radius:10px; background:#0f1720;
  color:#e6edf3; font:12px/1.6 var(--mono); overflow:auto; white-space:pre-wrap;
  word-break:break-word; }
code { font-family:var(--mono); font-size:.9em; background:#eef2f6;
  padding:1px 5px; border-radius:4px; }
pre code { background:none; padding:0; font-size:inherit; }
.prompt-card { background:#fff; border:1px solid var(--line); border-radius:16px;
  box-shadow:var(--shadow); padding:22px 24px; margin:18px 0; }
.prompt-head { display:flex; flex-wrap:wrap; gap:8px 18px; align-items:baseline;
  border-bottom:1px solid var(--line); padding-bottom:10px; margin-bottom:12px; }
.prompt-head h3 { margin:0; font-size:1.08rem; }
.prompt-meta { color:var(--quiet); font-family:var(--mono); font-size:.72rem;
  font-weight:600; }
.bilingual { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.lang { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.lang .tag { display:block; padding:6px 10px; background:#f1f5f9; color:#52627a;
  font-family:var(--mono); font-size:.68rem; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; }
.lang pre { margin:0; border-radius:0; background:#fff; color:#1f2937; font-size:11.5px; }
.lang.zh pre { color:#243b53; background:#fbfdff; }
details { margin-top:10px; }
summary { cursor:pointer; color:var(--accent,var(--violet)); font-size:.82rem;
  font-family:var(--mono); font-weight:700; }
.reply { background:#f8fafc; border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; font:12px/1.55 var(--mono); color:#243b53; white-space:pre-wrap;
  word-break:break-word; margin-top:10px; }
.timeline { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
  gap:16px; margin-top:18px; }
.action-card { display:grid; grid-template-columns:190px minmax(0,1fr);
  gap:16px; align-items:center; background:#fff; border:1px solid var(--line);
  border-radius:16px; box-shadow:var(--shadow); padding:14px; }
.action-card img { width:100%; border-radius:10px; border:1px solid var(--line); }
.action-card .action-meta { align-self:center; }
.action-card .action-meta h4 { font-size:.92rem; line-height:1.35; }
.action-card .action-meta p { font-size:.8rem; }
.action-meta h4 { margin:0 0 8px; font-size:1rem; }
.action-meta .kind { display:inline-block; font-family:var(--mono); font-size:.7rem;
  font-weight:700; color:var(--violet); background:#f2ecff; border-radius:999px;
  padding:2px 8px; margin-bottom:8px; }
.action-meta p { margin:4px 0; color:#40506a; font-size:.88rem; }
.coord { font-family:var(--mono); background:#eef2f6; padding:1px 6px; border-radius:4px; }
.shot-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px; }
.shot-grid figure { margin:0; background:#fff; border:1px solid var(--line);
  border-radius:12px; padding:8px; }
.shot-grid img { border-radius:8px; border:1px solid var(--line); }
.shot-grid figcaption { color:var(--muted); font-size:.72rem; margin-top:6px;
  font-family:var(--mono); }
table { width:100%; border-collapse:collapse; margin:14px 0; background:#fff;
  border:1px solid var(--line); border-radius:12px; overflow:hidden; }
th,td { padding:10px 12px; border-bottom:1px solid var(--line); text-align:left;
  font-size:.86rem; vertical-align:top; }
th { background:#f4f8fc; color:#334155; font-family:var(--mono); font-size:.72rem;
  letter-spacing:.03em; text-transform:uppercase; }
tr:last-child td { border-bottom:none; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
.pill { display:inline-block; padding:2px 9px; border-radius:999px;
  font-family:var(--mono); font-size:.68rem; font-weight:700; }
.pill.ok { background:#e7f6ec; color:#067647; }
.pill.bad { background:#fff7f6; color:#b42318; }
.pill.wait { background:#fff4e5; color:#b54708; }
.note { background:#fffaf0; border:1px solid #f3d9a8; border-left:5px solid var(--gold);
  border-radius:10px; padding:14px 18px; margin:16px 0; color:#5b4420; }
.note b { color:#8a5a00; }
.footer { padding:46px 0 60px; color:var(--quiet); font-size:.8rem; text-align:center; }
.footer a { color:var(--muted); }
@media (max-width:900px) {
  .timeline { grid-template-columns:1fr; }
  .section-head,.grid.two,.grid.three,.bilingual,.action-card,.stats,.pipeline {
    grid-template-columns:1fr; }
  .step:not(:last-child)::after { display:none; }
  .shot-grid { grid-template-columns:repeat(2,1fr); }
  .nav-links { display:none; }
  h1 { font-size:2.1rem; }
}
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def b64_image(path: Path, width: int = 460, quality: int = 76) -> str:
    if not path.exists():
        return ""
    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > width:
            height = round(image.height * width / image.width)
            image = image.resize((width, height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def img_tag(path: Path, alt: str, width: int = 460, cls: str = "") -> str:
    data = b64_image(path, width)
    if not data:
        return f'<div class="mini">missing: {esc(path.name)}</div>'
    return f'<img class="{cls}" src="{data}" alt="{esc(alt)}">'


def call_text(call: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in call.get("request") or []:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
        elif content is not None:
            parts.append(str(content))
    return "\n".join(parts)


def find_call(calls: list[dict[str, Any]], needle: str, purpose: str | None = None) -> dict[str, Any]:
    for call in calls:
        if purpose and call.get("purpose") != purpose:
            continue
        if needle in call_text(call):
            return call
    return {}


def truncate(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...\n" + text[-limit // 2 :]


# ---------------------------------------------------------------- prompt data


def build_prompt_cards() -> str:
    calls = load_jsonl(RUN / "llm_calls.jsonl")
    workflow = calls[0] if calls else {}
    screen = find_call(calls, "Describe what you see on the current screen")
    codegen = find_call(calls, "Mode: Code generation")
    wpc = find_call(calls, "WPC operations")
    ui_tars = find_call(calls, "", purpose="ui_tars_grounding")
    verifier_rows = load_jsonl(RUN / "verifier_llm.jsonl")
    verifier = verifier_rows[-1] if verifier_rows else {}

    workflow_text = call_text(workflow)
    task_line = ""
    match = re.search(r"# The Current Task\s*\n\s*(.+)", workflow_text)
    if match:
        task_line = match.group(1).strip()
    workflow_excerpt = (
        "I will introduce you to a new programming language called **Task Program**. "
        "This is a natural language style domain-specific language (DSL) used to "
        "describe task execution flows. You need to master this language and complete "
        "the tasks I arrange.\n\n"
        "A Task Program consists of a series of statements, usually one per line, "
        "describing an operation or a step, using imperative sentences or clear "
        "declarative sentences.\n\n"
        f"# The Current Task\n{task_line}\n\n"
        "# Output Instruction\n"
        "1. Current user's language is English. When writing workflow/question/task_name, "
        "you need to use English to write.\n"
        "2. Do not ask the user questions within the code. The user requires the task to "
        "be fully automated and will not participate in any part of the workflow.\n"
        "3. Please set variable {answer} to as the final answer if the task requires you "
        "to answer a question.\n"
        "4. Note: You must declare in which APP to operate. For example: `In \"Contacts\" "
        "App, add a new contact name 'Alice', and save it.`\n"
        "6. Remember to save! You must emphasize in the workflow that for tasks involving "
        "editing or creation, saving is mandatory at the end!\n\n"
        "Now, Respond with the following content:\n"
        "Your thought (starts with `--- Thought ---`), ...\n"
        "The workflow (starts with `--- Workflow ---`), which is the workflow steps in "
        "Task Program syntax generated based on your understanding."
    )

    screen_excerpt = (
        "You are a helpful assistant aiming to solve the user's task.\n"
        "# Task Requirements\n"
        "\"Describe what you see on the current screen in as much detail as possible.\n"
        "Requirements:\n"
        "1. Every element, especially the icons, should be mentioned in your response.\n"
        "2. You should describe the function, text, color, and position of every element, "
        "following a top-to-bottom and left-to-right order.\n"
        "3. Additionally, if there is a popup window, be sure to emphasize its presence "
        "and explain whether it blocks the background elements.\n"
        "5. You should respond with a string split by \";\". ...\n"
        "6. Answer in English.\n\n"
        "# Response Format Content\n"
        "--- Thought ---\n"
        "Your thoughts, which contains your understanding about the task and plan ...\n"
        "--- Answer ---\n"
        "(The answer part. It should be standard JSON content that can be parsed by json.loads ...)"
    )

    codegen_excerpt = (
        "# Introduction\n"
        "You are an expert in solving problems with python. You job is to complete given "
        "tasks by tranlating pesudo code (natural language-style step-by-step workflow "
        "description) to python code lines that can be executed reliably on the fly.\n\n"
        "**Mode 1: Code Generation**\n"
        "In this mode, you should output the **next lines of python code** to complete the "
        "current workflow step (marked as \"current step\" in inline comment) according to "
        "the task and context. The new python code lines should follow the principles below:\n"
        "- (1) Correctness: ...\n"
        "- (2) Simplicity: ...\n"
        "- (3) Data awareness: ...\n"
        "- (4) Sequential execution: ...\n\n"
        "[... 约 10k 字符的框架、工具说明、变量与截图 ...]\n\n"
        "Mode: Code generation\n"
        "So, your current task is to execute the following line based on the variable values "
        "in `Data & variables` ...\n"
        "The current belief state:\n"
        "```\n"
        "- The Contacts app is open on the contact creation form titled \"创建联系人\" ...\n"
        "```"
    )

    wpc_excerpt = (
        "**Mode 2: Workflow Status Update**\n"
        "In this mode, you should decide how to update the workflow program counter (WPC) "
        "based on the execution output of your generated python code. The WPC operations "
        "include:\n"
        "- **hold**: stay in the current workflow step if it has not been completed.\n"
        "- **continue**: move to the next workflow step.\n"
        "- **break**: jump out of the current loop.\n"
        "- **return**: return from the current function.\n\n"
        "The current node is a sequential execution node. Output `continue` if and only if "
        "the `current step` is confirmed complete, there is no error information, and the "
        "belief state considers that the current status does not require exception handling.\n"
        "Emphasize again: You **need to and can only** select one of the following WPC "
        "operations as Action: hold, continue, break, return."
    )

    ui_excerpt = call_text(ui_tars)
    if not ui_excerpt:
        ui_excerpt = (
            "You are a GUI agent. You are given a task and your action history, with "
            "screenshots. You need to perform the next action to complete the task.\n"
            "## Output Format\nThought: ...\nAction: ...\n"
            "## Action Space\nclick(point='<point>x1 y1</point>')\n...\n"
            "## Note\n- Coordinates in <point> MUST be normalized to a 0-1000 scale ...\n"
            "- Use Chinese in `Thought` part.\n"
            "## User Instruction\nClick on Text editing component containing 名字 (First name) field."
        )

    verifier_text = ""
    for message in verifier.get("messages") or []:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    verifier_text = str(part.get("text", ""))
        elif content:
            verifier_text = str(content)
    verifier_excerpt = (
        "You judge the FINAL observable state of an Android app.\n"
        "Goal: create a new contact named agent prog in contacts app.\n"
        "Useful visible strings (may be empty): ['agent prog']\n"
        "Forbidden visible strings (may be empty): []\n\n"
        "Final UI text (may be truncated):\n"
        "<hierarchy ... text=\"agent prog\" ...>\n\n"
        "Judge ONLY the final observable state in the screenshot and the final UI text. "
        "Do NOT require the screenshot to show intermediate steps, the exact navigation "
        "path, or hidden database state.\n\n"
        "Return exactly one JSON object with three fields:\n"
        "{\"success\": true or false, \"reason\": \"one or two sentences citing visible "
        "evidence\", \"evidence\": \"short quote or visual element\"}"
    )

    cards = [
        {
            "id": "stp",
            "kicker": "环节 1 / 6",
            "title": "STP 生成：把自然语言任务写成程序",
            "where": "generate_workflow.py · workflow_model_args",
            "call": workflow,
            "en": workflow_excerpt,
            "zh": (
                "我将向你介绍一种新的编程语言 **Task Program**。这是一种自然语言风格的领域特定语言（DSL），"
                "用于描述任务执行流程。你需要掌握它并完成我安排的任务。\n\n"
                "Task Program 由一系列语句组成，通常每行一条，描述一个操作或步骤，使用祈使句或清晰的陈述句。\n\n"
                f"# 当前任务\n{task_line}\n\n"
                "# 输出要求\n"
                "1. 当前用户语言为英语，workflow/question/task_name 都要用英语写。\n"
                "2. 不要在代码中向用户提问；任务必须全自动完成，用户不会参与任何环节。\n"
                "3. 如果任务要求回答问题，请把变量 {answer} 设为最终答案。\n"
                "4. 必须声明在哪个 App 中操作。例如：`In \"Contacts\" App, add a new contact "
                "name 'Alice', and save it.`\n"
                "6. 记得保存！涉及编辑或创建的任务，必须在 workflow 末尾强调保存。\n\n"
                "现在请输出：\n"
                "你的思考（以 `--- Thought ---` 开头）……\n"
                "workflow（以 `--- Workflow ---` 开头），即用 Task Program 语法写出的步骤。"
            ),
            "full": workflow_text,
            "response": str(workflow.get("response", "")),
        },
        {
            "id": "screen",
            "kicker": "环节 2 / 6",
            "title": "屏幕描述：把截图变成结构化文字",
            "where": "mobile_utils.get_text_description · executor 模型",
            "call": screen,
            "en": screen_excerpt,
            "zh": (
                "你是一个帮助用户完成任务的助手。\n"
                "# 任务要求\n"
                "“尽可能详细地描述当前屏幕上的内容。\n"
                "要求：\n"
                "1. 必须提到每一个元素，尤其是图标。\n"
                "2. 按从上到下、从左到右的顺序，描述每个元素的功能、文字、颜色和位置。\n"
                "3. 如果有弹窗，要强调它的存在，并说明是否遮挡背景元素。\n"
                "5. 用分号分隔的字符串回答……\n"
                "6. 用英语回答。\n\n"
                "# 响应格式\n"
                "--- Thought ---\n"
                "你的思考，包括对任务的理解和执行计划……\n"
                "--- Answer ---\n"
                "（答案部分必须是可被 json.loads 解析的标准 JSON 内容……）"
            ),
            "full": call_text(screen),
            "response": str(screen.get("response", "")),
        },
        {
            "id": "codegen",
            "kicker": "环节 3 / 6",
            "title": "Action Generation：把当前步骤翻译成 Python 动作",
            "where": "core/agentprog.py:117 code_generation()",
            "call": codegen,
            "en": codegen_excerpt,
            "zh": (
                "# 引言\n"
                "你是解决 Python 问题的专家。你的工作是把伪代码（自然语言风格的逐步 workflow）"
                "翻译成可以可靠执行的 Python 代码。\n\n"
                "**模式 1：代码生成**\n"
                "在这个模式下，你要输出完成当前 workflow 步骤的**下一段 Python 代码**"
                "（当前步骤在行内注释中标记为 current step）。代码应遵循：\n"
                "- (1) 正确性：……\n"
                "- (2) 简洁性：……\n"
                "- (3) 数据感知：……\n"
                "- (4) 顺序执行：……\n\n"
                "[……约 1 万字符的框架、工具说明、变量与截图……]\n\n"
                "模式：代码生成\n"
                "因此，你当前的任务是根据 `Data & variables` 中的变量值执行下面这一行……\n"
                "当前信念状态：\n"
                "```\n"
                "- Contacts App 打开在“创建联系人”表单……\n"
                "```"
            ),
            "full": call_text(codegen),
            "response": str(codegen.get("response", "")),
        },
        {
            "id": "wpc",
            "kicker": "环节 4 / 6",
            "title": "Program Counter Update：决定下一步走哪里",
            "where": "core/agentprog.py:194 workflow_status_update()",
            "call": wpc,
            "en": wpc_excerpt,
            "zh": (
                "**模式 2：Workflow 状态更新**\n"
                "在这个模式下，你要根据刚生成的 Python 代码的执行结果，决定如何更新 "
                "workflow 程序计数器（WPC）。WPC 操作包括：\n"
                "- **hold**：当前步骤还没完成，停在原地。\n"
                "- **continue**：进入下一个 workflow 步骤。\n"
                "- **break**：跳出当前循环。\n"
                "- **return**：从当前函数返回。\n\n"
                "当前节点是顺序执行节点。只有当 `current step` 确认完成、没有错误信息，"
                "并且信念状态认为不需要异常处理时，才输出 `continue`。\n"
                "再次强调：你**必须且只能**从 hold、continue、break、return 中选一个作为 Action。"
            ),
            "full": call_text(wpc),
            "response": str(wpc.get("response", "")),
        },
        {
            "id": "uitars",
            "kicker": "环节 5 / 6",
            "title": "UI-TARS 定位：把“点名字输入框”变成坐标",
            "where": "all_utils/ui_tars_utils.py · MobileAPI locator='ui_tars'",
            "call": ui_tars,
            "en": ui_excerpt,
            "zh": (
                "你是一个 GUI agent。你会收到任务、动作历史和截图，需要执行下一步动作来完成任务。\n"
                "## 输出格式\nThought: ……\nAction: ……\n"
                "## 动作空间\nclick(point='<point>x1 y1</point>')\nlong_press(...)\n"
                "type(content='')\nscroll(...)\nopen_app(app_name='')\ndrag(...)\n"
                "press_home()\npress_back()\nfinished(content='xxx')\n"
                "## 注意\n- <point> 坐标必须归一化到 0–1000：x = round(pixel_x / image_width * 1000)，"
                "y = round(pixel_y / image_height * 1000)，不要输出原始像素坐标。\n"
                "- `Thought` 部分用中文。\n"
                "- 先写一个小计划，再用一句话总结下一个动作及其目标元素。\n"
                "## 用户指令\n点击包含“名字”（First name）的文本编辑组件。"
            ),
            "full": ui_excerpt,
            "response": str(ui_tars.get("response", "")),
        },
        {
            "id": "verifier",
            "kicker": "环节 6 / 6",
            "title": "最终状态判定：只看任务结束后的可观察状态",
            "where": "scripts/reproduce_agentprog_example.py · verify()",
            "call": verifier,
            "en": verifier_excerpt,
            "zh": (
                "你判断 Android 应用的**最终可观察状态**。\n"
                "目标：在通讯录应用中创建一个名为 agent prog 的新联系人。\n"
                "应出现的可见字符串（可为空）：['agent prog']\n"
                "不应出现的可见字符串（可为空）：[]\n\n"
                "最终 UI 文本（可能被截断）：\n"
                "<hierarchy ... text=\"agent prog\" ...>\n\n"
                "只根据截图和最终 UI 文本判断最终状态。成功意味着目标要求的结束状态现在已经出现，"
                "或者是其直接结果（例如所有note归档后列表为空）。**不要求**截图展示中间步骤、"
                "精确导航路径或隐藏的数据库状态。忽略 agent 是如何到达这里的。\n\n"
                "只返回一个 JSON 对象，包含三个字段：\n"
                "{\"success\": true 或 false, \"reason\": \"一两句话，引用可见证据\", "
                "\"evidence\": \"简短引用或视觉元素\"}"
            ),
            "full": verifier_text,
            "response": str(verifier.get("content", "")),
        },
    ]

    html_parts = []
    for card in cards:
        call = card.get("call") or {}
        duration = call.get("seconds") or call.get("duration_s")
        meta = card["where"]
        if duration is not None:
            meta += f" · {duration}s"
        full_block = ""
        if card.get("full"):
            full_block = (
                "<details><summary>展开完整英文 prompt</summary>"
                f'<pre>{esc(truncate(card["full"], 12000))}</pre></details>'
            )
        response = card.get("response") or "（运行中断，未记录响应）"
        html_parts.append(
            f"""
            <div class="prompt-card" id="prompt-{card['id']}">
              <div class="prompt-head">
                <h3>{esc(card['title'])}</h3>
                <span class="prompt-meta">{esc(card['kicker'])} · {esc(meta)}</span>
              </div>
              <div class="bilingual">
                <div class="lang"><span class="tag">English prompt</span>
                  <pre>{esc(card['en'])}</pre></div>
                <div class="lang zh"><span class="tag">中文对照</span>
                  <pre>{esc(card['zh'])}</pre></div>
              </div>
              {full_block}
              <details><summary>模型返回（原文）</summary>
                <div class="reply">{esc(truncate(response, 1800))}</div>
              </details>
            </div>
            """
        )
    return "".join(html_parts)


# ---------------------------------------------------------------- run data


def load_result(path: Path) -> dict[str, Any]:
    return load_json(path)


def fmt_seconds(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if value >= 60:
        return f"{value / 60:.1f} min"
    return f"{value:.0f}s"


def result_rows() -> tuple[str, str, dict[str, Any]]:
    contacts = load_result(RUN / "result.json")
    summary_path = LUNA / "summary.json"
    tasks: list[dict[str, Any]] = []
    if summary_path.exists():
        tasks = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        for path in sorted(LUNA.glob("*/result.json")):
            tasks.append(load_result(path))

    rows = []
    if contacts:
        rows.append(
            "<tr>"
            "<td><code>contacts_readme</code><br><span class=\"mini\">system Contacts · sanity check</span></td>"
            "<td>create a new contact named agent prog</td>"
            f"<td class=\"num\">{contacts.get('model_calls', '—')}</td>"
            f"<td class=\"num\">{contacts.get('actions', '—')}</td>"
            f"<td class=\"num\">{fmt_seconds(contacts.get('duration_s'))}</td>"
            f"<td>{'<span class=\"pill ok\">PASS</span>' if contacts.get('success') else '<span class=\"pill bad\">FAIL</span>'}</td>"
            f"<td>{esc(contacts.get('reason', ''))}</td>"
            "</tr>"
        )
    for task in tasks:
        success = bool(task.get("success"))
        timed_out = bool(task.get("timed_out")) or task.get("error") == "timed out"
        if success:
            pill = '<span class="pill ok">PASS</span>'
        elif task.get("error"):
            pill = '<span class="pill wait">ERROR</span>'
        else:
            pill = '<span class="pill bad">FAIL</span>'
        if timed_out:
            pill += ' <span class="pill wait" title="子进程到达单任务时限后被终止；最终屏幕仍被评分">timeout</span>'
        reason = truncate(task.get("reason", ""), 260)
        if timed_out:
            reason = ("单任务时限到点，子进程被终止；下表数值与截图取自终止前的运行产物。"
                      + reason)
        rows.append(
            "<tr>"
            f"<td><code>{esc(task.get('id'))}</code><br><span class=\"mini\">{esc(task.get('app_name', task.get('app', '')))}</span></td>"
            f"<td>{esc(truncate(task.get('goal', ''), 200))}</td>"
            f"<td class=\"num\">{task.get('model_calls', '—')}</td>"
            f"<td class=\"num\">{len(task.get('images') or []) or '—'}</td>"
            f"<td class=\"num\">{fmt_seconds(task.get('agent_seconds'))}</td>"
            f"<td>{pill}</td>"
            f"<td>{esc(reason)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7">任务仍在运行或尚未开始。</td></tr>')

    ok = sum(1 for task in tasks if task.get("success"))
    total = len(tasks)
    if not tasks:
        ratio = "运行中"
    elif ok == total:
        ratio = f"{ok}/{total}"
    else:
        ratio = f"{ok}/{total}"
    return "".join(rows), ratio, {"contacts": contacts, "tasks": tasks}


def contacts_timeline() -> str:
    actions = load_jsonl(RUN / "actions.jsonl")
    cards = []
    for action in actions:
        if "error" in action:
            continue
        image = RUN / action.get("image", "")
        desc = action.get("description") or ""
        text = action.get("text") or ""
        kind = action.get("kind", "click")
        kind_zh = {"click": "点击", "input": "输入", "long_click": "长按", "swipe": "滑动"}.get(kind, kind)
        meta = []
        if desc:
            meta.append(f"<p><b>界面描述：</b>{esc(desc)}</p>")
        if text:
            meta.append(f"<p><b>输入内容：</b>{esc(text)}</p>")
        if action.get("x") is not None:
            meta.append(
                f'<p><b>坐标：</b><span class="coord">({action.get("x")}, {action.get("y")})</span>'
                " · 红色圆圈/十字为报告脚本在真实截图上标注的点击点</p>"
            )
        cards.append(
            f"""
            <div class="action-card">
              {img_tag(image, f"action {action.get('index')}", 300)}
              <div class="action-meta">
                <span class="kind">动作 {action.get('index')} · {esc(kind_zh)}</span>
                <h4>{esc(desc or kind_zh)}</h4>
                {''.join(meta)}
              </div>
            </div>
            """
        )
    return "".join(cards)


def task_case(task_id: str, title: str) -> str:
    result = load_result(LUNA / task_id / "result.json")
    if not result:
        return f'<div class="card"><h3>{esc(title)}</h3><p>任务尚未完成，结果待补。</p></div>'
    images = sorted((LUNA / task_id / "images").glob("screenshot_*.png"))
    chosen = images[:4]
    if (LUNA / task_id / "final.png").exists():
        chosen.append(LUNA / task_id / "final.png")
    figs = "".join(
        f'<figure>{img_tag(path, path.name, 320)}<figcaption>{esc(path.name)}</figcaption></figure>'
        for path in chosen
    )
    workflow = ""
    wf_path = LUNA / task_id / "workflow.ap"
    if wf_path.exists():
        workflow = wf_path.read_text(encoding="utf-8")
    pill = ('<span class="pill ok">PASS</span>' if result.get("success")
            else '<span class="pill bad">FAIL</span>')
    return f"""
    <div class="card">
      <h3>{esc(title)} {pill}</h3>
      <p class="mini">{esc(result.get('goal', ''))}</p>
      <p><b>最终状态判定：</b>{esc(result.get('reason', '—'))}</p>
      <p><b>证据：</b>{esc(result.get('evidence', '—'))}</p>
      <details><summary>展开生成的 workflow.ap</summary><pre>{esc(workflow)}</pre></details>
      <div class="shot-grid">{figs}</div>
    </div>
    """


def main() -> int:
    table_rows, open_source_ratio, data = result_rows()
    contacts = data["contacts"]
    tasks = data["tasks"]
    total_calls = (contacts.get("model_calls") or 0) + sum(
        task.get("model_calls") or 0 for task in tasks
    )
    total_actions = (contacts.get("actions") or 0) + sum(
        len(task.get("images") or []) for task in tasks
    )
    total_seconds = (contacts.get("duration_s") or 0) + sum(
        task.get("agent_seconds") or 0 for task in tasks
    )

    html_out = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentProg 讲清楚 — 论文、代码与真实执行</title>
<style>{CSS}</style></head>
<body>
<nav class="site-nav"><div class="nav-inner">
  <a class="brand" href="#">Agent<span>Prog</span></a>
  <div class="nav-links">
    <a href="#why">为什么</a><a href="#method">方法</a>
    <a href="#prompts">Prompt 对照</a><a href="#runs">真实执行</a>
    <a href="#code">代码地图</a><a href="#results">结果</a><a href="#cite">引用</a>
  </div>
</div></nav>

<header class="hero"><div class="hero-inner">
  <p class="eyebrow">AgentProg · MobiSys 2026 · Tsinghua AIR</p>
  <h1>AgentProg: Empowering Long-Horizon GUI Agents with Program-Guided Context Management</h1>
  <p class="hero-sub">把长程手机 GUI 任务写成程序：先规划 STP，再双模式执行，用程序结构裁剪上下文，用全局信念状态纠偏。</p>
  <p class="hero-authors">Shizuo Tian<sup>1</sup>, Hao Wen<sup>1</sup>, Yuxuan Chen<sup>1</sup>, Jiacheng Liu<sup>2</sup>,
    Shanhui Zhao<sup>1</sup>, Guohong Liu<sup>1</sup>, Ju Ren<sup>1</sup>, Yunxin Liu<sup>1</sup>, Yuanchun Li<sup>1</sup></p>
  <p class="hero-affiliations"><sup>1</sup>Tsinghua University &nbsp;&nbsp; <sup>2</sup>Peking University</p>
  <div class="hero-actions">
    <a class="button primary" href="{ARXIV}" target="_blank" rel="noopener">论文 arXiv:2512.10371</a>
    <a class="button" href="{CODE}" target="_blank" rel="noopener">开源代码</a>
    <a class="button accent" href="#prompts">六段 Prompt 中英对照</a>
    <a class="button teal" href="#runs">真实设备执行记录</a>
  </div>
</div></header>

<div class="stats">
  <div class="stat"><b>78.0%</b><span>AndroidWorld 成功率（论文，Gemini-2.5-Pro + UI-TARS-1.5）</span></div>
  <div class="stat"><b>68.4%</b><span>AW-Extend 长程任务成功率（论文）</span></div>
  <div class="stat"><b>{open_source_ratio}</b><span>本次开源 App 任务成功数 / 已完成数（gpt-6-luna）</span></div>
  <div class="stat"><b>{total_calls}</b><span>本次真实设备运行记录的模型调用次数</span></div>
</div>

<section class="section" id="why"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Why AgentProg</p><h2>长程任务的瓶颈不是“会不会点”，而是“记不记得住”</h2></div>
    <p class="lead">论文把 GUI agent 的交互历史重新看成一个<b>程序</b>：变量保存关键信息，控制流决定哪些历史仍然相关。于是“保留什么、丢弃什么”不再靠启发式摘要，而是由程序结构决定。</p>
  </div>
  <div class="grid three">
    <div class="card"><h3>① 缺乏整体规划</h3><p>现有 agent 容易完成前两个子任务就以为全部完成；STP 在开始执行前就把任务拆成可检查的步骤和循环。</p></div>
    <div class="card"><h3>② 关键信息丢失</h3><p>上下文压缩把 50 步前记下的电话号码压没了；STP 用显式变量把关键数据“钉”在上下文里。</p></div>
    <div class="card"><h3>③ 动态环境 / 部分可观测</h3><p>弹窗、误触、应用崩溃会让 agent 在错误前提上继续操作；全局信念状态持续做 Predict–Verify–Align。</p></div>
  </div>
  <div class="quote">论文原话：现有方法在 “MarkorTodoList” 任务里只完成了前两项就提前终止；在迭代任务中还会因为记不住最初打开的笔记内容而传错参数。<br>
  <span class="mini">— arXiv 2512.10371 §2.3 Motivation and Challenges</span></div>
</div></section>

<section class="section alt" id="method"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Method</p><h2>两阶段、双模式、一棵执行树</h2></div>
    <p class="lead">先把任务生成 STP（workflow.ap），再由运行时解释器逐行执行。执行器不是照本宣科，而是在“生成动作”和“更新程序计数器”之间交替。</p>
  </div>
  <div class="pipeline">
    <div class="step"><span class="n">1</span><b>STP 生成</b><span>自然语言任务 → 带变量/循环/分支的程序（workflow.ap）</span></div>
    <div class="step"><span class="n">2</span><b>Action Generation</b><span>当前步骤 + 截图 + 变量 → 一段 Python GUI 动作</span></div>
    <div class="step"><span class="n">3</span><b>PC Update</b><span>根据执行结果决定 hold / continue / break / return</span></div>
    <div class="step"><span class="n">4</span><b>Belief State</b><span>Predict–Verify–Align，发现“以为在表单、其实回了桌面”就恢复</span></div>
  </div>
  <div class="grid two">
    <div class="card">
      <h3>Program-Guided Context Management</h3>
      <p><b>执行树裁剪：</b>顺序节点挂到上一个节点下；只保留“未走的分支”与“已完成的循环迭代”之外的活动路径。<br>
      <b>同一步骤检索：</b>循环回到同一个 step ID 时，把该步骤过去几次的执行结果注入上下文。<br>
      <b>数据流持久化：</b>STP 生成阶段声明的变量是锚点，不会被裁剪掉。</p>
    </div>
    <div class="card">
      <h3>Global Belief State</h3>
      <p>论文用 Belief MDP 的视角维护“当前环境假设”：我在哪个页面、哪些字段已填、剪贴板/返回栈里有什么。每个低层动作执行后都用新截图校验；一旦观察与假设冲突，就标记 Context Lost 并进入恢复流程，而不是继续点一个已经不存在的 Save。</p>
    </div>
  </div>
  <h3 style="margin:26px 0 8px">本次真实生成的 STP（contacts README 示例）</h3>
  <pre>{esc((RUN / 'workflow.ap').read_text(encoding='utf-8') if (RUN / 'workflow.ap').exists() else '（workflow.ap 尚未生成）')}</pre>
  <p class="mini">只有两行：一条变量声明 + 一条自然语言动作。STP 的“语义容忍”允许执行器自己决定先点哪里、怎么填。
  文件里的 <code>text</code> 行是模型把程序包在 <code>```text</code> 代码块里、而上游只剥掉 <code>```agentprog</code>
  和 <code>```</code> 留下的残片；执行器把它当作未知行跳过，不影响执行。这是真实运行产物，未做清洗。</p>
</div></section>

<section class="section" id="prompts"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Prompt Walkthrough</p><h2>每个环节的 Prompt，中英对照</h2></div>
    <p class="lead">六段 prompt 全部取自本次真实运行（<code>runs/repro_agentprog_readme/llm_calls.jsonl</code> 与 <code>verifier_llm.jsonl</code>）。左侧是模型实际看到的英文，右侧是逐段中文对照；完整 prompt 可展开。</p>
  </div>
  {build_prompt_cards()}
</div></section>

<section class="section alt" id="runs"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Real Device Runs</p><h2>真实执行：从截图到最终状态</h2></div>
    <p class="lead">Pixel 9 Pro XL（Android 16，1008×2244），真实 adb 控制。成功只按任务结束后的可观察状态判定，不看路径、不看隐藏数据库。</p>
  </div>
  <div class="note"><b>为什么还有 Contacts？</b> 它是论文 README 的原始示例，只作为“复现链路能跑通”的 sanity check。
  下面的主案例全部换成不依赖登录/系统账号的开源 App（OmniNotes、Activity Diary、Tasks.org）。</div>
  <h3>案例 A：Contacts README 示例（sanity check）</h3>
  <p>任务：<code>create a new contact named agent prog in contacts app.</code> · 4 个动作 · 19 次模型调用 · 282s ·
  <span class="pill ok">PASS</span></p>
  <div class="timeline">{contacts_timeline()}</div>
  <div style="max-width:420px;margin-top:18px">
    {img_tag(RUN / 'final.png', 'contacts final state', 420)}
    <p class="mini">最终截图：联系人 “agent prog” 已出现在列表中；VLM 判定与 UI 文本双重确认。</p>
  </div>
  <h3 style="margin-top:34px">案例 B：开源 App 长任务</h3>
  {task_case('omni_three_notes_edit_archive', 'OmniNotes：三条笔记 + 编辑 + 归档')}
  {task_case('omni_two_notes_pin_delete', 'OmniNotes：置顶与删除')}
  {task_case('diary_officework_session', 'Activity Diary：开始/停止/切换活动')}
</div></section>

<section class="section" id="code"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Code Map</p><h2>论文概念在代码里的落点</h2></div>
    <p class="lead">上游代码保持原样，只做了 4 个文件的兼容性改动（18 insertions / 9 deletions）：本地网关、UI-TARS 环境变量、基准 App 的 Activity 映射、Windows UTF-8。</p>
  </div>
  <table>
    <thead><tr><th>论文概念</th><th>代码位置</th><th>做什么</th></tr></thead>
    <tbody>
      <tr><td>两阶段入口</td><td><code>plan/code_exec/workflow/pipeline.py:11</code></td><td><code>agentprog_pipeline_core</code>：先 <code>generate_workflow</code>，再 <code>agentprog_run_core</code>。</td></tr>
      <tr><td>STP 生成</td><td><code>workflow/generate_workflow.py</code></td><td>用 <code>get_script_mobile</code> prompt 生成 <code>workflow.ap</code>，解析 Thought/Workflow。</td></tr>
      <tr><td>移动端运行时</td><td><code>workflow/workflow_query_llm.py:169</code></td><td><code>_agentprog_run_mobile</code>：注入 <code>llm</code>、<code>mobile</code>、截图函数和变量后调用 <code>run_workflow</code>。</td></tr>
      <tr><td>双模式执行</td><td><code>workflow/core/agentprog.py:117 / :194</code></td><td><code>code_generation()</code> 生成动作；<code>workflow_status_update()</code> 决定 WPC。</td></tr>
      <tr><td>执行树 / 上下文</td><td><code>plan/workflow_utils.py:1107</code></td><td><code>WorkflowSystem</code> 用 <code>snipe()</code> 标记逐个节点注册、挂树、裁剪。</td></tr>
      <tr><td>信念状态</td><td><code>plan/belief/belief_state.py</code></td><td><code>BeliefState(belief_state_str, plan)</code>，每次 LLM 响应更新。</td></tr>
      <tr><td>UI-TARS 定位</td><td><code>all_utils/mobile_utils.py</code> + <code>ui_tars_utils.py</code></td><td><code>MobileAPI</code> 把元素描述交给 UI-TARS，拿回坐标后 adb 点击。</td></tr>
      <tr><td>Prompt 集合</td><td><code>workflow_prompts/</code></td><td>框架、示例、belief-state 更新、WPC 输出约束都在这里。</td></tr>
    </tbody>
  </table>
</div></section>

<section class="section alt" id="results"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Results</p><h2>论文结果 vs. 本次复现</h2></div>
    <p class="lead">论文在模拟器上用 Gemini-2.5-Pro + UI-TARS-1.5-API；本次在真机上用 auto/gpt-6-luna（规划、执行、UI-TARS 定位、最终判定统一换模型），任务目标是开源 App 子集。因此两组数字不能直接横比。</p>
  </div>
  <h3>论文：AndroidWorld（116 tasks）</h3>
  <table><thead><tr><th>方法</th><th class="num">成功率</th></tr></thead><tbody>
    <tr><td>M3A (SoM, Gemini-2.5-Pro)</td><td class="num">39.7%</td></tr>
    <tr><td>UI-TARS (UI-TARS-1.5-API)</td><td class="num">64.2%</td></tr>
    <tr><td>Mobile-Agent-v3 (GUI-Owl-32B)</td><td class="num">73.3%</td></tr>
    <tr><td><b>AgentProg (Gemini-2.5-Pro)</b></td><td class="num"><b>78.0%</b></td></tr>
  </tbody></table>
  <h3>论文：AW-Extend（19 个长程任务）</h3>
  <table><thead><tr><th>方法</th><th class="num">成功率</th></tr></thead><tbody>
    <tr><td>M3A (a11y)</td><td class="num">23.7%</td></tr>
    <tr><td>M3A (SoM)</td><td class="num">28.9%</td></tr>
    <tr><td>Mobile-Agent-v3 (GUI-Owl-32B)</td><td class="num">28.9%</td></tr>
    <tr><td>UI-TARS (UI-TARS-1.5-API)</td><td class="num">36.8%</td></tr>
    <tr><td><b>AgentProg</b></td><td class="num"><b>68.4%</b></td></tr>
  </tbody></table>
  <div class="note"><b>成本代价：</b>论文 Table 3 显示 AgentProg 每任务约 1026k static prefix + 301k dynamic + 180k output tokens，平均 2662s；输出 token 显著多于 UI-TARS（3.2k）和 Mobile-Agent-v3（22.1k）。这也是我们复现时把主模型换成更快的 gpt-6-luna 的原因。</div>
  <h3>本次真实设备运行</h3>
  <table><thead><tr><th>任务</th><th>目标</th><th class="num">模型调用</th><th class="num">截图</th><th class="num">耗时</th><th>最终状态</th><th>判定理由</th></tr></thead>
  <tbody>{table_rows}</tbody></table>
  <p class="mini">共 {total_calls} 次模型调用、{total_actions} 张过程截图、累计 {fmt_seconds(total_seconds)}。成功定义：final UI + 截图满足目标结束状态；不看中间路径与隐藏数据库。</p>
</div></section>

<section class="section" id="cite"><div class="wrap">
  <div class="section-head">
    <div><p class="kicker">Citation</p><h2>论文与代码</h2></div>
    <p class="lead">本页所有方法描述来自 arXiv 2512.10371v2 与上游 README；所有截图与判定来自本仓库的真实运行产物。</p>
  </div>
  <pre>@misc{{tian2025agentprog,
  title={{AgentProg: Empowering Long-Horizon GUI Agents with Program-Guided Context Management}},
  author={{Shizuo Tian and Hao Wen and Yuxuan Chen and Jiacheng Liu and Shanhui Zhao
    and Guohong Liu and Ju Ren and Yunxin Liu and Yuanchun Li}},
  year={{2025}}, eprint={{2512.10371}}, archivePrefix={{arXiv}}, primaryClass={{cs.AI}},
  url={{https://arxiv.org/abs/2512.10371}}
}}</pre>
  <p class="mini">页面版式参考 <a href="{REFERENCE}" target="_blank" rel="noopener">MemGUI-Agent 项目主页</a>
  （固定导航 / 大标题 Hero / 分区卡片 / 论文式表格），按其结构复刻并替换为 AgentProg 的内容。</p>
</div></section>

<footer class="footer"><div class="wrap">
  AgentProg 讲清楚 · 真实设备：Pixel 9 Pro XL / Android 16 · 模型网关：本地 magpie · 生成时间：2026-11-11
</div></footer>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
