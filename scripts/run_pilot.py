#!/usr/bin/env python3
"""Run user-level pilot cases on a real device with per-case reset."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from specfcg.benchmark.cases import (  # noqa: E402
    app_packages,
    load_apps,
    load_cases,
)
from specfcg.benchmark.pilot import Pilot  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.executor.summarizer import PlainStateSummarizer  # noqa: E402


def _reset_omninotes(serial: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reset_omninotes.py"),
            "--serial",
            serial,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "OmniNotes reset failed: "
            f"{completed.stdout.strip()} {completed.stderr.strip()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-pilot")
    parser.add_argument(
        "--config", default=str(ROOT / "config" / "llm.yaml")
    )
    parser.add_argument(
        "--cases", default=str(ROOT / "benchmark" / "cases" / "omninotes.yaml")
    )
    parser.add_argument(
        "--apps", default=str(ROOT / "benchmark" / "apps.yaml")
    )
    parser.add_argument(
        "--output", default=str(ROOT / "runs" / "pilot" / "omninotes.jsonl")
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--no-llm-summary", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config))
    packages = app_packages(load_apps(Path(args.apps)))
    cases = load_cases(Path(args.cases))
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if not cases:
        print("pilot: no cases")
        return 1

    app_name = cases[0].app
    package = packages.get(app_name, "")
    if not package:
        print(f"pilot: no package for app {app_name!r}")
        return 1

    pipeline = build_pipeline(config, False, False)
    pipeline.executor.summarizer = PlainStateSummarizer()

    reset = None
    if not args.no_reset:
        if package != "it.feio.android.omninotes.foss":
            print(f"pilot: no reset support for package {package}")
            return 1
        serial = config.device.serial or ""
        reset = lambda: _reset_omninotes(serial)  # noqa: E731

    if hasattr(pipeline.device, "set_app"):
        pipeline.device.set_app(package)

    detail_dir = Path(args.output).parent / "details"
    pilot = Pilot(
        pipeline, reset=reset, app=package, detail_dir=detail_dir
    )
    rows = pilot.run_to_jsonl(cases, Path(args.output))

    completed = sum(1 for row in rows if row.success)
    planned = sum(1 for row in rows if row.planned)
    actions = sum(row.actions_ok for row in rows)
    total_steps = sum(row.steps for row in rows)
    print(
        f"pilot: cases={len(rows)} planned={planned} "
        f"completion={completed}/{len(rows)} "
        f"actions={actions}/{total_steps} "
        f"llm_calls={sum(row.llm_calls for row in rows)} "
        f"output={args.output}"
    )
    for row in rows:
        print(
            f"- {row.case_id}: planned={row.planned} "
            f"success={row.success} goal={row.goal_success} "
            f"steps={row.steps} actions_ok={row.actions_ok} "
            f"path={row.path} failure={row.failure_type} "
            f"plan_s={row.plan_s} exec_s={row.execute_s}"
        )
    return 0 if completed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
