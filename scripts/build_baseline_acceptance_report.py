#!/usr/bin/env python3
"""Build the stage acceptance report for the real-device baseline work.

Only real run artifacts are used: AgentProg's own screenshots and model-call
logs from runs/agentprog_smoke and runs/agentprog, and AppAgent's completed
results from runs/appagent.  Nothing in this report is a scripted recreation.
"""

from __future__ import annotations

import json
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
    load_yaml_tasks,
    render_action_timeline,
    render_llm_section,
    short,
)

SMOKE = ROOT / "runs" / "agentprog_smoke" / "omni_tag_search"
FIXED = ROOT / "runs" / "agentprog" / "omni_tag_search"
APPAGENT = ROOT / "runs" / "appagent"
OUT = ROOT / "docs" / "reports" / "baseline-acceptance.html"

EXTRA_CSS = """
.status { display:inline-block; padding:2px 9px; border-radius:999px;
          font-size:12px; font-weight:700; white-space:nowrap; }
.status.ok { color:#137a3f; background:#e6f5ec; }
.status.part { color:#9a5b00; background:#fff3d6; }
.status.todo { color:#b42318; background:#fdecea; }
.callout { background:#fff; border:1px solid var(--line); border-left:5px solid var(--accent);
           border-radius:8px; padding:14px 18px; margin:16px 0; }
.callout.warn { border-left-color:#d97706; background:#fffaf0; }
.callout.bad { border-left-color:#b42318; background:#fff7f6; }
.kv { display:grid; grid-template-columns:180px 1fr; gap:6px 14px; font-size:13px; }
.kv b { color:var(--muted); font-weight:600; }
.shot-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr));
             gap:14px; margin:14px 0; }
.shot-card { background:#fbfcfd; border:1px solid var(--line); border-radius:10px; padding:10px; }
.shot-card img { width:100%; height:auto; border-radius:7px; border:1px solid var(--line); }
.shot-card .cap { font-size:12px; }
.toc ul { margin:6px 0 0 18px; padding:0; }
.toc li { margin:2px 0; }
"""


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def shot_cards(task_dir: Path, captions: dict[int, str]) -> str:
    images = sorted((task_dir / "images").glob("*.png"))
    if not images:
        return '<p class="muted">没有截图。</p>'
    cards = []
    for index, path in enumerate(images):
        cap = captions.get(index, f"{path.name}（AgentProg 自采）")
        cards.append(
            f'<div class="shot-card">{img_tag(path, width=300)}'
            f'<div class="cap">{esc(cap)}</div></div>'
        )
    return f'<div class="shot-grid">{"".join(cards)}</div>'


def stp_block(task_dir: Path) -> str:
    text = read_text(task_dir / "workflow.ap")
    if not text:
        return '<p class="muted">没有 workflow.ap。</p>'
    return f"<pre>{esc(text)}</pre>"


