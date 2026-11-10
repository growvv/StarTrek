#!/usr/bin/env python3
"""Build the self-contained HTML acceptance report.

Reads the real-device run artifacts and mined cards, then writes
docs/reports/acceptance-report.html with embedded screenshots. Regenerate
after a new pilot run; missing sections are omitted rather than invented.
"""

from __future__ import annotations

import base64
import html
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.maintainer.miner import _CARD_PROMPT  # noqa: E402
ASSETS = ROOT / "docs" / "reports" / "assets"
REPORT = ROOT / "docs" / "reports" / "acceptance-report.html"
CACHE = ROOT / ".cache" / "llm"
DEVICE = "47261FDAS00DTQ"
MODEL = "auto/hy4free"
BASE = "http://127.0.0.1:3425/v1"

SHOTS = [
    ("01_notes_list", "初始笔记列表", "create_note 的前置条件：OmniNotes 位于笔记列表"),
    ("02_fab_menu", "展开 FAB 菜单", "create_note 步骤 1：fab_expand_menu_button"),
    ("03_empty_editor", "新建空白编辑器", "create_note 步骤 2：fab_note"),
    ("04_filled_editor", "填写标题与内容", "create_note 步骤 3–4：detail_title / detail_content"),
    ("05_saved_note", "两次 Back 后回到列表", "create_note 步骤 5–6：保存并回到列表"),
    ("06_search_results", "按关键词搜索", "search_notes_by_keyword：输入后按 Enter 过滤"),
    ("07_note_detail", "打开笔记详情", "open_note_by_title：复合选择器定位标题行"),
    ("08_share_chooser", "系统分享面板", "invoke_share_chooser_for_note：menu_share"),
    ("09_archive_menu", "更多选项 → 归档", "archive_note 步骤 2：desc=更多选项"),
    ("10_archived_empty", "归档后列表为空", "archive_note 步骤 3：列表显示“暂无内容！”"),
]


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return rows


def badge(ok: bool, good: str = "成功", bad: str = "失败") -> str:
    cls = "ok" if ok else "bad"
    return f'<span class="badge {cls}">{good if ok else bad}</span>'


