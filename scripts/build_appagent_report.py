#!/usr/bin/env python3
"""Build the AppAgent real-device acceptance report from actual run artifacts."""

from __future__ import annotations

import base64
import html
import io
import json
import time
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "appagent"
OUT = ROOT / "docs" / "reports" / "appagent-report.html"
APPAGENT = ROOT / "third_party" / "AppAgent"


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
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def benchmark_order() -> list[str]:
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
        log = read_jsonl(task_dir / "appagent_log.jsonl")
        tasks.append(
            {
                "result": result,
                "dir": task_dir,
                "steps": steps,
                "log": log,
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


def loop_stats(steps: list[dict[str, Any]]) -> tuple[int, str, int]:
    """Longest run of the same action and the most frequent action."""
    longest = 0
    run = 0
    previous = None
    repeated = ""
    counts: dict[str, int] = {}
    for step in steps:
        # Normalize the same Markdown wrappers that the local parser patch
        # strips, so a backticked tap(7) still counts as the same action.
        action = " ".join(str(step.get("action", "")).split()).strip("`*_ ")
        counts[action] = counts.get(action, 0) + 1
        if action == previous:
            run += 1
        else:
            run = 1
            previous = action
        if run > longest:
            longest = run
            repeated = action
    top = max(counts.values()) if counts else 0
    return longest, repeated, top


def task_section(task: dict[str, Any], index: int) -> str:
    result = task["result"]
    task_dir = task["dir"]
    steps = task["steps"]
    ok = bool(result.get("success"))
    final = task_dir / "final.jpg"
    final_html = (
        f'<figure class="final"><img src="{thumb(final, 360, 78)}" alt="final">'
        f"<figcaption>Agent 结束后的真实终屏（外部评测器拍摄）</figcaption></figure>"
        if final.exists()
        else ""
    )

    frames = []
    for step in steps:
        image = task_dir / str(step.get("before", ""))
        if not image.exists():
            continue
        action = step.get("action", "") or step.get("action_tool", "")
        caption = f"Round {step.get('step')} · {action}"
        frames.append(
            '<figure class="frame">'
            f'<img src="{thumb(image)}" alt="{esc(caption)}">'
            f"<figcaption>{esc(caption)}<br><span>{esc(str(step.get('summary', ''))[:80])}</span></figcaption>"
            "</figure>"
        )
    film = f'<div class="film">{"".join(frames)}</div>' if frames else "<p>无截图。</p>"

    step_rows = [
        [
            str(step.get("step")),
            f"<code>{esc(step.get('action'))}</code>",
            esc(str(step.get("observation", ""))[:220]),
            esc(str(step.get("thought", ""))[:180]),
            esc(str(step.get("summary", ""))[:150]),
        ]
        for step in steps
    ]
    step_table = table(
        ["轮", "AppAgent 动作", "Observation（模型看到）", "Thought", "Summary"],
        step_rows,
    )

    raw = "\n\n".join(
        f"### Round {step.get('step')}\n{step.get('response', '')}"
        for step in steps
    )
    raw_html = f"<pre>{esc(raw[:60000])}</pre>" if raw else "<p>无模型响应日志。</p>"
    prompt = ""
    if task["log"]:
        prompt = str(task["log"][0].get("prompt", ""))[:3000]
    prompt_html = (
        f"<pre>{esc(prompt)}</pre>" if prompt else "<p>无模型请求日志。</p>"
    )
    longest, repeated, top = loop_stats(steps)
    loop_note = (
        f'<p class="warn">注意：连续 {longest} 轮重复 <code>{esc(repeated)}</code>，'
        "界面没有实质变化。这是 AppAgent 无 stall 检测的表现，可能发生在任务已完成之后"
        "（例如无法关闭抽屉），也可能意味着任务根本没推进；请对照逐轮截图判断。</p>"
        if longest >= 5
        else ""
    )

    return f"""
<section class="task">
  <div class="task-head">
    <h2>{index}. <code>{esc(result.get('id'))}</code> {badge(ok)}</h2>
    <div class="metrics">
      <span>App: {esc(result.get('app_name'))}</span>
      <span>Rounds: {result.get('rounds')}</span>
      <span>FINISH: {"是" if steps and steps[-1].get("action_tool") == "FINISH" else "否"}</span>
      <span>AppAgent: {result.get('appagent_seconds')}s</span>
      <span>Total: {result.get('elapsed_s')}s</span>
      <span>Verifier: {result.get('verifier_success')}</span>
      <span>Text check: {result.get('deterministic_ok')}</span>
    </div>
  </div>
  <p><strong>目标：</strong>{esc(result.get('goal'))}</p>
  <p><strong>最终判定：</strong>{esc(result.get('reason'))}</p>
  {loop_note}
  <div class="final-wrap">{final_html}</div>
  <h3>AppAgent 每一轮看到的真实截图</h3>
  <p class="muted">截图为 AppAgent 自己生成的 labeled 截图（含它标注的可交互元素编号），
  与模型当轮输入一致；不是脚本复现。</p>
  {film}
  <details open><summary>逐轮 Observation / Thought / Action / Summary</summary>{step_table}</details>
  <details><summary>查看某一轮的完整模型请求（AppAgent 原始 prompt，截断）</summary>{prompt_html}</details>
  <details><summary>查看全部轮的模型响应原文</summary>{raw_html}</details>
</section>
"""


def main() -> int:
    tasks = load_tasks()
    if not tasks:
        print("no AppAgent results found")
        return 1
    successes = sum(1 for task in tasks if task["result"].get("success"))
    text_ok = sum(1 for task in tasks if task["result"].get("deterministic_ok"))
    verifier_ok = sum(1 for task in tasks if task["result"].get("verifier_success"))
    total_rounds = sum(task["result"].get("rounds", 0) for task in tasks)
    total_agent = sum(task["result"].get("appagent_seconds", 0) for task in tasks)
    total_wall = sum(task["result"].get("elapsed_s", 0) for task in tasks)
    total_shots = sum(len(task["steps"]) for task in tasks)
    commit = ""
    try:
        commit = __import__("subprocess").check_output(
            ["git", "-C", str(APPAGENT), "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        pass

    rows = []
    for task in tasks:
        result = task["result"]
        steps = task["steps"]
        finished = bool(
            steps and steps[-1].get("action_tool") == "FINISH"
        )
        longest, repeated, top = loop_stats(steps)
        rows.append(
            [
                f"<code>{esc(result.get('id'))}</code>",
                esc(result.get("app_name")),
                badge(bool(result.get("success"))),
                "是" if result.get("deterministic_ok") else "否",
                "是" if finished else "否",
                str(result.get("rounds")),
                f"{result.get('appagent_seconds')}s",
                f"{result.get('elapsed_s')}s",
                f"{longest} × <code>{esc(repeated)}</code>" if longest >= 3 else "—",
                esc(str(result.get("reason"))[:130]),
            ]
        )
    result_table = table(
        ["任务", "App", "结果", "文本检查", "自报 FINISH", "轮数", "Agent 耗时", "总耗时",
         "最长连续重复动作", "判定理由"],
        rows,
        "results",
    )

    loop_tasks = []
    invisible_tasks = []
    for task in tasks:
        result = task["result"]
        longest, repeated, _ = loop_stats(task["steps"])
        if longest >= 5:
            loop_tasks.append(
                f"<code>{esc(result.get('id'))}</code>（{longest} × <code>{esc(repeated)}</code>）"
            )
        if result.get("deterministic_ok") and not result.get("verifier_success"):
            invisible_tasks.append(f"<code>{esc(result.get('id'))}</code>")
    failure_summary = (
        "<h3>失败模式（自动汇总）</h3><ul>"
        f"<li><strong>长循环：</strong>{'；'.join(loop_tasks) or '无'}</li>"
        f"<li><strong>文本检查通过、但 VLM 无法从终屏确认：</strong>"
        f"{'；'.join(invisible_tasks) or '无'}</li>"
        "</ul>"
    )

    config_diff = table(
        ["配置项", "AppAgent 原值", "本实验值", "说明"],
        [
            ["OPENAI_API_BASE", "https://api.openai.com/v1/chat/completions", "http://127.0.0.1:3425/v1/chat/completions", "指向本机 magpie"],
            ["OPENAI_API_KEY", "sk-", "magpie", "本机网关 key"],
            ["OPENAI_API_MODEL", "gpt-4-vision-preview", "auto/gpt-6-luna", "支持截图+文本的模型"],
            ["MAX_TOKENS", "300", "800", "避免长任务回复被截断"],
            ["MAX_ROUNDS", "20", "40", "长程任务需要更多轮"],
            ["REQUEST_INTERVAL", "10", "1", "本地网关无需 10s 间隔"],
        ],
        "related",
    )

    related = table(
        ["工作", "年份/venue", "输入模态", "与本题相关点"],
        [
            ["ProphetAgent", "FSE 2025", "UI 页面信息 + 事件区域截图 → GPT-4o", "CUTG + 自然语言测试用例；文本+视觉混合"],
            ["FuncDroid", "ISSTA 2026", "FFG + MLLM + 实时截图恢复", "功能间 flow；截图用于执行与 oracle"],
            ["ScenGen", "2025/2026", "截图 + CV/OCR + 多模态 LLM", "Observer/Supervisor；每步记录截图路径"],
            ["DroidAgent", "2023/2024", "widget/UI 表示 + 长短期记忆", "偏文本；没有强调视觉"],
            ["AppAgent（本报告）", "CHI 2025 / 开源", "截图 + labeled UI 元素 + GPT-4V", "Android 真机；tap/text/swipe/grid"],
            ["Mobile-Agent-v2", "NeurIPS 2024 / 开源", "截图 + Qwen-VL 图标描述", "多 agent 长程导航；需要 Qwen-VL 感知器"],
            ["Mobile-Agent-E", "2025 / 开源", "截图 + Qwen-VL 图标描述", "self-evolving 经验记忆；perceptor 依赖 Qwen-VL"],
        ],
        "related",
    )

    comparison = table(
        ["四卡任务：create → search → open → share", "旧 FCG 方案（内部）", "AppAgent（本报告）"],
        [
            ["设计结构", "功能卡 + 图 + 绑定器 + 编译器 + postcondition", "开源 AppAgent：截图 + 元素标注 + ReAct"],
            ["动作/轮数", "11 个编译动作", "见任务表"],
            ["LLM 调用", "11", "每轮 1 次，见任务表"],
            ["耗时", "688.8s 规划 + 105.7s 执行", "见任务表"],
            ["经验来源", "手工函数卡", "本轮为 no-doc 部署；未跑 AppAgent 的 exploration 文档"],
        ],
        "compare",
    )

    generated = time.strftime("%Y-%m-%d %H:%M")
    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AppAgent 开源实现真机验收报告</title>
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
.muted {{ color:var(--muted); }}
.warn {{ background:#fffaeb; border:1px solid #fedf89; color:#93370d; padding:9px 12px;
  border-radius:9px; font-size:13.5px; }}
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
  <h1>AppAgent 开源实现 · 真机验收报告</h1>
  <p>不做自研 agent 循环：直接运行 CHI 2025 开源的 AppAgent，只改配置 + 两处兼容性小补丁 + 薄封装。</p>
  <div class="meta">
    <span>日期 {generated}</span><span>Pixel 9 Pro XL · Android 16</span>
    <span>模型 auto/gpt-6-luna</span><span>AppAgent base {esc(commit)}</span>
    <span>完成任务 {successes}/{len(tasks)}</span>
  </div>
</header>

<section>
  <h2>结论</h2>
  <p>这一轮把 agent 本体换成了开源实现
  <a href="https://github.com/TencentQQGYLab/AppAgent">TencentQQGYLab/AppAgent</a>
  （MIT，CHI 2025）。没有重写 planner / executor / action 空间；只把模型地址、模型名、token
  上限和轮数上限改成适配本机 magpie 和长任务的值，加了两处设备/模型兼容性小补丁，再用一个
  薄封装完成 app 重置、任务喂入、截图/日志归档和最终评测。</p>
  <div class="kv">
    <div><span class="muted">严格成功</span><b>{successes}/{len(tasks)}</b></div>
    <div><span class="muted">文本检查通过</span><b>{text_ok}/{len(tasks)}</b></div>
    <div><span class="muted">VLM 认可</span><b>{verifier_ok}/{len(tasks)}</b></div>
    <div><span class="muted">总轮数</span><b>{total_rounds}</b></div>
    <div><span class="muted">Agent 总耗时</span><b>{int(total_agent)}s</b></div>
    <div><span class="muted">总墙钟</span><b>{int(total_wall)}s</b></div>
    <div><span class="muted">真实截图</span><b>{total_shots}</b></div>
  </div>
  <p class="muted">每一步截图都来自 AppAgent 自己保存的 labeled 截图
  （<code>runs/appagent/&lt;task&gt;/step_*.png</code>），不是脚本复现；最终判定由外部评测器
  拍终屏 + 严格文本检查完成，评测器不属于 AppAgent。两者都过才算成功，因此会出现
  “文本检查通过、但 VLM 无法从终屏确认隐藏状态（例如置顶/优先级）”的失败；任务表把两个
  检查分开列出，便于判断是 agent 没做，还是证据不可见。</p>
</section>

<section>
  <h2>用了哪个开源实现、改了什么</h2>
  <p><strong>Agent 本体：</strong>AppAgent（<code>third_party/AppAgent</code>，base commit
  <code>{esc(commit)}</code> + 下表配置/补丁）。它的流程是：ADB 截图 + uiautomator XML → 给可交互元素打编号
  → 多模态模型输出 <code>Observation / Thought / Action / Summary</code> → ADB 执行
  tap/text/long_press/swipe/grid。我们没有改它的 agent 逻辑。</p>
  <p>AppAgent 还自带 exploration → <code>auto_docs</code> 的元素级知识库（这是它原生的
  “经验积累”机制，和 RSI/ASPEC 的持久经验思路相近）。本轮为了快速验证，先跑 no-doc
  部署模式，没有生成 docs；这属于它的支持模式，但弱于完整的两阶段流程。</p>
  <p class="muted">为什么不是 Mobile-Agent-v2/E：它们的 Perceptor 依赖 Qwen-VL 图标描述
  （DashScope API 或本地 GPU）；当前环境只有 magpie 的 OpenAI-compatible 多模态模型。
  AppAgent 只需一个 OpenAI-compatible 视觉模型即可运行，是最小改动路径。</p>
  <h3>配置差异（仅 config.yaml）</h3>
  {config_diff}
  <p class="muted">原配置备份在 <code>third_party/AppAgent/config.yaml.orig</code>。
  除配置外，只新增了 <code>scripts/run_appagent_tasks.py</code> 作为运行/归档/评测的薄封装；
  它不参与决策。</p>
  <p><strong>仅有的两个代码兼容补丁：</strong></p>
  <ul>
    <li><code>scripts/and_controller.py</code> 的 <code>get_xml()</code>：
    <code>uiautomator dump</code> 返回非零时重试 4 次（每次 1s）。Android 16 在窗口尚未稳定时
    会偶发非零退出；不改变 prompt、动作空间或决策逻辑。</li>
    <li><code>scripts/model.py</code> 的 <code>parse_explore_rsp()/parse_grid_rsp()</code>：
    解析 <code>Action</code> 前去掉 Markdown 反引号/粗体符号（模型偶尔输出
    <code>`text("Travel")`</code> 或 <code>**tap(6)**</code>）；只做字符串清洗，
    不改变动作词表。</li>
  </ul>
  <p>另外薄封装在把设备交给 AppAgent 前会停掉自用的 uiautomator2/ATX instrumentation
  （显式 kill 设备侧 <code>com.wetest.uia2</code> 的 <code>app_process</code>），避免与
  AppAgent 的 <code>adb shell uiautomator dump</code> 冲突；否则 Android 16 上 dump 会返回 137。</p>
</section>

<section>
  <h2>任务结果</h2>
  {result_table}
  {failure_summary}
  <p class="muted">AppAgent 在 no-doc 部署模式下运行：没有先跑 exploration 生成文档库。
  这是 AppAgent 支持的模式，但比论文中的“先探索再部署”更弱。“最长连续重复动作”只做统计，
  用来暴露假进展：连续多次相同动作且界面未变，说明 agent 没有 stall 检测/回退机制。</p>
</section>

{''.join(task_section(task, i) for i, task in enumerate(tasks, 1))}

<section>
  <h2>相关工作的输入模态</h2>
  {related}
  <p class="muted">结论：最近的相关工作大多已经使用截图/多模态；DroidAgent 偏 widget/文本。
  我们之前纯文本 UI 树的 FCG 方案确实落后，这也是这次换成开源截图 agent 的原因。</p>
</section>

<section>
  <h2>与旧 FCG 方案的直接对比</h2>
  {comparison}
  <p class="muted">旧方案数据来自 <code>runs/real/pilot_complex_flow.jsonl</code>；
  AppAgent 数据来自本报告任务表。两者都在同一台真机上完成，但输入/知识来源不同，
  不是严格消融。</p>
</section>

<section>
  <h2>局限</h2>
  <ul>
    <li>AppAgent 的部署模式没有独立 planner / verifier / 跨任务经验记忆；长任务主要靠
    上一轮 <code>Summary</code> 维持上下文。没有 stall 检测：如果某个点击不生效，模型可能
    连续多轮重复同一动作直到 <code>MAX_ROUNDS</code>（结果表中的“最长连续重复动作”列即为此）。</li>
    <li>本轮是 no-doc 模式，没有跑 AppAgent 的 exploration 文档库，因此弱于论文完整流程。</li>
    <li>动作空间只有 tap / text / long_press / swipe / grid，没有显式 back/home；任务中通过点击
    可见返回箭头完成返回。</li>
    <li><code>adb shell input text</code> 只适合 ASCII；本轮输入均为英文，中文输入未验证。</li>
    <li>任务集只有 {len(tasks)} 个，且主要是 OmniNotes；这是 idea 验证，不是完整 benchmark。</li>
    <li>还没有把 ProphetAgent / FuncDroid / ScenGen 放在同一任务集上做对照。</li>
    <li>最终判定依赖外部 VLM 评测器 + 文本检查；隐藏状态（例如“已归档”本身）只能从终屏推断。</li>
  </ul>
</section>

<section>
  <h2>复现</h2>
<pre># 1. 还原 AppAgent 原配置，再按上表改 config.yaml
cd third_party/AppAgent
cp config.yaml.orig config.yaml

# 2. 运行全部任务（薄封装：重置 app、喂任务、归档截图、最终评测）
cd ../..
python scripts/run_appagent_tasks.py \\
  --tasks benchmark/agent_tasks.yaml \\
  --out runs/appagent

# 3. 重新生成报告
python scripts/build_appagent_report.py</pre>
  <p class="muted">证据目录：<code>runs/appagent/&lt;task&gt;/</code>（result.json、steps.json、
  appagent_log.jsonl、step_*.png、final.jpg）；AppAgent 原始目录：
  <code>third_party/AppAgent/tasks/task_&lt;id&gt;_*</code>。完整改动 diff：
  <code>runs/appagent/appagent_code.diff</code>。</p>
</section>
<footer>AppAgent 开源实现 · 真机验收报告 · 由 scripts/build_appagent_report.py 生成</footer>
</main></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