def section_alignment(tasks: dict[str, dict[str, Any]]) -> str:
    rows = [
        ("真机、原生执行，不反复找用户确认",
         "ok", "Pixel 9 Pro XL / Android 16 / 47261FDAS00DTQ",
         "所有截图、UI dump、点击都来自这台设备；本轮按你最新要求已全部停止。"),
        ("本地 magpie 网关",
         "ok", "http://127.0.0.1:3425/v1，auto/gpt-6.1-sol",
         "AgentProg 通过 litellm 调用；llm_calls.jsonl 有原始请求/响应与耗时。"),
        ("baseline 必须是学术界、有论文、代码开源",
         "ok", "AgentProg（清华 AIR，arXiv 2512.10371，github.com/MobileLLM/AgentProg）",
         "论文 + 开源代码，可读可改，后续可直接在上面加探索/功能图。"),
        ("不重复造轮子，最多改配置/做最小兼容",
         "ok", "third_party/AgentProg 算法未改",
         "只加了 wrapper、坐标提示、UTF-8 修复、APP 映射、UITARS_MODEL 环境变量。"),
        ("不写测试",
         "ok", "没有新增测试",
         "验收证据是真机运行日志、截图和模型 I/O，不是自写测试。"),
        ("真实截图 + 每一步动作 + 模型请求/响应",
         "ok", "2 次 AgentProg 冒烟共 53 次真实模型调用、15 张自采截图",
         "报告内嵌 llm_calls.jsonl 原文；截图来自 AgentProg 的 capture_screenshot。"),
        ("判分放宽：只看最终可观察状态",
         "part", "final_state_v1（success/reason/evidence 三字段）",
         "AppAgent 8 任务已按此规则判分；AgentProg 尚无一次完整跑完的判分"
         "（只有 1 次子进程崩溃后的兜底判分）。"),
        ("任务要复杂、长程，数量多于 4 个",
         "ok", "8 个任务（OmniNotes 6 + Activity Diary 1 + Tasks.org 1）",
         "任务定义在 benchmark/agent_tasks.yaml；不是只有 4 个简单任务。"),
        ("成功率应接近 90%",
         "todo", "尚未验证；AppAgent 对照仅 2/8",
         "这是当前最大缺口。AgentProg 还未跑出完整基线数字，不能声称达到 90%。"),
        ("在 baseline 上增加探索 + graph/功能地图",
         "todo", "未开始",
         "按你的要求，先把 baseline 跑通并验收，再叠加探索/FCG。"),
        ("模型侧 JSON/Markdown 不超过 10 个字段",
         "ok", "STATE_VERIFIER 只有 3 个字段",
         "没有引入自定义复杂 schema；AgentProg 自己的 prompt 结构未改。"),
        ("不要商业/未开源方案",
         "ok", "mobile-use 已排除",
         "Minitap 的 mobile-use 商业且未开源；只作为排除项记录。"),
    ]
    labels = {"ok": "已对齐", "part": "部分", "todo": "未完成"}
    body = "".join(
        f"<tr><td>{esc(req)}</td><td><span class='status {status}'>{labels[status]}</span></td>"
        f"<td>{esc(now)}</td><td>{esc(note)}</td></tr>"
        for req, status, now, note in rows
    )
    return f"""
    <table>
      <thead><tr><th>你的要求</th><th>状态</th><th>当前实现</th><th>证据 / 差距</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    <p class="muted">状态说明：<span class="status ok">已对齐</span>
      <span class="status part">部分</span>
      <span class="status todo">未完成</span></p>
    """


def section_choice() -> str:
    return """
    <p><b>选型结论：AgentProg。</b>它满足“学术论文 + 开源代码 + 真机 Android”
    三个硬条件，而且它的 Semantic Task Program（STP）正好是后续挂
    “探索 / 功能地图（FCG）”的地方。</p>
    <table>
      <thead><tr><th>候选</th><th>结论</th><th>原因</th></tr></thead>
      <tbody>
        <tr><td><b>AgentProg</b>（清华 AIR，arXiv 2512.10371）</td>
            <td><span class="status ok">采用</span></td>
            <td>论文 + 开源；STP + 代码生成/WPC 双模式 + belief state；
                UI-TARS 视觉定位；支持真机 Android。</td></tr>
        <tr><td>mobile-use（Minitap）</td><td><span class="status todo">排除</span></td>
            <td>商业产品、代码未开源，无法对照与二次开发（按你的要求排除）。</td></tr>
        <tr><td>Mobile-Agent-v3 / V-Droid</td><td><span class="status part">暂不采用</span></td>
            <td>依赖专用模型或较重环境，本轮不适合做可复现的本地基线。</td></tr>
        <tr><td>AppAgent</td><td><span class="status part">仅作对照</span></td>
            <td>开源学术 Agent，但设计较早；同一批任务、同一判分规则下 2/8。</td></tr>
        <tr><td>此前自研 Agent</td><td><span class="status todo">放弃</span></td>
            <td>属于重复造轮子，不符合“用开源实现、最小改动”的要求。</td></tr>
      </tbody>
    </table>
    """


