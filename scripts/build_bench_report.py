#!/usr/bin/env python3
"""Build the benchmark report page from the saved experiment records.

Reads only what the experiments wrote under ``runs/mobileworld`` and
``docs/evidence``; regenerating the page never reruns anything on the device.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.report import summarize  # noqa: E402
from specfcg.benchmark.scorecard import (
    control,  # noqa: E402
    DIMENSIONS,
    app_score,
    collect_entries,
    load_history,
)


def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _num(value: float) -> str:
    """One decimal only when the value has one; 100.0 reads as 100."""
    return f"{value:.1f}".removesuffix(".0")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
        + "</tr>"
        for row in rows
    )
    return (
        f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    )


def _selfopt_section(selfopt: dict | None) -> str:
    """The self-optimization run: rounds, per-round outcome, coverage curve."""
    if not selfopt:
        return ""
    # The runner writes {app, summary, rounds}; the flat shape is what the
    # page was first written against.  Accept both so a real run is not
    # rendered as zeros.
    if isinstance(selfopt.get("summary"), dict):
        selfopt = {
            **selfopt["summary"],
            "records": selfopt.get("rounds") or [],
        }
    curve = selfopt.get("curve") or []
    parts = [
        "<h3>自优化（覆盖曲线）</h3>",
        f"<p>{selfopt.get('rounds', 0)} 轮，成功补图 "
        f"{selfopt.get('completed', 0)}/{selfopt.get('rounds', 0)}；"
        f"卡片 {selfopt.get('cards_start', 0)} → "
        f"{selfopt.get('cards_end', 0)}，覆盖 "
        f"{selfopt.get('covered_start', 0)} → "
        f"{selfopt.get('covered_end', 0)}/"
        f"{selfopt.get('total', 0)}。"
        + (
            "曲线：" + " → ".join(str(value) for value in curve) + "。"
            if curve
            else ""
        )
        + "</p>",
    ]
    rows = [
        [
            str(record.get("index", "")),
            record.get("function", ""),
            record.get("goal", ""),
            "、".join(record.get("added_cards") or []) or "—",
            "是" if record.get("completed") else "否",
            record.get("reason") or "—",
        ]
        for record in selfopt.get("records") or []
    ]
    if rows:
        parts.append(
            _table(
                ["轮次", "目标功能", "提出的任务", "新增卡片", "补图成功", "备注"],
                rows,
            )
        )
    return "".join(parts)


def _first(*paths: Path) -> dict | list | None:
    """The first existing record among the candidate paths."""
    for path in paths:
        record = _load(path)
        if record is not None:
            return record
    return None


def _selfopt_flat(record: dict | None) -> dict:
    """The runner's {summary, rounds} shape, flattened for the overview."""
    if not record:
        return {}
    if isinstance(record.get("summary"), dict):
        return {**record["summary"], "records": record.get("rounds") or []}
    return record


def estimate(entry: dict) -> dict[str, float]:
    """Per-app scores from the shared scorecard (kept as the page's API)."""
    return app_score(entry)


