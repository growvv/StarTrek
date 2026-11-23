#!/usr/bin/env python3
"""Graph-completeness experiments: source coverage, random traversal, task-guided completion.

Three measurements, all written under ``runs/mobileworld/<app>/experiments/``:

1. ``coverage``: graph completeness against the source-derived function
   inventory (how many user-level functions have a card).
2. ``random``: an N-episode random traversal on the real device; how many
   inventoried functions were observed at all (a graph-independent upper
   bound on what an unguided explorer finds).
3. ``probes``: for each inventoried function with no card, propose a task,
   predict a route and a reachability probability from the graph, execute it,
   and compare the predicted probability with whether the function was
   actually observed.

Records are latest-only per key so reruns replace stale data.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.agents import (  # noqa: E402
    RandomTraversalAgent,
)
from specfcg.benchmark.suite import BenchTask  # noqa: E402
from specfcg.benchmark.suite_runner import AgentRun  # noqa: E402
from specfcg.scoring.coverage_eval import (  # noqa: E402
    graph_coverage,
    load_inventory,
    observed_coverage,
)
from specfcg.benchmark.device_ops import AdbOps  # noqa: E402
from specfcg.benchmark.harness import fresh_app  # noqa: E402
from specfcg.benchmark.exploration import (  # noqa: E402
    build_probe,
    calibration,
    evidence_hit,
    uncovered,
)
from specfcg.benchmark.store import LatestStore  # noqa: E402
from specfcg.scoring.scorecard import measured  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.executor.device import Uiautomator2Device  # noqa: E402


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _app_meta(app: str) -> dict:
    suite = ROOT / "benchmark" / "mobileworld" / "suite.yaml"
    import yaml

    raw = yaml.safe_load(suite.read_text(encoding="utf-8"))
    for entry in raw.get("apps") or []:
        if entry.get("name") == app:
            return entry
    raise SystemExit(f"unknown app {app}")


def run_random(
    app: str,
    package: str,
    functions,
    serial: str,
    episodes: int,
    steps: int,
    seed: int,
    out_dir: Path,
    onboarding: list[dict] | None = None,
) -> dict:
    ops = AdbOps(serial)
    device = Uiautomator2Device(serial, settle_s=0.8)
    device.set_app(package)
    observed: list[str] = []
    episode_rows = []
    for index in range(episodes):
        fresh_app(ops, package, onboarding)
        time.sleep(1.5)
        agent = RandomTraversalAgent(
            device, rng=random.Random(seed + index)
        )
        # The runner-facing agent callable takes the task; a random walk is
        # the same call with a task whose goal it ignores.
        run = agent(BenchTask(
            id=f"random-{index}",
            app=app,
            package=package,
            template="explore the app",
            max_steps=steps,
        ))
        text = "\n".join(run.observed_ui)
        final = device.dump_ui()
        text = text + "\n" + final
        observed.append(text)
        report = observed_coverage(functions, text)
        episode_rows.append(
            {
                "episode": index,
                "steps": len(run.steps),
                "covered": report.covered,
                "score": round(report.score, 3),
                "missing": report.missing,
            }
        )
        print(
            f"  random episode {index + 1}/{episodes}: "
            f"{report.covered}/{report.total} functions "
            f"({report.score:.0%})",
            flush=True,
        )
    union = observed_coverage(functions, "\n".join(observed))
    result = {
        "app": app,
        "episodes": episodes,
        "steps_per_episode": steps,
        "seed": seed,
        "total": union.total,
        "covered_union": union.covered,
        "score_union": round(union.score, 3),
        "missing_union": union.missing,
        "hits": union.hits,
        "per_episode": episode_rows,
        "finished": _stamp(),
    }
    (out_dir / "random.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LatestStore(out_dir / "latest.json").update("random", result)
    return result


def run_probes(
    app: str,
    package: str,
    functions,
    graph,
    serial: str,
    out_dir: Path,
    limit: int,
    steps: int,
    onboarding: list[dict] | None = None,
    pipeline=None,
    ops=None,
) -> dict:
    covered = {
        function.id
        for function in functions
        if graph_coverage([function], graph).covered
    }
    missing = uncovered(functions, covered)[:limit]
    if pipeline is None:
        raise SystemExit("probes need a pipeline to compile the predicted path")
    device = pipeline.device
    device.set_app(package)
    # Injected by tests so the probe path can be checked without a device;
    # a real run builds the adb bridge here.
    ops = ops or AdbOps(serial)
    probes = []
    for function in missing:
        probe = build_probe(graph, function)
        print(
            f"  probe {function.id}: goal={probe.goal[:70]!r} "
            f"path={probe.predicted_path} "
            f"p={probe.predicted_confidence:.2f}",
            flush=True,
        )
        fresh_app(ops, package, onboarding)
        time.sleep(1.5)
        # The probe predicted a path; the walk that tests the prediction must
        # be that path.  A goal-blind random walk measures a different thing
        # entirely, so "reached" would not be evidence about the estimate.
        # The package travels with the plan: the executor hands the plan's
        # description to an agent, and an agent with no app has nothing to
        # act on.
        plan = pipeline.plan_path(
            probe.goal, probe.predicted_path, app=package
        )
        if plan is None:
            run = AgentRun(steps=[], no_plan=True)
            observed = pipeline.observe(package)
        else:
            # The probe predicted a path; the walk that tests the prediction
            # executes exactly that plan, through the same agent the
            # benchmark uses.
            result = pipeline.executor.execute(plan, max_steps=steps)
            run = AgentRun(
                steps=[
                    {
                        "action": item.get("action", ""),
                        "target": item.get("target", ""),
                        "args": item.get("args", ""),
                        "ok": bool(item.get("success")),
                    }
                    for item in result.step_results
                ],
                done=bool(result.success),
                predicted_path=list(plan.path),
                reached_cards=list(plan.path) if result.success else [],
                observed_ui=[item.get("before", "") for item in result.step_results],
                error=result.error,
            )
            observed = "\n".join(run.observed_ui)
        probe.reached = evidence_hit(function, observed)
        probe.observed_evidence = (
            next(
                (
                    evidence
                    for evidence in function.ui_evidence
                    if evidence.casefold() in observed.casefold()
                ),
                "",
            )
        )
        probes.append(
            {
                "function": function.id,
                "label": function.label,
                "goal": probe.goal,
                "target_card": probe.target_card,
                "predicted_path": probe.predicted_path,
                "predicted_confidence": round(
                    probe.predicted_confidence, 3
                ),
                "reached": probe.reached,
                "evidence": probe.observed_evidence,
                "steps": len(run.steps),
            }
        )
        print(
            f"    reached={probe.reached} "
            f"evidence={probe.observed_evidence!r}",
            flush=True,
        )
    from specfcg.benchmark.exploration import CompletionProbe

    rebuilt = [
        CompletionProbe(
            function_id=row["function"],
            label=row["label"],
            goal=row["goal"],
            target_card=row["target_card"],
            predicted_path=row["predicted_path"],
            predicted_confidence=row["predicted_confidence"],
            reached=row["reached"],
        )
        for row in probes
    ]
    result = {
        "app": app,
        "probes": probes,
        "calibration": calibration(rebuilt),
        "finished": _stamp(),
    }
    save_probes(out_dir, result)
    return result


def save_probes(out_dir: Path, payload: dict) -> None:
    """Save a probe run, unless it probed nothing.

    Pointed at a graph with every function covered the experiment has no
    probe to run, and its empty record would replace the seed run's real
    calibration -- an empty record reads as a perfect prediction of
    nothing.  The same rule the scorecard applies on read is applied here
    on write, so the two cannot disagree.
    """
    if not measured(payload, "probes"):
        print(
            "no uncovered function to probe; record left as it was",
            file=sys.stderr,
        )
        return
    (out_dir / "probes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LatestStore(out_dir / "latest.json").update("probes", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-graph-experiments")
    parser.add_argument("--app", required=True)
    parser.add_argument("--serial", default="")
    parser.add_argument("--config", default="config/llm.yaml")
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument("--random-episodes", type=int, default=3)
    parser.add_argument("--random-steps", type=int, default=20)
    parser.add_argument("--probe-steps", type=int, default=12)
    parser.add_argument("--probe-limit", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--graph-root",
        default="",
        help="graph to measure (default: runs/mobileworld/<app>/graph)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="experiment output dir (default: <graph parent>/experiments)",
    )
    parser.add_argument(
        "--skip",
        default="",
        help="comma list of stages to skip: random,probes",
    )
    args = parser.parse_args(argv)

    meta = _app_meta(args.app)
    inventory = ROOT / "benchmark" / "coverage" / f"{args.app}.yaml"
    if not inventory.exists():
        print(f"no inventory {inventory}", file=sys.stderr)
        return 2
    functions = load_inventory(inventory)
    graph_root = (
        ROOT / args.graph_root
        if args.graph_root
        else ROOT / args.runs / args.app / "graph"
    )
    if not (graph_root / "cards").exists():
        print(f"no graph at {graph_root}", file=sys.stderr)
        return 2
    config = load_config(ROOT / args.config)
    config.paths.root = str(graph_root)
    pipeline = build_pipeline(config, fake_llm=False, fake_device=False)
    graph = pipeline.store.load()
    out_dir = (
        ROOT / args.out if args.out else graph_root.parent / "experiments"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    skip = {part.strip() for part in args.skip.split(",") if part.strip()}

    coverage = graph_coverage(functions, graph)
    coverage_row = {
        "app": args.app,
        "functions": coverage.total,
        "covered": coverage.covered,
        "score": round(coverage.score, 3),
        "missing": coverage.missing,
        "unreachable": coverage.unreachable,
        "hits": coverage.hits,
        "cards": len(graph.cards),
        "edges": len(graph.edges),
        "finished": _stamp(),
    }
    (out_dir / "coverage.json").write_text(
        json.dumps(coverage_row, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LatestStore(out_dir / "latest.json").update("coverage", coverage_row)
    print(
        f"coverage: {coverage.covered}/{coverage.total} "
        f"({coverage.score:.0%}) missing={coverage.missing}",
        flush=True,
    )

    if "random" not in skip:
        if not args.serial:
            print("--serial required for random traversal", file=sys.stderr)
            return 2
        run_random(
            args.app,
            meta["package"],
            functions,
            args.serial,
            args.random_episodes,
            args.random_steps,
            args.seed,
            out_dir,
            meta.get("onboarding"),
        )

    if "probes" not in skip:
        if not args.serial:
            print("--serial required for probes", file=sys.stderr)
            return 2
        run_probes(
            args.app,
            meta["package"],
            functions,
            graph,
            args.serial,
            out_dir,
            args.probe_limit,
            args.probe_steps,
            meta.get("onboarding"),
            pipeline=pipeline,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