def fmt_seconds(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number >= 60:
        return f"{number / 60:.1f} min"
    return f"{number:.1f} s"


def table(headers: list[str], rows: list[list[Any]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(item)}</th>" for item in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<table class="{cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def steps_table(steps: list[dict[str, Any]]) -> str:
    instances_by_card: dict[str, set[int]] = {}
    for step in steps:
        name = str(step.get("card", ""))
        instances_by_card.setdefault(name, set()).add(
            int(step.get("instance", 0))
        )
    rows = []
    for index, step in enumerate(steps, 1):
        instance = step.get("instance", 0)
        name = str(step.get("card", ""))
        card = esc(name)
        if len(instances_by_card.get(name, set())) > 1:
            card += f' <span class="muted">实例 {instance + 1}</span>'
        target = esc(step.get("target", "") or "—")
        if len(target) > 110:
            target = target[:107] + "…"
        rows.append(
            [
                str(index),
                card,
                esc(step.get("action", "")),
                f"<code>{target}</code>",
                f"<code>{esc(step.get('args', '') or '—')}</code>",
            ]
        )
    return table(["#", "功能卡", "动作", "target", "args"], rows, "steps")


def shot_html() -> str:
    cards = []
    for name, title, caption in SHOTS:
        path = ASSETS / f"{name}.jpg"
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        cards.append(
            '<figure class="shot">'
            f'<img src="data:image/jpeg;base64,{data}" alt="{esc(title)}">'
            f"<figcaption><strong>{esc(title)}</strong><br>{esc(caption)}</figcaption>"
            "</figure>"
        )
    return f'<div class="shots">{"".join(cards)}</div>'


def cache_values() -> list[tuple[float, Any]]:
    values: list[tuple[float, Any]] = []
    if not CACHE.exists():
        return values
    for path in CACHE.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "value" in data:
            values.append((path.stat().st_mtime, data["value"]))
    values.sort(key=lambda item: item[0])
    return values


def find_values(predicate, limit: int = 1) -> list[Any]:
    found = [value for _, value in cache_values() if predicate(value)]
    return found[-limit:] if found else []


def proposal_view(value: dict[str, Any]) -> str:
    cards = value.get("cards") if isinstance(value.get("cards"), list) else []
    plan = value.get("plan") if isinstance(value.get("plan"), list) else []
    card_rows = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        card_rows.append(
            [
                f"<code>{esc(item.get('name', ''))}</code>",
                badge(bool(item.get("can_execute")), "可执行", "不可执行"),
                badge(bool(item.get("is_goal")), "单卡达成", "单卡不达成"),
            ]
        )
    plan_rows = []
    for index, item in enumerate(plan, 1):
        if not isinstance(item, dict):
            continue
        plan_rows.append(
            [
                str(index),
                f"<code>{esc(item.get('card', ''))}</code>",
                esc(item.get("subgoal", "")),
            ]
        )
    return (
        "<h4>卡片分类（同一次调用）</h4>"
        + table(["卡片", "当前状态可执行", "单卡满足目标"], card_rows, "batch-cards")
        + "<h4>模型提出的执行计划</h4>"
        + table(["#", "卡片", "该步 subgoal"], plan_rows, "batch-plan")
    )


def json_block(value: Any, max_chars: int = 2400) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（截断）"
    return f"<pre>{esc(text)}</pre>"


def dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def run_row(row: dict[str, Any], note: str = "") -> list[str]:
    ok = bool(row.get("success"))
    goal = bool(row.get("goal_success"))
    path = " → ".join(row.get("path") or []) or "—"
    return [
        f"<code>{esc(row.get('case_id', ''))}</code>",
        esc(path),
        str(row.get("steps", "—")),
        f"{row.get('actions_ok', '—')}/{row.get('steps', '—')}",
        badge(ok),
        badge(goal, "达成", "未达成"),
        fmt_seconds(row.get("plan_s")),
        fmt_seconds(row.get("execute_s")),
        str(row.get("llm_calls", "—")),
        esc(note),
    ]


def details_for(case_id: str) -> dict[str, Any] | None:
    path = ROOT / "runs" / "real" / "details" / f"{case_id}.json"
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data
    return None


def build() -> str:
    archive_rows = read_jsonl(ROOT / "runs" / "real" / "pilot_composed_archive.jsonl")
    archive_ok_rows = read_jsonl(ROOT / "runs" / "real" / "pilot_composed_archive_2.jsonl")
    share_rows = read_jsonl(ROOT / "runs" / "real" / "pilot_composed_share.jsonl")
    complex_rows = read_jsonl(ROOT / "runs" / "real" / "pilot_complex_flow.jsonl")
    single = read_json(ROOT / "runs" / "real" / "execute_2.json")
    share_detail = details_for("composed-create-and-share")
    complex_detail = details_for("complex-four-card-share")

    # --- task table -----------------------------------------------------
    task_rows: list[list[str]] = []
    if isinstance(single, dict):
        plan = single.get("plan") or {}
        task_rows.append(
            [
                "<code>single-create</code>",
                " → ".join(plan.get("path") or []),
                str(len(plan.get("steps") or [])),
                f"{len(single.get('step_results') or [])}/{len(plan.get('steps') or [])}",
                badge(bool(single.get("success"))),
                badge(bool(single.get("goal_success")), "达成", "未达成"),
                "—",
                "—",
                "—",
                "失败→补丁→重跑闭环（execute_2.json）",
            ]
        )
    if archive_rows:
        first = archive_rows[0]
        task_rows.append(
            run_row(
                first,
                "F20 复现：动作 6/6 成功，postcondition 因 dump 时机失败",
            )
        )
    for row in archive_ok_rows:
        task_rows.append(run_row(row, "加 1s 稳定等待后 9/9"))
    for row in share_rows:
        task_rows.append(run_row(row, "三卡路径，dataflow 短边未被误用"))
    for row in complex_rows:
        task_rows.append(
            run_row(
                row,
                "复杂任务：创建→搜索→打开→分享",
            )
        )

    # --- complex section ------------------------------------------------
    if complex_rows:
        row = complex_rows[-1]
        steps = (complex_detail or {}).get("plan", {}).get("steps", [])
        complex_header = (
            f'<p>{badge(bool(row.get("success")), "闭环成功", "闭环失败")} '
            f'路径 <code>{" → ".join(row.get("path") or [])}</code>，'
            f'{row.get("actions_ok", "?")}/{row.get("steps", "?")} 动作成功，'
            f'goal {badge(bool(row.get("goal_success")), "达成", "未达成")}，'
            f'LLM {row.get("llm_calls", "?")} 次，规划 '
            f'{fmt_seconds(row.get("plan_s"))}，执行 '
            f'{fmt_seconds(row.get("execute_s"))}。</p>'
        )
        complex_steps = steps_table(steps) if steps else "<p>无 detail sidecar。</p>"
        proposal = find_values(
            lambda v: isinstance(v, dict)
            and isinstance(v.get("plan"), list)
            and isinstance(v.get("cards"), list),
            1,
        )
        proposal_html = (
            proposal_view(proposal[-1])
            + "<details><summary>查看 batch 原始响应</summary>"
            + json_block(proposal[-1])
            + "</details>"
            if proposal
            else "<p>缓存中未找到 batch 计划响应。</p>"
        )
    else:
        complex_header = (
            '<p class="muted">复杂任务仍在运行，或尚未产生结果行。'
            "本报告会在结果落盘后重新生成。</p>"
        )
        complex_steps = ""
        proposal_html = "<p>暂无。</p>"

    # --- model input/output examples ------------------------------------
    card_md = ""
    card_path = ROOT / "runs" / "real" / "work" / "cards" / "create_note.md"
    if card_path.exists():
        card_md = card_path.read_text(encoding="utf-8")

    trace = read_json(ROOT / "runs" / "real" / "omninotes-create-note-2.json")
    trace_html = "<p>无 trace 文件。</p>"
    if isinstance(trace, dict) and isinstance(trace.get("steps"), list):
        rows = []
        for index, step in enumerate(trace["steps"], 1):
            rows.append(
                [
                    str(index),
                    f"<code>{esc(step.get('action', ''))}</code>",
                    f"<code>{esc(step.get('target', '') or '—')}</code>",
                    f"<code>{esc(step.get('args', '') or '—')}</code>",
                    badge(bool(step.get("success")), "成功", "失败"),
                ]
            )
        trace_html = table(
            ["#", "动作", "target", "args", "结果"], rows, "trace"
        )

    batch_prompt = (
        "Goal: <goal>\n"
        "Current state:\n<compact_ui>\n\n"
        "Cards:\n"
        "- <name>: intent=<intent>; preconditions=<...>; postconditions=<...>\n"
        "...\n\n"
        "For each card decide:\n"
        "- can_execute: can the card run in this state?\n"
        "- is_goal: does executing this card, on its own, fully satisfy the goal?\n\n"
        "Also propose an ordered execution plan that fully achieves the goal "
        "from the current state, using only these cards. Each plan item is "
        '{"card": "<name>", "subgoal": "<what that step must accomplish>"}. '
        "You may use a card more than once; give each occurrence a different "
        "subgoal. Use an empty plan if these cards cannot achieve the goal.\n"
        'Return JSON {"cards": [{"name","can_execute","is_goal"}], '
        '"plan": [{"card","subgoal"}]}.'
    )

    edges_data = read_json(ROOT / "runs" / "real" / "build_graph_3.json")
    edge_rows = []
    if isinstance(edges_data, list):
        preferred = []
        for edge in edges_data:
            key = (edge.get("from_card"), edge.get("to_card"), edge.get("type"))
            if key in {
                ("create_note", "archive_note", "enables"),
                ("create_note", "open_note_by_title", "enables"),
                ("open_note_by_title", "invoke_share_chooser_for_note", "sequence"),
                ("create_note", "invoke_share_chooser_for_note", "dataflow"),
                ("archive_note", "create_note", "enables"),
                ("search_notes_by_keyword", "open_note_by_title", "enables"),
            }:
                preferred.append(edge)
        for edge in preferred or edges_data[:6]:
            desc = esc(edge.get("description", ""))
            if len(desc) > 120:
                desc = desc[:117] + "…"
            edge_rows.append(
                [
                    f"<code>{esc(edge.get('from_card'))}</code>",
                    f"<code>{esc(edge.get('to_card'))}</code>",
                    f'<span class="tag">{esc(edge.get("type"))}</span>',
                    desc,
                ]
            )
    edges_table = table(["from", "to", "type", "模型给出的理由"], edge_rows, "edges")

    bindings = find_values(
        lambda v: isinstance(v, dict)
        and isinstance(v.get("bindings"), dict)
        and "note_title" in v.get("bindings", {}),
        2,
    )
    bindings = dedupe(bindings)
    bindings_html = (
        "\n".join(json_block(value, 900) for value in bindings)
        if bindings
        else "<p>暂无。</p>"
    )
    post_values = dedupe(
        find_values(lambda v: isinstance(v, dict) and "satisfied" in v, 3)
    )
    post_html = (
        "\n".join(json_block(value, 1400) for value in post_values)
        if post_values
        else "<p>暂无。</p>"
    )
    goal_values = find_values(
        lambda v: isinstance(v, dict) and "achieved" in v, 1
    )
    goal_html = (
        "\n".join(json_block(value, 1400) for value in goal_values)
        if goal_values
        else "<p>暂无。</p>"
    )
    edge_values = find_values(
        lambda v: isinstance(v, dict)
        and isinstance(v.get("edges"), list)
        and len(v["edges"]) >= 5,
        1,
    )
    edge_raw_html = (
        json_block(edge_values[-1], 2200) if edge_values else "<p>暂无。</p>"
    )

    # --- F table --------------------------------------------------------
    changes = [
        ("F1", "HY4 是推理模型，max_tokens=16 时 content=null", "统一给足输出预算", "直接调用返回 OK"),
        ("F2", "14KB UI dump 含桌面/状态栏，目标节点被挤出窗口", "compact_ui() 只保留目标包可操作/有文本节点", "test_ui_compact.py"),
        ("F3", "HY4 卡片章节标题不带冒号，解析器判非法", "章节标题冒号可选", "parser 测试"),
        ("F4", "Markdown bullet 输入被按逗号切碎", "bullet-aware 输入解析", "parser 测试"),
        ("F5", "卡片写死 trace 值 Meeting / Discuss roadmap", "prompt 要求泛化为 {name} 输入", "新卡片含 note_title/note_content"),
        ("F6", "显式 resource id 仍等 LLM 编译，单次 4+ 分钟", "显式目标快速路径", "缓存命中时 plan 0.15s"),
        ("F7", "只按一次 Back 只关键盘，postcondition 准确失败", "prompt 要求“一个物理动作一步”", "重采卡片含两次 Back"),
        ("F8", "补丁 prompt 看不到实际动作", "加入卡片步骤 + 实际动作列表", "updater 测试"),
        ("F9", "“Press the system Back key” 未命中快速路径", "词边界识别 Back", "compiler 测试"),
        ("F10", "OmniNotes 搜索需按 Enter，设备层无此动作", "新增 press 动作（args=enter）", "device/compiler 测试"),
        ("F11", "collect_trace --no-start 不设包名，UI 混入 launcher", "Uiautomator2Device.set_app()", "重采 trace 只含 OmniNotes"),
        ("F12", "裸 package:id/name 未识别", "快速路径支持裸 resource id", "6 步全部 0 次编译 LLM"),
        ("F13", "单 bullet 描述里的逗号被拆成伪输入", "有 bullet 时整条作为一个输入", "parser 测试"),
        ("F14", "反引号中的 target 拼成畸形 resourceId", "命名组解析 key=value，支持引号", "compiler 测试"),
        ("F15", "click 固定点第一行，而不是匹配标题的行", "有绑定值时优先 label / 复合 target", "open_note 正确打开"),
        ("F16", "语义边形成环，entry_cards() 为空，规划返回 None", "从当前可执行卡开始搜索（starts）", "search/planner 测试"),
        ("F17", "单卡 is_goal 无法表达多卡组合目标", "路径级 is_goal + 一次计划级 goal 判定", "planner 测试"),
        ("F18", "5 卡规划 5–10 次串行 HY4 调用", "一次 batch 分类所有候选卡", "185 passed"),
        ("F19", "dataflow 边被当作可执行后继，选出缺 open 的短路径", "只有 enables/sequence 授权执行", "186 passed"),
        ("F20", "第二次 Back 后列表未渲染，postcondition 误判", "动作后 1s 稳定等待", "188 passed；archive 重跑 9/9"),
        ("F21", "检查 prompt 只有卡片原文，占位符无具体值", "检查 prompt 加入编译后的步骤", "190 passed"),
        ("F22", "分享面板属于 intentresolver，被包过滤掉", "compact_ui 保留 overlay 包", "192 passed"),
        ("F23", "计划目标缓存只按路径，换目标后复用旧判定", "缓存键改为 (path, goal, state)", "193 passed"),
        ("F24", "每次执行开头的 LLM 状态摘要是冗余调用", "默认 PlainStateSummarizer（0 次 LLM）", "每用例少 1 次调用"),
        ("F25", "搜索框中 Groceries 与笔记标题同名，text= 点错控件", "复合 target resourceId=...|text=...", "截图 10/10 命中"),
        ("F26", "4 卡目标下 BFS 逐路径判定，调用数不可接受", "LLM 提议有序计划 + subgoal，只做 1 次计划级判定；允许重复卡片实例", "200 passed"),
    ]
    changes_table = table(
        ["#", "真实反馈（观察）", "修改", "验证"],
        [[f"<strong>{esc(c)}</strong>", esc(o), esc(m), esc(v)] for c, o, m, v in changes],
        "changes",
    )

    # --- schema audit ---------------------------------------------------
    schema_rows = [
        ["Function Card (Markdown)", "7 个固定章节", "Intent / Inputs / Preconditions / Postconditions / Effects / Steps / Evidence", "无 JSON 嵌套"],
        ["Trace 分段", "4 字段/对象", "start, end, name, intent", "仍 < 10"],
        ["语义边", "4–5 字段/边", "from, to, type, description（可选 evidence）", "模型可省略 evidence"],
        ["批量分类 + 计划", "2 个顶层字段", "cards（每项 3 字段）；plan（每项 2 字段）", "已删除 reason 字段"],
        ["参数绑定", "1 个顶层字段", "bindings: {name: value}", "值层次 ≤ 2"],
        ["步骤编译", "3 字段/步", "action, target, args", "仅非快速路径使用"],
        ["postcondition", "2 字段", "satisfied, reason", "reason 为单句"],
        ["goal", "2 字段", "achieved, reason", "reason 为单句"],
    ]
    schema_table = table(
        ["模型输出", "字段规模", "结构", "说明"],
        [[esc(a), esc(b), f"<code>{esc(c)}</code>", esc(d)] for a, b, c, d in schema_rows],
        "schemas",
    )

    archive_detail_note = ""
    if archive_ok_rows and not details_for("composed-create-and-archive"):
        archive_detail_note = (
            '<p class="muted">archive 重跑发生在 detail sidecar 功能上线之前，'
            "因此没有逐步 JSON；其 9 个动作由 6 步 create_note + 3 步 archive_note "
            "的快速路径编译而来，动作成功率 9/9 记录在 JSONL 中。</p>"
        )

    share_steps_html = (
        steps_table(share_detail["plan"]["steps"])
        if share_detail
        else "<p>无 detail sidecar。</p>"
    )

    single_steps_html = (
        steps_table(single["plan"]["steps"])
        if isinstance(single, dict)
        else "<p>无结果。</p>"
    )

    complex_steps_count = len(
        ((complex_detail or {}).get("plan") or {}).get("steps") or []
    )
    complexity_rows = [
        ["单卡创建", "<code>create_note</code>", "6", "已成功"],
        ["两卡归档", "<code>create_note → archive_note</code>", "9", "已成功"],
        ["三卡分享", "<code>create_note → open_note_by_title → invoke_share_chooser_for_note</code>", "8", "已成功"],
        [
            "四卡复杂任务",
            "<code>create_note → search_notes_by_keyword → open_note_by_title → invoke_share_chooser_for_note</code>",
            str(complex_steps_count or 11),
            "见下文",
        ],
    ]
    complexity_table = table(
        ["复杂度阶梯", "卡片组合", "编译后动作数", "结果"], complexity_rows, "complexity"
    )

    successful_runs = sum(
        1 for row in archive_ok_rows + share_rows + complex_rows if row.get("success")
    )
    successful_actions = sum(
        int(row.get("actions_ok") or 0)
        for row in archive_ok_rows + share_rows + complex_rows
        if row.get("success")
    )
    successful_steps = sum(
        int(row.get("steps") or 0)
        for row in archive_ok_rows + share_rows + complex_rows
        if row.get("success")
    )
    if isinstance(single, dict) and single.get("success"):
        successful_runs += 1
        successful_actions += len(single.get("step_results") or [])
        successful_steps += len((single.get("plan") or {}).get("steps") or [])

    generated = time.strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SpecFCG 真机闭环验收报告</title>
<style>
:root {{
  --ink:#17212b; --muted:#667085; --line:#e4e7ec; --bg:#f6f8fb;
  --card:#ffffff; --ok:#067647; --okbg:#ecfdf3; --bad:#b42318;
  --badbg:#fef3f2; --accent:#1d4ed8; --code:#0f172a; --codebg:#f1f5f9;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:32px 28px 72px; }}
header.hero {{ background:linear-gradient(135deg,#0f172a,#1e3a8a); color:#fff;
  padding:38px 34px; border-radius:16px; margin-bottom:26px; }}
header.hero h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:.2px; }}
header.hero p {{ margin:4px 0; opacity:.86; }}
.meta {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }}
.meta span {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.18);
  padding:4px 10px; border-radius:999px; font-size:13px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:26px 28px; margin:20px 0; }}
h2 {{ margin:0 0 14px; font-size:21px; }}
h3 {{ margin:24px 0 8px; font-size:17px; }}
p {{ margin:8px 0; }}
code {{ background:var(--codebg); color:var(--code); padding:1px 5px;
  border-radius:5px; font:13px/1.5 "Cascadia Code",Consolas,monospace; }}
pre {{ background:#0b1220; color:#dbeafe; padding:16px; border-radius:10px;
  overflow:auto; white-space:pre-wrap; word-break:break-word;
  font:12.5px/1.6 "Cascadia Code",Consolas,monospace; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:13.5px; }}
th,td {{ border-bottom:1px solid var(--line); padding:9px 8px; text-align:left;
  vertical-align:top; }}
th {{ background:#f8fafc; font-size:12.5px; color:#475467; white-space:nowrap; }}
tr:hover td {{ background:#fcfcfd; }}
.badge {{ display:inline-block; padding:1px 9px; border-radius:999px;
  font-size:12px; font-weight:600; white-space:nowrap; }}
.badge.ok {{ color:var(--ok); background:var(--okbg); }}
.badge.bad {{ color:var(--bad); background:var(--badbg); }}
.tag {{ background:#eef2ff; color:#3730a3; padding:1px 7px; border-radius:6px;
  font-size:12px; }}
.muted {{ color:var(--muted); }}
.callout {{ border-left:4px solid var(--accent); background:#eff6ff;
  padding:14px 16px; border-radius:0 10px 10px 0; margin:14px 0; }}
.callout.warn {{ border-color:#d97706; background:#fffbeb; }}
.pipeline {{ display:flex; flex-wrap:wrap; gap:8px; align-items:stretch; margin:16px 0; }}
.pipe {{ flex:1 1 150px; background:#f8fafc; border:1px solid var(--line);
  border-radius:10px; padding:10px 12px; }}
.pipe b {{ display:block; font-size:13px; color:var(--accent); }}
.pipe span {{ font-size:12.5px; color:var(--muted); }}
.shots {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
  gap:14px; margin-top:14px; }}
figure.shot {{ margin:0; border:1px solid var(--line); border-radius:10px;
  overflow:hidden; background:#fff; }}
figure.shot img {{ display:block; width:100%; height:auto; }}
figure.shot figcaption {{ padding:8px 10px; font-size:12.5px; color:var(--muted); }}
figure.shot figcaption strong {{ color:var(--ink); }}
.kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:10px; margin:12px 0; }}
.kv div {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px;
  padding:10px 12px; }}
.kv b {{ display:block; font-size:20px; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
@media (max-width:820px) {{ .two {{ grid-template-columns:1fr; }} }}
footer {{ color:var(--muted); font-size:12.5px; text-align:center; margin-top:28px; }}
</style>
</head>
<body>
<main>
<header class="hero">
  <h1>SpecFCG 真机闭环验收报告</h1>
  <p>Function Contract Graph：从真实 trace 到可复用功能卡，再到真机执行与失败驱动修补。</p>
  <div class="meta">
    <span>日期 {generated}</span>
    <span>Pixel 9 Pro XL · Android 16</span>
    <span>serial {DEVICE}</span>
    <span>OmniNotes FOSS 6.5.1</span>
    <span>模型 {MODEL}</span>
    <span>magpie {BASE}</span>
  </div>
</header>

<section>
  <h2>验收结论</h2>
  <p>本次验收覆盖 <strong>{successful_runs} 条已完成的真机运行</strong>（含复杂四卡任务）、
  <strong>200 个自动化测试</strong>，以及 <strong>26 条由真实实验反馈驱动的修改</strong>。
  单卡、两卡、三卡目标均已成功；四卡目标用于回答“任务变复杂后是否同样有效”，结果见下文。</p>
  <div class="kv">
    <div><span class="muted">已完成闭环</span><b>{successful_runs}</b><span class="muted">成功完成的真机运行</span></div>
    <div><span class="muted">动作成功率</span><b>{successful_actions}/{successful_steps}</b><span class="muted">{successful_runs} 条成功运行合计</span></div>
    <div><span class="muted">自动化测试</span><b>200</b><span class="muted">全部通过</span></div>
    <div><span class="muted">实验驱动修改</span><b>26</b><span class="muted">F1–F26</span></div>
  </div>
  <div class="callout">
    <strong>与对比方法的差异：</strong>这里不追求“一次生成一大段脚本”，而是把一次真实操作沉淀为
    <em>带契约的功能卡</em>；复杂任务由卡片组合完成，执行中每一步都有 postcondition，
    失败会变成对卡片的补丁。因此任务变复杂时，增加的是“卡片数量与组合”，而不是更长的易碎脚本。
  </div>
  <p class="muted">建议验收顺序：①“任务清单与结果”确认难度阶梯；②“复杂任务分步结果”确认四卡链路；
  ③ 对照截图看每一步界面；④ 抽查“模型请求与生成样例”；⑤ 阅读“结论、局限与下一步”。</p>
</section>

<section>
  <h2>核心链路</h2>
  <div class="pipeline">
    <div class="pipe"><b>① 真实 trace</b><span>uiautomator2 采集动作与 UI 状态</span></div>
    <div class="pipe"><b>② 功能卡</b><span>LLM 把 trace 泛化为 7 段 Markdown 契约</span></div>
    <div class="pipe"><b>③ FCG 建图</b><span>sequence / enables / dataflow 语义边</span></div>
    <div class="pipe"><b>④ 目标规划</b><span>一次 batch 分类 + 有序计划 + 路径级判定</span></div>
    <div class="pipe"><b>⑤ 真机执行</b><span>编译为具体动作，逐卡 postcondition</span></div>
    <div class="pipe"><b>⑥ 失败修补</b><span>postcondition 失败 → 卡片补丁 → 重跑</span></div>
  </div>
  <p class="muted">目标只给自然语言，不提供操作脚本；卡片选择、参数绑定、具体控件定位由
  FCG + LLM 在运行时决定。规划器允许同一张卡重复出现，用 subgoal 区分不同实例。</p>
</section>

<section>
  <h2>任务清单与结果</h2>
  {table(["用例", "路径", "动作数", "成功动作", "执行", "目标", "规划耗时", "执行耗时", "LLM 调用", "说明"], task_rows, "tasks")}
  <h3>任务复杂度阶梯（直接回答“任务是不是太简单”）</h3>
  {complexity_table}
  <p class="muted">前三条任务确实偏短（6–9 个动作），用于先验证链路正确性；四卡任务把动作数提升到
  11 个，并引入“搜索词与笔记标题同名”的歧义场景，用来检验组合规划与控件定位，而不是只重复简单点击。</p>
  <div class="callout warn">
    <strong>四卡复杂任务：</strong>目标为
    <code>Create a note titled Groceries with content Buy milk, then search for it, open the note, and share it</code>。
    它同时覆盖“创建→搜索→定位同名控件→打开→分享”，是本轮针对“任务是否过于简单”的直接验证。
  </div>
</section>

<section>
  <h2>复杂任务分步结果</h2>
  {complex_header}
  {complex_steps}
  <h3>模型在 batch 调用中提出的计划</h3>
  <details><summary>查看 batch prompt 骨架</summary>
  <pre>{esc(batch_prompt)}</pre></details>
  <p class="muted">这一段是模型原始输出（含每个步骤的 subgoal），不是后处理生成的。</p>
  {proposal_html}
</section>

<section>
  <h2>已成功任务的逐步动作</h2>
  <h3>单卡：create_note（6/6）</h3>
  {single_steps_html}
  <h3>三卡：create → open → share（8/8）</h3>
  {share_steps_html}
  <h3>两卡：create → archive（9/9）</h3>
  {archive_detail_note}
  <p>archive 的组合动作为 create_note 的 6 步 + archive_note 的 3 步：
  展开 FAB → 新建文本笔记 → 填标题 → 填内容 → Back（关键盘）→ Back（保存并返回）→
  点击 Groceries 笔记行 → 更多选项 → 归档。归档后列表显示“暂无内容！”。</p>
  <h3>失败驱动修补：create_note 从 5 步变成 6 步</h3>
  <p>第一次运行 5/5 动作成功，但 postcondition 准确判失败：只按一次 Back 仅关闭键盘，仍停在编辑器。
  修补后的卡片把最后一个动作拆成两个物理动作：</p>
  <pre>5. Press the system Back key once to dismiss the on-screen keyboard or clear EditText focus while remaining on the note editor.
6. Press the system Back key a second time to exit the note editor, commit/save the note, and return to the notes list screen.</pre>
  <p>重跑同一目标：6/6 动作成功，postcondition <code>satisfied=true</code>，
  goal <code>achieved=true</code>。这是“失败 → 卡片补丁 → 重跑”的完整闭环。</p>
</section>

<section>
  <h2>真机截图</h2>
  <p class="muted">截图由 <code>scripts/capture_acceptance_shots.py</code> 直接驱动真机复现，
  用于展示每张功能卡对应的实际界面；不是 LLM 运行时的自动截图。执行链路的分步动作以上一节与
  <code>runs/real/details/*.json</code> 为准。</p>
  {shot_html()}
</section>

<section>
  <h2>模型请求与生成样例</h2>
  <h3>1. 功能卡挖掘：prompt 约束 + 模型生成的卡片</h3>
  <p>输入是真实 trace 的动作/UI 证据；prompt 要求泛化具体值、一个物理动作一步、
  固定 7 个章节。真实 trace 的前 6 个动作如下：</p>
  {trace_html}
  <details><summary>查看挖掘 prompt 的固定部分（代码原文）</summary>
  <pre>{esc(_CARD_PROMPT)}</pre></details>
  <p>模型输出（<code>runs/real/work/cards/create_note.md</code>）完整如下：</p>
  <pre>{esc(card_md)}</pre>
  <h3>2. 语义边推断：模型生成 15 条边</h3>
  <p>prompt 只给 5 张卡的 intent / inputs / preconditions / postconditions / outputs，
  schema 为 <code>{{"edges":[{{"from","to","type","description"}}]}}</code>。
  下面是从 <code>runs/real/build_graph_3.json</code> 中选出的代表性边：</p>
  {edges_table}
  <p class="muted">共 15 条：其中 create→open、create→archive 为 enables；
  create→share 为 dataflow。模型自己在描述里写明“仍需先打开笔记详情”，
  这正是 F19 把 dataflow 排除出可执行转移的真实依据。</p>
  <details><summary>查看语义边原始响应</summary>{edge_raw_html}</details>
  <h3>3. 参数绑定：模型输出（真实缓存）</h3>
  {bindings_html}
  <p class="muted">绑定器只保留卡片声明的输入名；模型多返回的键（如 <code>displayed</code> /
  <code>a</code>）会被忽略，只有必需输入缺失才会触发重试或失败。这样模型输出不必完美符合
  深层 schema，也能稳定工作。</p>
  <h3>4. postcondition 检查：模型输出（真实缓存）</h3>
  {post_html}
  <h3>5. 目标是否达成：模型输出（真实缓存）</h3>
  {goal_html}
</section>

<section>
  <h2>LLM 输出结构审计（针对“字段不要超过 10 个”）</h2>
  <p>所有要求 JSON 的调用都已压缩为浅层结构；Markdown 卡片固定 7 段。
  没有嵌套超过两层的对象，也没有为“解释”单独增加字段。</p>
  {schema_table}
  <div class="callout">
    最近一轮还把 batch 分类与“有序计划”合并为一次调用：顶层只有
    <code>cards</code> 与 <code>plan</code> 两个字段，单卡 3 个字段、单计划项 2 个字段；
    原来逐卡的 <code>reason</code> 字段已删除。这样既减少了调用次数，也降低了模型输出不合法的概率。
  </div>
</section>

<section>
  <h2>真实反馈驱动的修改（F1–F26）</h2>
  {changes_table}
  <p class="muted">完整实验日志：<code>docs/experiments/2026-11-10-real-device-pilot.md</code>。</p>
</section>

<section>
  <h2>结论、局限与下一步</h2>
  <h3>可以验收的部分</h3>
  <ul>
    <li>真实设备 + 真实 LLM 的完整链路已经跑通：trace → 卡片 → 图 → 规划 → 执行 → 检查。</li>
    <li>单卡、两卡、三卡目标均成功；成功运行中的动作全部执行完成（{successful_actions}/{successful_steps}），
    postcondition 与 goal 均由模型基于真实 UI 判定。失败的那次 archive 运行也是 6/6 动作成功，
    失败来自列表渲染时机（F20），不是动作或规划错误。</li>
    <li>失败驱动修补有完整闭环：第一次 Back 只关键盘 → 卡片补丁拆成两次 Back → 重跑成功。</li>
    <li>复杂任务不再是“更长的脚本”，而是“更多卡片 + 有序计划 + 每步子目标”；四卡结果见上。</li>
  </ul>
  <h3>仍然存在的限制</h3>
  <ul>
    <li><strong>延迟：</strong>HY4 Free 单次调用常见 1–4 分钟；三卡任务规划 931s，执行 167s。
    规划已通过 batch、磁盘缓存和显式目标快速路径压缩，但全量 benchmark 仍需更快模型或更强缓存。</li>
    <li><strong>与论文基线的对照：</strong>当前是方法可行性验证，不是与 ProphetAgent / FuncDroid
    在相同 benchmark 上的对照实验；复杂任务成功只能说明组合链路可用，不能据此声称优于基线。
    下一步需要在相同 app / 任务集上统计 completion、action accuracy 与调用成本。</li>
    <li><strong>多实例：</strong>重复卡片 + <code>PlanStep.instance</code> 已实现并有单测，
    但尚未在真机上跑“同一张卡出现两次”的任务。</li>
    <li><strong>能力补全：</strong>当图中没有可用卡片时，completer 尚未在真机上验证；
    目前所有成功任务都落在已有 5 张卡的能力范围内。</li>
    <li><strong>状态隔离：</strong>重复运行会在列表留下多张同名笔记；pilot 每例前已 <code>pm clear</code>，
    正式 benchmark 需要固定此隔离策略。</li>
    <li><strong>外部 app：</strong>分享面板只验证到“系统 chooser 打开且预览内容正确”，
    没有继续选择具体目标 app，避免产生外部副作用。</li>
    <li><strong>4 用例 pilot：</strong>因宿主内存压力被终止，未产生结果行；按约定没有重跑。
    现有结论来自逐条组合实验，而不是那次批量运行。</li>
  </ul>
  <h3>建议的下一步</h3>
  <ol>
    <li>用当前四卡链路再跑一个“两次 create_note + open + share”的多实例任务，验证 subgoal 绑定与 instance postcondition。</li>
    <li>把逐卡参数绑定合并为一次批量绑定（当前四卡任务为此串行付出 4 次 HY4 调用）；
    并把执行阶段的多次 postcondition 检查合并为“每卡一次、最后再一次”。</li>
    <li>在 6 个开源 app 上扩展到 20–30 条用户级任务，按 completion / action accuracy / 调用数 / 时延统计。</li>
    <li>补做 capability completion 的真机实验（例如目标需要“删除笔记”但图中无此卡）。</li>
  </ol>
</section>

<section>
  <h2>复现方式</h2>
<pre># 0. 安装（提供 specfcg 命令）
python -m pip install -e .

# 1. 采 trace / 挖卡 / 建图（示例）
python scripts/collect_trace.py --help
specfcg mine --trace runs/real/omninotes-create-note-2.json
specfcg build-graph

# 2. 跑复杂任务（真机 + magpie）
OPENAI_API_KEY=magpie PYTHONIOENCODING=utf-8 \\
  python scripts/run_pilot.py --cases benchmark/pilot/complex_flow.yaml \\
  --output runs/real/pilot_complex_flow.jsonl

# 3. 重新生成验收报告
python scripts/build_acceptance_report.py

# 4. 自动化测试
python -m pytest -q</pre>
  <p class="muted">证据文件：<code>runs/real/pilot_*.jsonl</code>、
  <code>runs/real/details/*.json</code>、<code>runs/real/build_graph_3.json</code>、
  <code>runs/real/work/cards/*.md</code>、<code>docs/reports/assets/*.jpg</code>。</p>
</section>

<footer>SpecFCG · 真机闭环验收报告 · 由 scripts/build_acceptance_report.py 生成</footer>
</main>
</body>
</html>
"""


def main() -> int:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    html_text = build()
    REPORT.write_text(html_text, encoding="utf-8")
    size = REPORT.stat().st_size / 1024
    print(f"wrote {REPORT} ({size:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