def _estimate_section(
    estimates: list[tuple[str, dict[str, float]]],
    control: dict[str, float] | None = None,
) -> str:
    if not estimates:
        return ""
    labels = [(key, label) for key, label, _source in DIMENSIONS]
    rows = [
        [app] + [f"{scores[key]:.0f}" for key, _label in labels]
        + [
            f"{sum(scores[key] for key, _label in labels) / len(labels):.0f}"
        ]
        for app, scores in estimates
    ]
    mean = [
        f"{sum(scores[key] for _app, scores in estimates) / len(estimates):.0f}"
        for key, _label in labels
    ]
    overall = sum(float(value) for value in mean) / len(mean)
    rows.append(["平均"] + mean + [f"{overall:.0f}"])
    return (
        "<h2>估计打分</h2>"
        "<p>每个能力维度 0–100，全部由 <code>runs/mobileworld</code> 下的记录算出："
        "图完整度取源码功能清单覆盖率；探针标定取 100 − |预测 − 实际|；"
        "自优化增益取曲线新增功能占清单比例；"
        "任务成功率取图臂在 20 步上限内的通过率；原始 goal 臂是配对对照，"
        "单独列出、不计入分数。"
        "随机遍历可达与原始 goal 臂都是对照组，只作参照，不计入分数："
        "随机遍历对每个被测量的系统都是同一个值，给它权重只会移动分数；"
        "原始 goal 臂的成功率是 agent 的能力，只有两臂的配对差异才说明图的分量。</p>"
        + (
            f"<p>对照组：随机遍历 {control.get('random', 0):.1f}，"
            f"原始 goal 臂 {control.get('raw', 0):.1f}。</p>"
            if control
            else ""
        )
        + "<p>探针标定用的是偏差（bias）口径，它只比较预测均值与实际命中率："
        "一个恰好猜中总体命中率的常数同样拿满分，所以这一维衡量的是"
        "估计有没有系统性偏高或偏低，而不是每个探针估得准不准。"
        "记录里同时给出 Brier 分数与「不同预测值的个数」：前者是逐探针的"
        "正规评分，后者为 1 就说明估计器是常数、无法区分任何两个探针。</p>"
        "<p><b>这个维度看得见什么、看不见什么：</b>预测说的是"
        "「图给出的路线能否走通」，观测说的是「agent 实际走的那一趟有没有"
        "走到」。一个无视正确路线乱走的 agent，和一个走错路线却误打误撞"
        "找到功能的 agent，都会表现为预测误差。单个数字分不开这两者，"
        "所以这里的数字不能用来说明图对了还是错了。</p>"
        + _table(
            ["App"] + [label for _key, label in labels] + ["综合"],
            rows,
        )
        + f"<p>综合估计：<strong>{overall:.0f} / 100</strong>"
        "（四个能力维度等权）。这一分数是实验记录的函数，重跑实验后重生成页面即更新。"
        "</p>"
    )


# Categorical slots 1-4 from the validated reference palette, in fixed
# order; the composite is ink, not a category, so it never takes a hue.
# Roles, not hex: the page's dark mode supplies its own validated steps.
_SERIES_COLORS = [
    "var(--series-1)",
    "var(--series-2)",
    "var(--series-3)",
    "var(--series-4)",
]
_OVERALL_COLOR = "var(--ink)"
_CURVE = {"w": 900, "h": 330, "left": 48, "right": 176, "top": 26, "bottom": 44}


def _y(value: float, top: float, plot_h: float) -> float:
    return round(top + (1 - max(0.0, min(100.0, value)) / 100) * plot_h, 1)


def _line_points(xs: list[float], values: list[float], top: float, plot_h: float) -> str:
    return " ".join(
        f"{x:.1f},{_y(v, top, plot_h)}" for x, v in zip(xs, values)
    )


def _spread_labels(
    entries: list[tuple[float, str, str, str]], top: float, bottom: float
) -> list[tuple[float, float, str, str, str]]:
    """Direct labels beside the last point, pushed apart, leaders included.

    ``entries`` is (point_y, text, color, key).  Returns (point_y, label_y,
    text, color, key) in the order given; the label keeps its series color as
    a swatch, the text stays ink.
    """
    gap = 19.0
    ordered = sorted(entries, key=lambda entry: entry[0])
    ys = [min(bottom, max(top, entry[0])) for entry in ordered]
    for index in range(1, len(ys)):
        ys[index] = max(ys[index], ys[index - 1] + gap)
    overflow = ys[-1] - bottom
    if overflow > 0:
        ys = [value - overflow for value in ys]
        for index in range(len(ys) - 2, -1, -1):
            ys[index] = min(ys[index], ys[index + 1] - gap)
    by_key = {}
    for entry, label_y in zip(ordered, ys):
        by_key[entry[3]] = label_y
    return [
        (point_y, by_key[key], text, color, key)
        for point_y, text, color, key in entries
    ]


