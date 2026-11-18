#!/usr/bin/env python3
"""Run the AndroidWorld/MobileWorld-style suite on the real device.

Usage:
  python scripts/run_mobileworld_bench.py --app omninotes --agent specfcg
  python scripts/run_mobileworld_bench.py --app omninotes --agent random

The script only orchestrates: task initialisation, the 20-step cap, the
final-state oracle, and latest-only record keeping live in
``specfcg.benchmark``; planning/execution come from the existing SpecFCG
pipeline (no agent policy is reimplemented here).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.agents import (  # noqa: E402
    GraphAgent,
    RandomTraversalAgent,
    RawGoalAgent,
)
from specfcg.benchmark.coverage_eval import path_confidence  # noqa: E402
from specfcg.benchmark.device_ops import AdbOps  # noqa: E402
from specfcg.benchmark.suite import load_suite  # noqa: E402
from specfcg.benchmark.suite_runner import TaskRunner  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.executor.device import Uiautomator2Device  # noqa: E402
from specfcg.executor.mobile_agent_backend import MobileAgentBackend  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-mobileworld-bench")
    parser.add_argument("--suite", default="benchmark/mobileworld/suite.yaml")
    parser.add_argument("--app", required=True)
    parser.add_argument(
        "--agent", choices=["graph", "raw", "random"], default="graph"
    )
    parser.add_argument("--serial", default=os.getenv("ANDROID_SERIAL", ""))
    parser.add_argument("--config", default="config/llm.yaml")
    parser.add_argument(
        "--graph-root", default="", help="SpecFCG graph root for this app"
    )
    parser.add_argument("--out", default="runs/mobileworld")
    parser.add_argument("--only", default="")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tag", default="")
    args = parser.parse_args(argv)

    if not args.serial:
        print("missing --serial or ANDROID_SERIAL", file=sys.stderr)
        return 2

    suites = {suite.app: suite for suite in load_suite(ROOT / args.suite)}
    if args.app not in suites:
        print(
            f"unknown app {args.app}; known: {sorted(suites)}",
            file=sys.stderr,
        )
        return 2
    suite = suites[args.app]
    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    tasks = [
        task for task in suite.tasks if not wanted or task.id in wanted
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # One stable directory per app and agent: a rerun replaces the previous
    # record instead of piling up timestamped copies.
    run_dir = Path(args.out) / args.app / f"bench-{args.agent}"
    run_dir.mkdir(parents=True, exist_ok=True)

    ops = AdbOps(args.serial)
    device = Uiautomator2Device(args.serial, settle_s=1.0)
    device.set_app(suite.package)
    runner = TaskRunner(ops, settle_s=1.0, out_dir=run_dir)

    pipeline = None
    confidence = None
    raw_agent = None
    if args.agent == "raw":
        # The same agent as the graph arm, minus the graph.  It is built
        # straight from the config so the two arms share one model, one
        # device and one runner; only the string differs.
        config = load_config(ROOT / args.config)
        raw_agent = MobileAgentBackend(
            args.serial,
            config.agent.model,
            config.agent.fallback_model,
            Path(args.out) / args.app / "bench-raw" / "agent",
            base_url=config.llm.base_url,
            api_key=os.environ.get(config.llm.api_key_env, ""),
        )
    if args.agent == "graph":
        graph_root = Path(
            args.graph_root or (Path(args.out) / args.app / "graph")
        )
        if not (graph_root / "cards").exists():
            print(f"no graph at {graph_root}", file=sys.stderr)
            return 2
        config = load_config(ROOT / args.config)
        config.paths.root = str(graph_root)
        # The pipeline's agent must act on the device this run was given.
        # The config's serial is one machine's default; with four emulators
        # in parallel, a pipeline that ignored --serial observed and acted on
        # a different app's screen, and every card looked inexecutable.
        config.device.serial = args.serial
        pipeline = build_pipeline(config, fake_llm=False, fake_device=False)
        graph = pipeline.store.load()
        print(
            f"graph: {len(graph.cards)} cards, {len(graph.edges)} edges",
            flush=True,
        )
        confidence = lambda path: path_confidence(graph, path)  # noqa: E731

    rows = []
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.id}: {task.goal[:90]}", flush=True)
        if args.agent == "graph":
            agent = GraphAgent(pipeline, confidence=confidence)
        elif args.agent == "raw":
            agent = RawGoalAgent(raw_agent)
        else:
            agent = RandomTraversalAgent(
                device, rng=random.Random(args.seed + index)
            )
        outcome = runner.run(task, agent)
        # The screen the oracle judged, kept beside the record: an acceptance
        # claim about the final state should be checkable by looking at it.
        try:
            device.screenshot(run_dir / "shots" / f"{task.id}.png")
        except Exception as exc:  # evidence is best-effort, never fatal
            print(f"    screenshot failed: {exc}", flush=True)
        print(
            f"    success={outcome.success} steps={outcome.steps}/"
            f"{outcome.max_steps} failure={outcome.failure_type} "
            f"predicted={outcome.predicted_confidence:.2f} "
            f"reached={outcome.reached_cards} reason={outcome.reason[:110]}",
            flush=True,
        )
        rows.append(outcome.as_record())

    summary = {
        "app": suite.app,
        "agent": args.agent,
        "tag": args.tag,
        "seed": args.seed,
        "started": stamp,
        "tasks": len(rows),
        "success": sum(1 for row in rows if row["success"]),
        "failure_types": {},
        "steps": sum(row["steps"] for row in rows),
        "rows": rows,
    }
    for row in rows:
        key = row["failure_type"] or "success"
        summary["failure_types"][key] = (
            summary["failure_types"].get(key, 0) + 1
        )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
