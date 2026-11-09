#!/usr/bin/env python
"""Run the Stage 1 benchmark and write an evaluation report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from specfcg.benchmark.cases import (  # noqa: E402
    app_packages,
    load_apps,
    load_cases,
    load_goals,
)
from specfcg.benchmark.metrics import (  # noqa: E402
    action_accuracy,
    completion_rate,
    coverage,
    path_recall,
)
from specfcg.benchmark.runner import Runner  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.models import RunResult  # noqa: E402
from specfcg.pipeline import Pipeline  # noqa: E402


def _run_one(
    pipeline: Pipeline, text: str, app: str = ""
) -> RunResult:
    result = pipeline.execute_goal(text, app=app)
    if result is not None:
        return result
    return RunResult(
        success=False,
        goal_success=False,
        failure_type="goal_failure",
        error="no plan for this case",
    )


def _executed(
    pipeline: Pipeline, results: list[RunResult]
) -> tuple[set[str], set[tuple[str, str, str]]]:
    cards: set[str] = set()
    edges: set[tuple[str, str, str]] = set()
    for result in results:
        for item in result.step_results:
            if isinstance(item, dict):
                card = item.get("card")
                if card:
                    cards.add(str(card))
        if result.plan is None:
            continue
        path = result.plan.path
        for left, right in zip(path, path[1:]):
            for edge in pipeline.graph.edges:
                if (
                    edge.from_card == left
                    and edge.to_card == right
                ):
                    edges.add((left, right, edge.type))
    return cards, edges


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_stage1")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "llm.example.yaml"),
    )
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--output",
        default=str(ROOT / "runs" / "stage1_report.json"),
    )
    args = parser.parse_args(argv)

    started = time.time()
    apps = load_apps(ROOT / "benchmark" / "apps.yaml")
    cases = load_cases(ROOT / "benchmark" / "cases")
    goals = load_goals(ROOT / "benchmark" / "goals")
    if args.limit is not None:
        limit = max(0, args.limit)
        cases = cases[:limit]
        goals = goals[:limit]

    config = load_config(Path(args.config))
    pipeline = build_pipeline(config, args.fake, args.fake)
    packages = app_packages(apps)

    case_results = {
        case.id: _run_one(
            pipeline,
            case.text,
            packages.get(case.app, ""),
        )
        for case in cases
    }
    case_rows = Runner(case_results.__getitem__).run(cases)

    goal_results: list[RunResult] = []
    goal_rows: list[dict] = []
    for goal in goals:
        result = _run_one(
            pipeline,
            goal.text,
            packages.get(goal.app, ""),
        )
        goal_results.append(result)
        goal_rows.append(
            {
                "goal_id": goal.id,
                "success": result.success,
                "goal_success": result.goal_success,
                "failure_type": result.failure_type,
                "assertions": len(goal.assertions),
            }
        )

    all_results = [*case_results.values(), *goal_results]
    executed_cards, executed_edges = _executed(
        pipeline, all_results
    )
    report = {
        "apps": [
            {
                "name": app.name,
                "package": app.package,
                "apk_path": str(app.apk_path),
                "version": app.version,
            }
            for app in apps
        ],
        "cases": case_rows,
        "goals": goal_rows,
        "completion_rate": completion_rate(all_results),
        "action_accuracy": action_accuracy(all_results),
        "path_recall": path_recall(pipeline.graph, []),
        "coverage": coverage(
            pipeline.graph, executed_cards, executed_edges
        ),
        "cost": {
            "llm_calls": getattr(pipeline.llm, "calls", 0),
            "elapsed_s": round(time.time() - started, 3),
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"stage1: {len(case_rows)} cases, {len(goal_rows)} goals, "
        f"completion={report['completion_rate']:.2f}, "
        f"report={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