def _curve_svg(points: list[dict]) -> str:
    dims = [(key, label) for key, label, _source in DIMENSIONS]
    n = len(points)
    width, height = _CURVE["w"], _CURVE["h"]
    left, right, top, bottom = (
        _CURVE["left"],
        _CURVE["right"],
        _CURVE["top"],
        _CURVE["bottom"],
    )
    plot_w = width - left - right
    plot_h = height - top - bottom
    if n == 1:
        xs = [left + plot_w / 2]
    else:
        xs = [left + index * plot_w / (n - 1) for index in range(n)]

    def values(key: str) -> list[float]:
        if key == "overall":
            return [float(point.get("overall") or 0.0) for point in points]
        return [
            float((point.get("dims") or {}).get(key) or 0.0)
            for point in points
        ]

    grid = []
    for tick in (0, 25, 50, 75, 100):
        y = _y(tick, top, plot_h)
        grid.append(
            f'<line x1="{left}" y1="{y}" x2="{left + plot_w}" y2="{y}" '
            'class="grid"/>'
            f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" '
            f'class="axis">{tick}</text>'
        )
    tick_labels = "".join(
        f'<text x="{x:.1f}" y="{height - bottom + 22}" text-anchor="middle" '
        f'class="axis">#{point.get("iteration", index)}</text>'
        for index, (x, point) in enumerate(zip(xs, points))
    )

    lines = []
    last_entries: list[tuple[float, str, str, str]] = []
    for index, (key, label) in enumerate(dims):
        series = values(key)
        color = _SERIES_COLORS[index % len(_SERIES_COLORS)]
        label_text = f"{label} {_num(series[-1])}"
        lines.append(
            f'<polyline points="{_line_points(xs, series, top, plot_h)}" '
            f'fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round">'
            f"<title>{html.escape(label)}</title></polyline>"
        )
        last_entries.append(
            (_y(series[-1], top, plot_h), label_text, color, key)
        )
        for index_point, (x, value) in enumerate(zip(xs, series)):
            tooltip = f'{points[index_point].get("label", "")} · {label} {value:.1f}'
            lines.append(
                _marker(x, _y(value, top, plot_h), color, tooltip)
            )
    overall = values("overall")
    lines.append(
        f'<polyline points="{_line_points(xs, overall, top, plot_h)}" '
        f'fill="none" stroke="{_OVERALL_COLOR}" stroke-width="3" '
        f'stroke-linejoin="round" stroke-linecap="round">'
        "<title>综合</title></polyline>"
    )
    last_entries.append(
        (
            _y(overall[-1], top, plot_h),
            f"综合 {_num(overall[-1])}",
            _OVERALL_COLOR,
            "overall",
        )
    )
    for index_point, (x, value) in enumerate(zip(xs, overall)):
        tooltip = f'{points[index_point].get("label", "")} · 综合 {value:.1f}'
        lines.append(_marker(x, _y(value, top, plot_h), _OVERALL_COLOR, tooltip))

    labels = []
    for point_y, label_y, text, color, key in _spread_labels(
        last_entries, top, top + plot_h
    ):
        swatch = (
            f'<rect x="{left + plot_w + 10}" y="{label_y - 4}" width="8" '
            f'height="8" rx="2" fill="{color}"/>'
        )
        if abs(label_y - point_y) > 1:
            labels.append(
                f'<line x1="{xs[-1] + 6}" y1="{point_y}" '
                f'x2="{left + plot_w + 10}" y2="{label_y}" class="leader"/>'
            )
        weight = ' font-weight="700"' if key == "overall" else ""
        labels.append(
            swatch
            + f'<text x="{left + plot_w + 22}" y="{label_y + 4}" '
            f'class="direct"{weight}>{html.escape(text)}</text>'
        )

    return (
        f'<svg id="score-curve" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="各维度随迭代的得分曲线" '
        f'xmlns="http://www.w3.org/2000/svg">'
        + "".join(grid)
        + tick_labels
        + "".join(lines)
        + "".join(labels)
        + "</svg>"
    )


def _marker(x: float, y: float, color: str, tooltip: str) -> str:
    return (
        f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="{color}" '
        f'stroke="var(--card)" stroke-width="2">'
        f"<title>{html.escape(tooltip)}</title></circle>"
    )