def section_changes() -> str:
    rows = [
        ("scripts/run_agentprog_tasks.py", "新增（wrapper）",
         "设备重置/启动/首次引导关闭/通知权限；ModelTrace；final_state_v1；批量子进程与超时。"),
        ("third_party/AgentProg/agentprog/all_utils/ui_tars_utils.py", "小改",
         "在 UI-TARS API prompt 中明确要求 0–1000 归一化坐标（模型原先返回缩放图像像素，点击偏移）。"),
        ("third_party/AgentProg/agentprog/all_utils/mobile_utils.py", "小改",
         "UITARS_MODEL 环境变量；补 OmniNotes / Activity Diary / Tasks.org 的启动 Activity 映射。"),
        ("third_party/AgentProg/agentprog/plan/code_exec/workflow/generate_workflow.py"
         "<br>.../workflow_query_llm.py", "小改",
         "Windows 下 workflow.ap 与统计文件按 UTF-8 读写，避免 GBK 编码错误。"),
        ("benchmark/agent_tasks.yaml", "任务定义",
         "8 个长程任务；OmniNotes 标签目标改为在正文写 #urgent（APP 的真实标签语义）。"),
        ("mobile_agent/prompts.py, mobile_agent/llm.py", "复用",
         "final_state_v1 最终态判定器（3 字段 JSON）；magpie VLM 客户端。"),
    ]
    body = "".join(
        f"<tr><td><code>{esc(path)}</code></td><td>{esc(kind)}</td><td>{esc(what)}</td></tr>"
        for path, kind, what in rows
    )
    return f"""
    <table>
      <thead><tr><th>文件</th><th>性质</th><th>改动 / 原因</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    <p class="muted">AgentProg 的规划、代码生成、WPC、belief state、UI-TARS 解析逻辑均未改动；
    报告里所有 AgentProg 行为都能在开源代码里对照。</p>
    """


def section_smoke_old() -> str:
    goal = "（旧目标）创建 Urgent 笔记，要求用工具栏“添加标签”动作加 urgent 标签，保存后搜索 urgent。"
    rows = []
    summary = load_json(ROOT / "runs" / "agentprog_smoke" / "summary.json", [])
    if isinstance(summary, list):
        for row in summary:
            if row.get("id") == "omni_tag_search":
                goal = str(row.get("goal", goal))
    captions = {
        0: "notes 列表（空）",
        1: "点 FAB 后展开的“文本注释 / 清单 / 语音”菜单",
        2: "文本笔记编辑器 + 键盘",
        3: "标题输入 Urgent",
        4: "正文区域获得焦点",
        5: "正文写入 Fix login bug",
        6: "正文输入完成后的编辑器",
        7: "点“添加标签”后：黄色提示“没有可用的标签，请先…添加 # 开头的标签”",
        8: "Agent 自行改写正文为“Fix login bug #urgent”",
        9: "第二次点“添加标签”仍是同一提示（工具栏标签选择器无可用项）",
    }
    return f"""
    <p>这是 <b>19:32–19:53</b> 的一次完整冒烟：AgentProg 在真机上从空列表一路做到
    “标题 Urgent + 正文 Fix login bug + 写入 #urgent”。它证明了整条链路真的能驱动真机；
    也暴露了旧目标把“添加标签”写死成工具栏动作的问题。</p>
    <div class="goal"><b>目标（旧）：</b>{esc(goal)}</div>
    <h3>AgentProg 生成的 STP（workflow.ap 原文）</h3>
    {stp_block(SMOKE)}
    <h3>真机动作时间线</h3>
    {render_action_timeline(SMOKE)}
    <h3>AgentProg 自己截取的 10 张真机画面</h3>
    {shot_cards(SMOKE, captions)}
    <div class="callout warn">
      <b>关键发现：</b>OmniNotes 的标签是正文里的 <code>#hashtag</code>；
      在没有标签的笔记上，工具栏“添加标签”只会弹出黄色提示。
      Agent 看到提示后自己改写了正文（screenshot_8），但旧 STP 的字面步骤仍然是
      “use the toolbar action”，WPC 因此一直 hold，形成死循环。
      这是<b>目标措辞与 APP 语义不一致</b>，不是 AgentProg 的规划器坏了。
    </div>
    <h3>本次运行的模型 I/O</h3>
    {render_llm_section(SMOKE)}
    """


