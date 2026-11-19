#!/usr/bin/env python3
"""Collect the reference traces for one app and build its graph.

Traces are replayed on the real device (real screenshots, real UI dumps) with
``collect_trace.run_actions``; then the existing pipeline mines a function card
per trace and the edge builder adds semantic edges.  Nothing here reimplements
mining, planning, or execution.

Run:
  PYTHONPATH=. python scripts/build_app_graph.py --app activitydiary
  PYTHONPATH=. python scripts/build_app_graph.py --app markor --skip-collect
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.executor.device import Uiautomator2Device  # noqa: E402
from specfcg.traces.recorder import trace_from_dict, trace_to_dict  # noqa: E402
from specfcg.benchmark.first_run import grant_storage_access, settle_first_run
from specfcg.traces.scripted import run_actions  # noqa: E402


def _run_actions(device, actions) -> None:
    for spec_action in actions or []:
        device.execute(
            str(spec_action.get("action", "")),
            str(spec_action.get("target", "")),
            str(spec_action.get("args", "")),
        )


def collect(
    spec_path: Path, trace_dir: Path, serial: str, only: set[str]
) -> list[Path]:
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    app = str(spec["app"])
    package = str(spec["package"])
    onboarding = list(spec.get("onboarding") or [])
    device = Uiautomator2Device(serial, settle_s=0.6)
    device.set_app(package)
    trace_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in spec.get("traces") or []:
        trace_id = str(item["id"])
        if only and trace_id not in only:
            continue
        if item.get("reset"):
            subprocess.run(
                ["adb", "-s", serial, "shell", "pm", "clear", package],
                capture_output=True,
            )
            # `pm clear` revokes runtime permissions along with the app's
            # data.  Without re-granting storage the file browser shows an
            # empty directory and every file trace fails for a reason that
            # has nothing to do with the trace.
            grant_storage_access(device, package)
            time.sleep(1.0)
        device.start_app(package)
        # A first-run dialog is not part of any function under study, and a
        # trace that opens on one records the dialog instead of the app.
        settle_first_run(device, package, settle_s=2.0, rounds=8)
        # Onboarding and the prelude put the app in the state the trace
        # assumes; neither is recorded, so the card describes only the
        # function under study.
        if item.get("reset"):
            _run_actions(device, onboarding)
        _run_actions(device, item.get("prelude"))
        trace = run_actions(
            device,
            list(item.get("actions") or []),
            app=package,
            trace_id=trace_id,
            goal=str(item.get("goal") or ""),
            function_name=str(item.get("name") or ""),
            metadata={
                "source": "scripted-benchmark",
                "app": app,
                "device": serial,
            },
        )
        path = trace_dir / f"{trace_id}.json"
        path.write_text(
            json.dumps(trace_to_dict(trace), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ok = sum(1 for step in trace.steps if step.success)
        print(
            f"trace {trace_id}: {len(trace.steps)} steps, {ok} ok -> {path}",
            flush=True,
        )
        written.append(path)
    return written


def declared_names(spec: dict) -> dict[str, str]:
    """The function name each trace spec declares, by trace id.

    A spec that names its function is stating which function the trace
    exercises.  Reading it here, rather than only at collection time, means a
    trace recorded before a name was added still mines under that name — the
    evidence is unchanged either way.
    """
    return {
        str(item["id"]): str(item["name"])
        for item in spec.get("traces") or []
        if item.get("id") and item.get("name")
    }


def grow(pipeline, traces: list[Path], names: dict[str, str] | None = None) -> list[str]:
    """Mine every trace, then derive the semantic edges once.

    Mining adds one card per trace and the sequence edges observed inside
    it.  Semantic edges are a function of the whole card set, so deriving
    them after every trace runs the same function over every growing
    prefix: N traces cost N calls carrying 1+2+...+N card rows.  Asking
    once, after the last card is in, is the same answer for one call.
    """
    mined: list[str] = []
    names = names or {}
    for path in traces:
        trace = trace_from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
        declared = names.get(getattr(trace, "trace_id", ""), "")
        if declared and not getattr(trace, "function_name", ""):
            trace.function_name = declared
        print(f"--- mining {path.stem} ---", flush=True)
        patch = pipeline.mine_trace(trace)
        mined += [card.name for card in patch.new_cards]
        print(f"    new cards: {[card.name for card in patch.new_cards]}",
              flush=True)
    edges = pipeline.build_graph([])
    print(
        f"    graph: {len(pipeline.graph.cards)} cards, {len(edges)} edges",
        flush=True,
    )
    return mined


def build(
    traces: list[Path],
    root: Path,
    config_path: Path,
    names: dict[str, str] | None = None,
) -> dict[str, int]:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    config = load_config(config_path)
    config.paths.root = str(root)
    pipeline = build_pipeline(config, fake_llm=False, fake_device=False)

    grow(pipeline, traces, names)
    graph = pipeline.store.load()
    return {"cards": len(graph.cards), "edges": len(graph.edges)}


def select_traces(
    spec: dict, trace_dir: Path, only: set[str]
) -> list[Path]:
    """Trace files the spec lists that exist on disk, optionally a subset.

    ``only`` seeds a deliberately incomplete graph: the probes and the
    self-optimization curve are only meaningful when functions are missing,
    so the same builder has to accept a subset of the traces.
    """
    paths: list[Path] = []
    for item in spec.get("traces") or []:
        trace_id = str(item["id"])
        if only and trace_id not in only:
            continue
        path = trace_dir / f"{trace_id}.json"
        if path.exists():
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-app-graph")
    parser.add_argument("--app", required=True)
    parser.add_argument("--serial", default="")
    parser.add_argument("--config", default="config/llm.yaml")
    parser.add_argument("--traces-dir", default="runs/mobileworld")
    parser.add_argument(
        "--only",
        default="",
        help="comma list of trace ids to mine (seeds an incomplete graph)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="graph root to write (default: runs/mobileworld/<app>/graph)",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="rebuild the graph from traces already on disk",
    )
    args = parser.parse_args(argv)

    spec_path = ROOT / "benchmark" / "traces" / f"{args.app}.yaml"
    if not spec_path.exists():
        print(f"no trace spec {spec_path}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    trace_dir = ROOT / args.traces_dir / args.app / "traces"
    only = {item.strip() for item in args.only.split(",") if item.strip()}

    if args.skip_collect:
        traces = select_traces(spec, trace_dir, only)
    else:
        if not args.serial:
            print("--serial is required unless --skip-collect", file=sys.stderr)
            return 2
        traces = collect(spec_path, trace_dir, args.serial, only)

    if not traces:
        print("no traces to mine", file=sys.stderr)
        return 2
    root = (
        ROOT / args.out
        if args.out
        else ROOT / args.traces_dir / args.app / "graph"
    )
    counts = build(
        traces, root, ROOT / args.config, declared_names(spec)
    )
    print(json.dumps({"app": args.app, "root": str(root), **counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