def _curve_section(points: list[dict]) -> str:
    """The metric curve: every recorded iteration, as one line per dimension."""
    if not points:
        return ""
    legend = "".join(
        f'<span class="legend-item"><i style="background:'
        f'{_SERIES_COLORS[index % len(_SERIES_COLORS)]}"></i>'
        f"{html.escape(label)}</span>"
        for index, (_key, label, _source) in enumerate(DIMENSIONS)
    )
    legend += (
        '<span class="legend-item"><i style="background:'
        f'{_OVERALL_COLOR}"></i>综合</span>'
    )
    labels = [(key, label) for key, label, _source in DIMENSIONS]
    rows = [
        [
            f"#{point.get('iteration', index)}",
            point.get("label", ""),
            *[_num(float((point.get('dims') or {}).get(key, 0))) for key, _label in labels],
            _num(float(point.get("overall", 0))),
            (
                _num(float((point.get("control") or {}).get("random", 0)))
                if (point.get("control") or {}).get("random")
                else "—"
            ),
        ]
        for index, point in enumerate(points)
    ]
    first = float(points[0].get("overall") or 0.0)
    last = float(points[-1].get("overall") or 0.0)
    delta = last - first
    note = (
        f"综合从 {first:.1f} 到 {last:.1f}（{delta:+.1f}）。"
        "<b>这条曲线止于旧架构</b>：Task F 之后任务维度的含义从""“编译脚本回放成功”变成“agent 按图描述达成目标”，""与旧分数不连续，不能连成一条线。"
        if len(points) > 1
        else "目前只有一个记录点；曲线从下一次迭代开始延伸。"
    )
    return (
        "<h2>指标曲线</h2>"
        "<p>每个点是 <code>scripts/record_score.py</code> 依据当次实验记录算出并写入 "
        "<code>runs/mobileworld/score-history.json</code> 的一次迭代；"
        "四个能力维度等权，随机遍历可达作为对照单独列出、不计入分数。"
        + note
        + "</p>"
        f'<div class="legend">{legend}</div>'
        + _curve_svg(points)
        + _table(
            ["迭代", "改动", *[label for _key, label in labels], "综合", "随机遍历（对照）"],
            rows,
        )
        + "<p class=\"hint\">图例以外，每条线在末端直接标注当前值；"
        "悬停任意圆点可看到该迭代的准确数值。色板与对比度已通过校验，"
        "数值同时以表格给出。</p>"
    )


def collect(runs: Path) -> dict:
    """The page's shape: {"apps": [...]}, from the shared scorecard reader."""
    runs = Path(runs)
    apps = collect_entries(runs)
    # The graph's size and duplicate groups are read from the graph on disk,
    # not from a record written by an older build: a rebuild changes both.
    sizes = {entry["app"]: _graph_size(runs, entry["app"]) for entry in apps}
    duplicates = {
        entry["app"]: _load_groups(_graph_file(runs, entry["app"], "same_function.json"))
        for entry in apps
    }
    for entry in apps:
        entry.update(sizes.get(entry["app"]) or {})
    return {
        "apps": apps,
        "cost": _load(runs / "graph-cost.json") or {},
        "duplicates": duplicates,
    }


def _graph_file(runs: Path, app: str, name: str) -> Path:
    """A file under the app's graph, in either layout."""
    base = Path(runs) / app / "graph"
    for candidate in (base / "graph" / name, base / name):
        if candidate.exists():
            return candidate
    return base / "graph" / name


def _graph_size(runs: Path, app: str) -> dict[str, int]:
    from specfcg.cards.store import CardStore
    from specfcg.graph.store import GraphStore

    base = Path(runs) / app / "graph"
    if not (base / "cards").exists():
        return {"cards": 0, "edges": 0}
    cards = CardStore(base).all()
    graph = GraphStore(base, CardStore(base)).load()
    return {"cards": len(cards), "edges": len(graph.edges)}


def _load_groups(path: Path) -> list[list[str]]:
    data = _load(path) or {}
    return [
        [str(name) for name in group]
        for group in (data.get("groups") or [])
        if isinstance(group, list) and len(group) >= 2
    ]


def _cost_cell(record: dict | None) -> str:
    if not record:
        return "—"
    calls = record.get("calls", 0)
    minutes = record.get("seconds", 0.0) / 60
    return f"{calls} 次 / {minutes:.1f} 分"