def section_smoke_fixed() -> str:
    captions = {
        0: "notes 列表（空）",
        1: "FAB 展开菜单",
        2: "文本笔记编辑器",
        3: "标题 Urgent 已输入",
        4: "正文区域获得焦点（随后写入 Fix login bug）",
    }
    return f"""
    <p>把目标改成“在正文写 <code>#urgent</code>（OmniNotes 的真实标签存储方式）”后，
    STP 立刻从“工具栏动作”变成了“创建正文含 #urgent 的笔记并保存”。
    第二次冒烟在 <b>21:28–21:40</b> 跑到正文输入 <code>Fix login bug</code>，
    随后按你的要求全部停止，尚未产出最终判分。</p>
    <div class="goal"><b>目标（现行）：</b>创建标题 Urgent、正文
      “Fix login bug” 的文本笔记；把标签写成正文里的 <code>#urgent</code>；
      保存、返回列表、搜索 urgent，最终停在显示 Urgent 笔记的搜索结果。</div>
    <h3>修正后的 STP</h3>
    {stp_block(FIXED)}
    <h3>真机动作时间线</h3>
    {render_action_timeline(FIXED)}
    <h3>AgentProg 自采画面（5 张）</h3>
    {shot_cards(FIXED, captions)}
    <h3>本次运行的模型 I/O（19 次调用）</h3>
    {render_llm_section(FIXED)}
    """


def section_appagent(tasks: dict[str, dict[str, Any]]) -> str:
    rows = []
    cards = []
    successes = 0
    for task_id, task in tasks.items():
        result = load_json(APPAGENT / task_id / "result.json", {})
        ok = result.get("success") is True
        successes += 1 if ok else 0
        rows.append(
            "<tr>"
            f"<td><code>{esc(task_id)}</code></td>"
            f"<td>{badge(result.get('success'))}</td>"
            f"<td>{esc(result.get('rounds', '—'))}</td>"
            f"<td>{esc(result.get('appagent_seconds', '—'))}s</td>"
            f"<td>{esc(short(result.get('reason', ''), 240))}</td>"
            "</tr>"
        )
        final = APPAGENT / task_id / "final.jpg"
        cards.append(
            f'<div class="shot-card">{img_tag(final, width=300)}'
            f'<div class="cap">{badge(result.get("success"))} '
            f'<code>{esc(task_id)}</code><br>{esc(short(result.get("reason", ""), 120))}</div></div>'
        )
    return f"""
    <p>AppAgent 不是本轮的 baseline，但它已经<b>完整跑完 8 个任务</b>，
    且用的是同一套 final_state_v1 判定，所以可以作为“任务难度 / 判分规则”的对照。
    本次结果：<b>{successes}/8</b>。</p>
    <table>
      <thead><tr><th>任务</th><th>结果</th><th>轮数</th><th>耗时</th><th>判定理由（截断）</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <h3>8 个任务的最终画面</h3>
    <div class="shot-grid">{''.join(cards)}</div>
    <p class="muted">AppAgent 使用 auto/gpt-6-luna；AgentProg 使用 auto/gpt-6.1-sol。
    两者模型不同，因此这组数字只用于说明任务难度和判分规则，不作为等模型对比。</p>
    """


def section_assessment() -> str:
    return """
    <div class="callout">
      <b>结论：方案方向是对的，但验收只完成了“能跑”，还没完成“效果”。</b>
      学术开源基座 + 最小 wrapper + 最终态判分 + 真机证据，这四点都已经落地；
      但 AgentProg 还没有跑出任何一个完整任务的最终判分，所以现在不能回答
      “成功率是多少、是否接近 90%”。
    </div>
    <h3>做得好的地方</h3>
    <ul>
      <li><b>可对照、可修改：</b>AgentProg 的 STP/WPC/代码生成/视觉定位都在开源代码里，
          后续加探索与功能图有明确挂载点。</li>
      <li><b>没有重复造轮子：</b>规划与执行全部用上游实现；wrapper 只做设备环境、日志和判分。</li>
      <li><b>证据可审计：</b>每一步都有真机截图、动作时间、模型原始请求/响应与耗时。</li>
      <li><b>判分不看过程：</b>只看最终屏幕是否满足目标，避免“路径不同就判失败”。</li>
      <li><b>环境问题已工程化：</b>首次引导、通知权限、输入法、APP 启动 Activity 都已自动处理。</li>
    </ul>
    <h3>风险与不够好的地方</h3>
    <ul>
      <li><b>速度慢：</b>gpt-6.1-sol 下每步约 1.5–3 分钟；一个 6–8 步任务要 15–25 分钟，
          8 任务全量要好几个小时。</li>
      <li><b>成功率未知：</b>AppAgent 对照只有 2/8；AgentProg 尚无完整数字。
          距离你期望的 90% 还有明显差距，必须先补基线数字。</li>
      <li><b>字面步骤会卡住 WPC：</b>标签任务已证明，STP 若把“用工具栏动作”写死，
          即使 Agent 已经用 #urgent 达成目标，WPC 仍会 hold。目标措辞必须贴合 APP 语义。</li>
      <li><b>外部中断：</b>Phase A 被低内存回收器停过一次；本次又按你的要求暂停。
          两次都不是 Agent 失败，但导致没有完整判分。</li>
      <li><b>任务集仍偏 OmniNotes：</b>8 个任务里 6 个是 OmniNotes，
          Activity Diary / Tasks.org 各 1 个；跨 APP 覆盖还不够。</li>
    </ul>
    """


