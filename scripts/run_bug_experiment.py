#!/usr/bin/env python3
"""Run a buggy Themis build and report whether its known crash happened.

    python scripts/run_bug_experiment.py --version AmazeFileManager-3.3.2-#1796 \
        --serial emulator-5600 --config config/llm.bench.yaml

The task text is the one the dataset's own graph would generate for the
build's function, so the comparison against FuncDroid is like for like: same
app, same version, same user-level goal.  When the dataset ships no goal for
a version, the script refuses rather than inventing one — a made-up task would
measure the task, not the method.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.datasets.apk_source import (  # noqa: E402
    ApkUnavailable,
    download,
    find_apk,
    find_in_archive,
)
from specfcg.benchmark.bug_experiment import BugExperiment, summarise  # noqa: E402
from specfcg.datasets.bug_task import task_for  # noqa: E402
from specfcg.benchmark.device_ops import AdbOps  # noqa: E402
from specfcg.datasets.themis import load_dataset  # noqa: E402
from specfcg.executor.mobile_agent_backend import MobileAgentBackend  # noqa: E402
from specfcg.config import load_config  # noqa: E402


def _version(versions, wanted: str):
    for version in versions:
        if version.id == wanted:
            return version
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-bug-experiment")
    parser.add_argument("--version", required=True, help="dataset directory name")
    parser.add_argument("--task", default="", help="task text; defaults to the dataset's goal")
    parser.add_argument("--serial", default="")
    parser.add_argument("--config", default="config/llm.bench.yaml")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--apks", default="/home/farong/hdd/android/themis")
    parser.add_argument("--out", default="runs/themis")
    parser.add_argument("--max-steps", type=int, default=25)
    args = parser.parse_args(argv)

    if not args.serial:
        print("missing --serial", file=sys.stderr)
        return 2

    dataset = Path(args.dataset) if args.dataset else ROOT / "benchmark" / "themis" / "dataset"
    if not dataset.is_dir():
        print(
            f"no dataset at {dataset}; pass --dataset with the FuncDroid "
            f"effectiveness-evaluation directory",
            file=sys.stderr,
        )
        return 2

    versions = load_dataset(dataset)
    version = _version(versions, args.version)
    if version is None:
        print(f"unknown version {args.version}; known: {[v.id for v in versions][:5]}...", file=sys.stderr)
        return 2

    # The crash's stack names the action that reaches it; the dataset's
    # `function_description` describes a page, which cannot reach a crash in
    # code that page never runs.  The stack wins, and when neither yields a
    # task the run is refused rather than given an invented one.
    derived = task_for(version, _dataset_goal(dataset / version.directory))
    task = args.task or (derived.text if derived else "")
    if not task:
        print(
            f"{version.id}: no task can be derived from this crash's stack, "
            f"and inventing one would measure the task instead of the method",
            file=sys.stderr,
        )
        return 2
    print(f"task ({derived.source if derived else 'explicit'}): {task}", flush=True)

    # Two sources, in order: the project's own releases, then F-Droid's
    # archive, which kept builds the projects no longer publish.  Neither is
    # allowed to substitute a neighbouring version.
    candidate = None
    errors: list[str] = []
    for source in (
        lambda: find_apk(version.app, version.version_name),
        lambda: find_in_archive(version.package, version.version_name),
    ):
        try:
            candidate = source()
            break
        except ApkUnavailable as exc:
            errors.append(str(exc))
    if candidate is None:
        print(f"{version.id}: {'; '.join(errors)}", file=sys.stderr)
        return 2
    try:
        apk = download(candidate, Path(args.apks))
    except ApkUnavailable as exc:
        print(f"{version.id}: {exc}", file=sys.stderr)
        return 2

    config = load_config(ROOT / args.config)
    agent = MobileAgentBackend(
        args.serial,
        config.agent.model,
        config.agent.fallback_model,
        Path(args.out) / version.id / "agent",
        base_url=config.llm.base_url,
        api_key=__import__("os").environ.get(config.llm.api_key_env, ""),
    )
    device = AdbOps(args.serial)
    run = BugExperiment(device, agent, Path(args.out)).run(
        version, apk, task, max_steps=args.max_steps
    )
    record = {
        "version": run.version_id,
        "app": run.app,
        "package": run.package,
        "task": run.task,
        "installed": run.installed,
        "steps": run.steps,
        "detected": run.detected,
        "matched_crash": run.matched_crash,
        "error": run.error,
    }
    out = Path(args.out) / version.id / "result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def _dataset_goal(directory: Path) -> str:
    """The goal FuncDroid's own graph records for this build, if any.

    `fdg.json` holds one entry per function with a `function_description` and
    the steps its core logic takes.  The first `to_test` function is the
    build's primary flow, which is what the dataset's crash belongs to.
    """
    path = directory / "fdg.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for entry in data.get("FDG") or []:
        if not isinstance(entry, dict) or not entry.get("to_test", True):
            continue
        description = str(entry.get("function_description") or "").strip()
        if description:
            return description
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
