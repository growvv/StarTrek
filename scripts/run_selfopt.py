#!/usr/bin/env python3
"""Self-optimization experiment: does the graph grow toward full coverage?

Each round picks the next source-inventoried function the graph does not
cover, turns it into a task, and lets the pipeline's existing capability
completion path (detect gap -> hypothesise -> device probe -> mine trace ->
graph patch) add the missing card.  Coverage is re-measured after every
round, so the saved record is the coverage curve, not just the final score.

Run:
  PYTHONPATH=. python scripts/run_selfopt.py --app activitydiary --rounds 6
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.coverage_eval import (  # noqa: E402
    graph_coverage,
    load_inventory,
)
from specfcg.benchmark.selfopt import (  # noqa: E402
    growth,
    make_round,
    next_attempt,
)
from specfcg.benchmark.store import LatestStore  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _package(app: str) -> str:
    suite = ROOT / "benchmark" / "mobileworld" / "suite.yaml"
    raw = yaml.safe_load(suite.read_text(encoding="utf-8"))
    for entry in raw.get("apps") or []:
        if entry.get("name") == app:
            return str(entry["package"])
    raise SystemExit(f"unknown app {app}")


def _onboarding(app: str) -> list[dict]:
    """The first-run steps the benchmark replays before every task."""
    suite = ROOT / "benchmark" / "mobileworld" / "suite.yaml"
    raw = yaml.safe_load(suite.read_text(encoding="utf-8"))
    for entry in raw.get("apps") or []:
        if entry.get("name") == app:
            return list(entry.get("onboarding") or [])
    return []


def resolve_graph_root(app: str, override: str) -> Path:
    """The graph the curve starts from: the app graph, or a seed graph."""
    return (
        ROOT / override
        if override
        else ROOT / "runs" / "mobileworld" / app / "graph"
    )


def launch_state(device, package: str, onboarding: list[dict]) -> str:
    """Restart the app, replay its onboarding, and return the start screen.

    A round is an independent measurement, so it has to start where the
    benchmark starts a task: from the app's launch state, past the first-run
    screens the benchmark clicks through.  A round that instead inherits the
    previous round's final screen measures the app's leftovers -- its first
    discovered "capability" is the one that undoes the last probe (relaunch
    the app, dismiss the dialog it opened) -- and the curve counts recovery
    steps instead of the target function.
    """
    device.start_app(package)
    for step in onboarding:
        action = str(step.get("action") or "")
        target = str(step.get("target") or "")
        if action:
            device.execute(action, target, str(step.get("args") or ""))
    return device.dump_ui()


def working_graph(seed: Path, work: Path) -> Path:
    """A fresh copy of the graph under test, safe to grow in place.

    The pipeline writes every discovered card back into the graph it reads,
    so a run pointed at the recorded graph would mutate its own baseline:
    the next run would measure growth from the previous run's end and the
    seed graph would stop being the fixed start point the curve is relative
    to.  Each run therefore grows a copy, replaced from the seed every time.
    """
    seed, work = Path(seed), Path(work)
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(seed, work)
    return work


def should_record(summary: dict) -> bool:
    """Whether a run measured growth at all.

    A run against a graph with no gap left executes zero rounds.  Saving
    that would overwrite the seed run's real curve with a zero and describe
    a graph the run never grew, so the run leaves the record untouched.
    """
    return bool(summary.get("rounds"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-selfopt")
    parser.add_argument("--app", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--config", default="config/llm.bench.yaml")
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument(
        "--graph-root",
        default="",
        help="graph to grow (default: runs/mobileworld/<app>/graph)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="experiment output dir (default: <graph parent>/experiments)",
    )
    parser.add_argument("--serial", default="")
    args = parser.parse_args(argv)

    package = _package(args.app)
    onboarding = _onboarding(args.app)
    graph_root = resolve_graph_root(args.app, args.graph_root)
    if not (graph_root / "cards").exists():
        print(f"no graph at {graph_root}", file=sys.stderr)
        return 2
    inventory = load_inventory(
        ROOT / "benchmark" / "coverage" / f"{args.app}.yaml"
    )
    out_dir = (
        ROOT / args.out if args.out else graph_root.parent / "experiments"
    )
    # Grow a copy: the graph the run starts from must not change, or the
    # next run's baseline would be this run's result.
    graph_root = working_graph(graph_root, out_dir / "working-graph")
    config = load_config(ROOT / args.config)
    config.paths.root = str(graph_root)
    if args.serial:
        config.device.serial = args.serial
    pipeline = build_pipeline(config, fake_llm=False, fake_device=False)
    pipeline.device.set_app(package)

    start = pipeline.store.load()
    covered = {
        function.id
        for function in inventory
        if graph_coverage([function], start).covered
    }
    rows = []
    attempts: dict[str, int] = {}
    last_target = None
    last_grew = False
    for index in range(1, max(1, args.rounds) + 1):
        target = next_attempt(
            inventory,
            covered,
            attempts,
            last_target=last_target,
            last_grew=last_grew,
        )
        if target is None:
            print("all functions covered; stopping", flush=True)
            break
        attempts[target.id] = attempts.get(target.id, 0) + 1
        goal = (
            f"In the app, {target.label.lower().rstrip('.')} "
            "and leave the result visible on screen."
        )
        before = pipeline.store.load()
        state = launch_state(pipeline.device, package, onboarding)
        patch = pipeline.complete(goal, state)
        after = pipeline.store.load()
        row = make_round(
            index=index,
            target=target,
            goal=goal,
            before=before,
            after=after,
            functions=inventory,
            reason=(patch.reason if patch is not None else "no completion"),
        )
        rows.append(row)
        covered = {
            function.id
            for function in inventory
            if graph_coverage([function], after).covered
        }
        last_target = target
        last_grew = row.cards_after > row.cards_before
        print(
            f"round {index}: {target.id} -> cards {row.cards_before}->"
            f"{row.cards_after}, covered {row.covered_before}->"
            f"{row.covered_after}/{len(inventory)} "
            f"{'OK' if row.completed else 'no gain'} ({row.reason})",
            flush=True,
        )

    end = pipeline.store.load()
    summary = growth(rows, start, end, inventory)
    summary.update({"app": args.app, "finished": _stamp()})
    print(json.dumps(summary, ensure_ascii=False))
    if not should_record(summary):
        print(
            f"no uncovered function in {graph_root}; nothing measured,"
            " record left as it was",
            file=sys.stderr,
        )
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "app": args.app,
        "summary": summary,
        "rounds": [row.__dict__ for row in rows],
        "finished": summary["finished"],
    }
    (out_dir / "selfopt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LatestStore(out_dir / "latest.json").update("selfopt", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