def section_next() -> str:
    return """
    <p>下面四条路，建议先走 <b>A</b>，拿到一个完整成功样本后再批量。</p>
    <table>
      <thead><tr><th>选项</th><th>做什么</th><th>预计时间</th><th>产出</th></tr></thead>
      <tbody>
        <tr><td><b>A（建议）</b></td><td>只跑修正后的 <code>omni_tag_search</code></td>
            <td>10–20 分钟</td><td>第一个 AgentProg 完整 result.json + 最终判分</td></tr>
        <tr><td>B</td><td>直接重跑 Phase A 的 4 个任务</td>
            <td>1–2 小时</td><td>4 个任务数字；中途失败会浪费时间</td></tr>
        <tr><td>C</td><td>先调任务/模型再跑（换更快模型、缩短步骤）</td>
            <td>视调整而定</td><td>更快，但偏离“原样学术 baseline”</td></tr>
        <tr><td>D</td><td>先讨论方案与任务集，不动设备</td>
            <td>—</td><td>确认后再跑</td></tr>
      </tbody>
    </table>
    <div class="callout warn">
      <b>关于中断：</b>Claude Code 在系统内存紧张时会回收后台命令。若要避免，
      可用 <code>CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1</code> 启动本会话，
      或把批测拆小、在前台跑。本轮两次中断都不是 Agent 或设备的问题。
    </div>
    """


def section_files() -> str:
    return """
    <table class="mini">
      <thead><tr><th>内容</th><th>路径</th></tr></thead>
      <tbody>
        <tr><td>8 个任务定义</td><td><code>benchmark/agent_tasks.yaml</code></td></tr>
        <tr><td>AgentProg wrapper / 判分</td><td><code>scripts/run_agentprog_tasks.py</code></td></tr>
        <tr><td>旧目标冒烟（34 次调用 / 10 张截图）</td>
            <td><code>runs/agentprog_smoke/omni_tag_search/</code></td></tr>
        <tr><td>修正目标后的冒烟（19 次调用 / 5 张截图）</td>
            <td><code>runs/agentprog/omni_tag_search/</code></td></tr>
        <tr><td>AppAgent 8 任务对照</td><td><code>runs/appagent/*/result.json</code></td></tr>
        <tr><td>本报告生成脚本</td><td><code>scripts/build_baseline_acceptance_report.py</code></td></tr>
        <tr><td>此前的 SpecFCG 闭环报告（已归档）</td>
            <td><code>docs/reports/acceptance-report.html</code></td></tr>
        <tr><td>实验记录</td><td><code>docs/experiments/2026-11-10-real-device-pilot.md</code></td></tr>
      </tbody>
    </table>
    <p class="muted">复现命令：</p>
    <pre>.venv-agentprog/Scripts/python scripts/run_agentprog_tasks.py \\
  --tasks omni_tag_search --out runs/agentprog --per-task-timeout 1800

.venv-agentprog/Scripts/python scripts/run_agentprog_tasks.py \\
  --tasks omni_tag_search,omni_four_card_share,diary_officework_session,tasks_buy_milk \\
  --out runs/agentprog --per-task-timeout 2400

python scripts/build_baseline_acceptance_report.py</pre>
    """