def _ablation_section(benches: list[dict]) -> str:
    """Paired table: the graph's description against the raw goal.

    The two arms share one agent, one device and one runner; the only
    difference is the string the agent receives.  Reporting them separately
    keeps the level (how good the agent is) apart from the delta (what the
    graph adds), which is the only quantity that speaks for the graph.
    """
    arms = {
        str(bench.get("agent")): bench
        for bench in benches
        if bench and bench.get("rows")
    }
    graph = arms.get("graph") or arms.get("specfcg")
    raw = arms.get("raw")
    if not graph or not raw:
        if graph or raw:
            return (
                "<h3>两臂对照</h3>"
                "<p>只记录了一臂（"
                + html.escape("、".join(sorted(arms)))
                + "）。图的分量来自同一批任务的配对差异，单臂只能说明 agent 的绝对水平。</p>"
            )
        return ""

    def by_task(bench: dict) -> dict[str, dict]:
        return {str(row.get("task_id")): row for row in bench.get("rows") or []}

    graph_rows = by_task(graph)
    raw_rows = by_task(raw)
    task_ids = sorted(set(graph_rows) | set(raw_rows))
    both_pass = graph_only = raw_only = both_fail = 0
    rows_html = []
    for task_id in task_ids:
        g = graph_rows.get(task_id) or {}
        r = raw_rows.get(task_id) or {}
        g_ok = bool(g.get("success"))
        r_ok = bool(r.get("success"))
        if g_ok and r_ok:
            both_pass += 1
        elif g_ok:
            graph_only += 1
        elif r_ok:
            raw_only += 1
        else:
            both_fail += 1
        rows_html.append(
            "<tr>"
            f"<td><code>{html.escape(task_id)}</code></td>"
            f"<td>{'通过' if g_ok else '失败'}</td>"
            f"<td>{'通过' if r_ok else '失败'}</td>"
            f"<td><code>{html.escape(str(g.get('task_text') or '—')[:160])}</code></td>"
            f"<td><code>{html.escape(str(r.get('task_text') or '—')[:160])}</code></td>"
            "</tr>"
        )
    delta = graph_only - raw_only
    return (
        "<h3>两臂对照：图生成的任务描述 vs 原始 goal</h3>"
        "<p>同一个 agent、同一台设备、同一批任务，唯一不同的是交给它的字符串。"
        "<b>水平</b>是 agent 的能力，<b>差异</b>才是图的分量："
        f"两臂都通过 {both_pass}，只有图臂通过 {graph_only}，"
        f"只有原始臂通过 {raw_only}，两臂都失败 {both_fail}；"
        f"配对差异 {delta:+d}。</p>"
        "<p class=\"mini\">Task F 之后 <code>task</code> 维度的含义从“编译脚本回放成功”"
        "变成“agent 按图描述达成目标”，与旧分数不连续，曲线在这里断开。</p>"
        "<table><thead><tr><th>任务</th><th>图臂</th><th>原始臂</th>"
        "<th>交给图臂的字符串</th><th>交给原始臂的字符串</th></tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def _duplicate_listing(duplicates: dict) -> str:
    """The groups themselves, with the caveat attached to them."""
    rows = []
    for app in sorted(duplicates):
        for group in duplicates[app]:
            rows.append(
                "<tr>"
                f"<td>{html.escape(app)}</td>"
                f"<td>{html.escape('、'.join(group))}</td>"
                "</tr>"
            )
    if not rows:
        return (
            "<p>这次构建没有报告重复功能组。</p>"
        )
    return (
        "<h3>重复功能组明细</h3>"
        "<p class=\"mini\">模型判断，不是分数；只报告，不自动合并。</p>"
        "<table><thead><tr><th>App</th><th>卡片组</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _graph_section(
    apps: list[tuple[str, dict | None]],
    cost: dict | None = None,
    duplicates: dict | None = None,
) -> str:
    """Per-app link to the animated construction journal."""
    cost = cost or {}
    duplicates = duplicates or {}
    rows = [
        [
            app,
            f"{entry.get('cards', 0)} 张卡片 / {entry.get('edges', 0)} 条边",
            f"{entry.get('covered', 0)}/{entry.get('functions', 0)}",
            str(len(duplicates.get(app) or [])),
            _cost_cell(cost.get(app)),
            f'<a href="../graph/{html.escape(app)}.html">构建过程 →</a>',
        ]
        for app, entry in apps
        if entry
    ]
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{cell if cell.startswith('<a ') else html.escape(str(cell))}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return (
        "<h2>构建的图</h2>"
        "<p>每张图从轨迹开始逐帧构建：先回放探索轨迹挖出卡片，再让 LLM 在卡片之间"
        "推断语义边。下面的页面按 journal 的回放顺序显示每一帧，"
        "可以直接看到卡片与边是如何长出来的。</p>"
        "<p>「重复功能组」是模型在推断语义边的同一次调用里给出的判断："
        "它读每张卡片的意图、输入、前后置条件与产出，指出哪些卡片描述的是同一个"
        "用户级功能。<b>这是判断，不是测量</b>——卡片不再带动作，就没有确定性的"
        "「同一功能」判据。旧的「行为面」分数比较的是编译出来的动作集，"
        "衡量的是另一个卡片格式，与这里不可比。</p>"
        f'<table><thead><tr><th>App</th><th>图规模</th><th>覆盖</th>'
        f"<th>重复功能组</th><th>语义边推断</th>"
        f"<th>链接</th></tr></thead><tbody>{body}</tbody></table>"
        + _duplicate_listing(duplicates)
        + "<p>「语义边推断」读的是构图 journal：每挖完一条轨迹就重推一次全图，"
        "会留下一条 <code>semantic edges</code> 帧，两帧之间的时间就是那次模型调用。"
        "表里是已记录图的实测开销。当前构建流程在挖完所有轨迹后只推一次；"
        "2026-11-14 用同一份轨迹冷缓存重建 activitydiary 实测 "
        "<strong>1 次调用 / 2.8 分钟</strong>，记录图为 17 次 / 38.3 分钟。"
        "同一份轨迹也只挖一次：记录图里 omninotes 的 "
        "<code>merge_notes</code> 与 <code>merge_two_notes</code> 就是"
        + "<code>omni-merge</code> 被挖了两遍的结果，重建后只会留下一张。</p>"
    )


def _shots(entry: dict, evidence_root: Path) -> dict[str, str]:
    """Copy each task's final screenshot into the published evidence area.

    Returns {task_id: web path}.  The run record stays where the experiment
    wrote it; the report owns what is published beside it.
    """
    paths: dict[str, Path] = {}
    for raw in entry.get("shots") or []:
        path = Path(raw)
        if path.exists():
            paths[path.stem] = path
    published: dict[str, str] = {}
    for task_id, path in sorted(paths.items()):
        dest_dir = evidence_root / entry["app"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
            shutil.copy2(path, dest)
        published[task_id] = (
            f"../evidence/{entry['app']}/{path.name}"
        )
    return published


def render(
    data: dict, evidence_root: Path | None = None
) -> str:
    sections: list[str] = []
    sections.append(_curve_section(data.get("history") or []))
    overview: list[list[str]] = []
    for entry in data["apps"]:
        coverage = entry.get("coverage") or {}
        random_row = entry.get("random") or {}
        probes = entry.get("probes") or {}
        selfopt = _selfopt_flat(entry.get("selfopt"))
        calib = probes.get("calibration") or {}
        overview.append(
            [
                entry["app"],
                f"{coverage.get('covered', 0)}/{coverage.get('functions', 0)}",
                _pct(coverage.get("score", 0.0)),
                _pct(coverage.get("hint_dependence", 0.0)),
                _pct(random_row.get("score_union", 0.0)),
                f"{calib.get('predicted', 0):.2f}",
                f"{calib.get('actual', 0):.2f}",
                str(calib.get("probes", 0)),
                (
                    f"{selfopt.get('covered_start', 0)}→"
                    f"{selfopt.get('covered_end', 0)}"
                    if selfopt
                    else "—"
                ),
            ]
        )
    mean_score = (
        sum(
            float((entry.get("coverage") or {}).get("score") or 0.0)
            for entry in data["apps"]
        )
        / len(data["apps"])
        if data["apps"]
        else 0.0
    )
    sections.append(
        "<h2>总览</h2>"
        "<p>图覆盖率由当前代码重算，不读实验时存的快照：图与清单都在磁盘上，"
        "而快照是当时那个匹配规则算出来的。旧规则会把清单的 <code>cards:</code> "
        "提示当作匹配依据，而那些提示正是照着某一次建图写下的卡片名——"
        "拿它去评另一张图，测的是两次建图有没有起同一个名字。去掉提示后，"
        f"四个 app 的平均覆盖率是 {_num(mean_score * 100)}%，"
        "而记录时是 100%。「提示依赖」列是提示还会额外"
        "补上多少功能，用来把这次下降量化清楚。</p>"
        + _table(
            [
                "App",
                "图覆盖函数",
                "图覆盖率",
                "提示依赖",
                "随机遍历观察到",
                "预测可达率",
                "实际命中率",
                "探针数",
                "自优化覆盖",
            ],
            overview,
        )
    )

    sections.append(
        _estimate_section(
            [(entry["app"], estimate(entry)) for entry in data["apps"]],
            control(data["apps"]),
        )
    )
    sections.append(
        _graph_section(
            [
                (
                    entry["app"],
                    {
                        **(entry.get("coverage") or {}),
                        "cards": entry.get("cards", 0),
                        "edges": entry.get("edges", 0),
                    },
                )
                for entry in data["apps"]
            ],
            data.get("cost") or {},
            data.get("duplicates") or {},
        )
    )

    evidence_root = evidence_root or ROOT / "docs" / "evidence" / "mobileworld"
    for entry in data["apps"]:
        coverage = entry.get("coverage") or {}
        random_row = entry.get("random") or {}
        probes = entry.get("probes") or {}
        shots = _shots(entry, evidence_root)
        parts = [f"<h2>{html.escape(entry['app'])}</h2>"]
        parts.append(
            f"<p>图规模：{coverage.get('cards', 0)} 张卡片 / "
            f"{coverage.get('edges', 0)} 条边；源码功能清单 "
            f"{coverage.get('functions', 0)} 项，图覆盖 "
            f"{coverage.get('covered', 0)} 项。</p>"
        )
        if coverage.get("missing"):
            parts.append(
                "<p>未覆盖：" + html.escape(", ".join(coverage["missing"]))
                + "</p>"
            )
        if random_row:
            parts.append(
                f"<h3>随机遍历</h3><p>{random_row.get('episodes', 0)} 个 "
                f"episode × {random_row.get('steps_per_episode', 0)} 步，"
                f"并集观察到 {random_row.get('covered_union', 0)}/"
                f"{random_row.get('total', 0)} 项功能"
                f"（{_pct(random_row.get('score_union', 0.0))}）。</p>"
            )
            rows = [
                [
                    str(row["episode"]),
                    str(row["steps"]),
                    f"{row['covered']}/{random_row.get('total', 0)}",
                    _pct(row["score"]),
                ]
                for row in random_row.get("per_episode") or []
            ]
            if rows:
                parts.append(_table(["Episode", "步数", "覆盖", "比例"], rows))
        if probes:
            parts.append("<h3>任务指引补图探针</h3>")
            rows = [
                [
                    row["function"],
                    row["goal"],
                    " → ".join(row["predicted_path"]) or "—",
                    f"{row['predicted_confidence']:.2f}",
                    "是" if row["reached"] else "否",
                    row.get("evidence") or "—",
                ]
                for row in probes.get("probes") or []
            ]
            if rows:
                parts.append(
                    _table(
                        [
                            "未覆盖功能",
                            "提出的任务",
                            "预测路线",
                            "预测可达率",
                            "实际命中",
                            "证据",
                        ],
                        rows,
                    )
                )
            calib = probes.get("calibration") or {}
            distinct = calib.get("distinct_predictions")
            spread = (
                f"，Brier {calib.get('brier', 0):.3f}，"
                f"不同预测值 {distinct} 个"
                + (
                    "（<b>常数估计</b>：无法区分任何两个探针）"
                    if distinct == 1
                    else ""
                )
                if distinct is not None
                else ""
            )
            parts.append(
                f"<p>校准：预测均值 {calib.get('predicted', 0):.2f}，"
                f"实际命中 {calib.get('actual', 0):.2f}，"
                f"差 {calib.get('gap', 0):+.2f}{spread}。</p>"
            )
        parts.append(_selfopt_section(entry.get("selfopt")))
        parts.append(_ablation_section(entry.get("bench") or []))
        for bench in entry.get("bench") or []:
            if not bench:
                continue
            summary = summarize(bench.get("rows") or [])
            parts.append(
                f"<h3>任务评测（{html.escape(str(bench.get('agent')))}）</h3>"
                f"<p>{summary['success']}/{summary['tasks']} 成功"
                f"（{_pct(summary['success_rate'])}），"
                f"平均 {summary['mean_steps']} 步；失败类型："
                + html.escape(
                    "，".join(
                        f"{name} ×{count}"
                        for name, count in sorted(
                            summary["failure_types"].items(),
                            key=lambda item: (-item[1], item[0]),
                        )
                    )
                    or "无"
                )
                + "</p>"
            )
            head = "".join(
                f"<th>{label}</th>"
                for label in ["任务", "结果", "失败类型", "步数", "原因", "最终画面"]
            )
            body = []
            for row in bench.get("rows") or []:
                shot = shots.get(row["task_id"])
                image = (
                    f'<a href="{shot}"><img src="{shot}" width="160" '
                    f'alt="{html.escape(str(row["task_id"]))} 最终画面"></a>'
                    if shot
                    else "—"
                )
                body.append(
                    "<tr>"
                    + "".join(
                        f"<td>{html.escape(str(cell))}</td>"
                        for cell in [
                            row["task_id"],
                            "通过" if row["success"] else "失败",
                            row.get("failure_type") or "—",
                            f"{row['steps']}/{row['max_steps']}",
                            (row.get("reason") or "")[:120],
                        ]
                    )
                    + f"<td>{image}</td></tr>"
                )
            parts.append(
                f"<table><thead><tr>{head}</tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table>"
            )
            for row in bench.get("rows") or []:
                actions = row.get("actions") or []
                if not actions:
                    continue
                predicted = " → ".join(row.get("predicted_path") or []) or "—"
                step_rows = [
                    [
                        str(index),
                        action.get("card", ""),
                        action.get("action", ""),
                        action.get("target", ""),
                        action.get("args", ""),
                        "成功" if action.get("ok") else "失败",
                    ]
                    for index, action in enumerate(actions, 1)
                ]
                parts.append(
                    f"<details><summary>{html.escape(str(row['task_id']))}"
                    f" · 每步动作（预测路径 {html.escape(predicted)}）</summary>"
                    + _table(
                        ["#", "卡片", "动作", "目标", "参数", "结果"],
                        step_rows,
                    )
                    + "</details>"
                )
        sections.append("".join(parts))
    return "".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-bench-report")
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument(
        "--history", default="runs/mobileworld/score-history.json"
    )
    parser.add_argument("--out", default="docs/reports/mobileworld.html")
    parser.add_argument("--title", default="SpecFCG 移动端基准实验")
    args = parser.parse_args(argv)

    runs = ROOT / args.runs
    if not runs.exists():
        print(f"no runs at {runs}", file=sys.stderr)
        return 2
    data = collect(runs)
    data["history"] = load_history(ROOT / args.history)
    body = render(data)
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(args.title)}</title>
<style>
:root{{--ink:#101828;--muted:#475467;--line:#e4e7ec;--accent:#3b5bdb;--bg:#f8fafc;
--card:#ffffff;--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100}}
*{{box-sizing:border-box}}
body{{margin:0;font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans SC",sans-serif;color:var(--ink);background:var(--bg)}}
main{{max-width:1080px;margin:0 auto;padding:56px 24px 96px}}
h1{{font-size:30px;margin:0 0 8px}}
h2{{font-size:22px;margin:44px 0 12px;padding-top:16px;border-top:1px solid var(--line)}}
h3{{font-size:17px;margin:28px 0 8px}}
p{{color:var(--muted);margin:8px 0}}
table{{width:100%;border-collapse:collapse;margin:12px 0;background:var(--card);font-size:14px;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:var(--bg);font-weight:600}}
code{{background:var(--bg);padding:1px 5px;border-radius:4px}}
svg#score-curve{{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}}
#score-curve .grid{{stroke:var(--line);stroke-width:1}}
#score-curve .axis{{fill:var(--muted);font-size:12px}}
#score-curve .direct{{fill:var(--ink);font-size:12px}}
#score-curve .leader{{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 2}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0 4px;font-size:13px;color:var(--muted)}}
.legend-item i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.hint{{font-size:13px}}
@media (prefers-color-scheme: dark){{
:root{{--ink:#f0efec;--muted:#c3c2b7;--line:#33332f;--bg:#151514;--card:#1a1a19;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500}}
}}
</style></head>
<body><main>
<h1>{html.escape(args.title)}</h1>
<p>数据来自 <code>{html.escape(args.runs)}</code>：源码功能清单覆盖率、随机遍历覆盖率、
任务指引补图探针的预测/实际命中，以及 20 步上限下的任务成功与失败类型。</p>
{body}
</main></body></html>
"""
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