def build() -> str:
    tasks = load_yaml_tasks()
    smoke_calls = sum(
        1 for line in read_text(SMOKE / "llm_calls.jsonl").splitlines() if line.strip()
    )
    fixed_calls = sum(
        1 for line in read_text(FIXED / "llm_calls.jsonl").splitlines() if line.strip()
    )
    smoke_shots = len(list((SMOKE / "images").glob("*.png")))
    fixed_shots = len(list((FIXED / "images").glob("*.png")))
    appagent_ok = sum(
        1
        for task_id in tasks
        if load_json(APPAGENT / task_id / "result.json", {}).get("success") is True
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentProg 真机基线阶段性验收报告</title>
<style>{CSS}{EXTRA_CSS}</style>
</head>
<body>
<main>
  <h1>AgentProg 真机基线阶段性验收报告</h1>
  <p class="sub">2026-11-10 21:40 · Pixel 9 Pro XL / Android 16 / 47261FDAS00DTQ ·
     本地 magpie · 全部数字与截图来自真实运行</p>

  <div class="callout">
    <b>一句话结论：</b>学术开源 baseline（AgentProg）已经在真机上跑通“看屏幕 → 生成 STP →
    代码生成 / WPC → UI-TARS 定位 → 真机点击 → 再观察”的全链路，并留下了可审计的模型 I/O 与截图；
    但完整 8 任务的最终判分尚未产出（两次外部中断），所以“成功率是否接近 90%”现在还不能回答。
  </div>

  <div class="cards">
    <div class="card"><div class="n">{smoke_calls + fixed_calls}</div>
      <div class="l">真实模型调用（两次冒烟）</div></div>
    <div class="card"><div class="n">{smoke_shots + fixed_shots}</div>
      <div class="l">AgentProg 真机自采截图</div></div>
    <div class="card"><div class="n">0</div>
      <div class="l">AgentProg 完整跑完的任务（另有 1 次崩溃后兜底判分）</div></div>
    <div class="card"><div class="n">{appagent_ok}/8</div>
      <div class="l">AppAgent 同规则对照（非 baseline）</div></div>
  </div>

  <div class="toc">
    <b>目录</b>
    <ul>
      <li><a href="#align">1. 意图对齐：你的要求 vs 当前状态</a></li>
      <li><a href="#why">2. 为什么选 AgentProg（以及排除了什么）</a></li>
      <li><a href="#changes">3. 最小改动清单</a></li>
      <li><a href="#smoke">4. 真机证据：旧目标冒烟（到标签死循环）</a></li>
      <li><a href="#fixed">5. 目标修正后的第二次冒烟</a></li>
      <li><a href="#appagent">6. 对照：AppAgent 8 任务（同一最终态规则）</a></li>
      <li><a href="#assess">7. 方案评估：好的地方与风险</a></li>
      <li><a href="#next">8. 下一步（请你选）</a></li>
      <li><a href="#files">9. 复现与文件索引</a></li>
    </ul>
  </div>

  <h2 id="align">1. 意图对齐：你的要求 vs 当前状态</h2>
  {section_alignment(tasks)}

  <h2 id="why">2. 为什么选 AgentProg（以及排除了什么）</h2>
  {section_choice()}

  <h2 id="changes">3. 最小改动清单</h2>
  {section_changes()}

  <h2 id="smoke">4. 真机证据：旧目标冒烟（到标签死循环）</h2>
  {section_smoke_old()}

  <h2 id="fixed">5. 目标修正后的第二次冒烟</h2>
  {section_smoke_fixed()}

  <h2 id="appagent">6. 对照：AppAgent 8 任务（同一最终态规则）</h2>
  {section_appagent(tasks)}

  <h2 id="assess">7. 方案评估：好的地方与风险</h2>
  {section_assessment()}

  <h2 id="next">8. 下一步（请你选）</h2>
  {section_next()}

  <h2 id="files">9. 复现与文件索引</h2>
  {section_files()}

  <p class="files">本报告由 scripts/build_baseline_acceptance_report.py 生成；
  所有图片以 base64 内嵌，单文件可离线查看。</p>
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
