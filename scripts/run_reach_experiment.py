#!/usr/bin/env python3
"""Run the reachability experiment on Themis builds: graph description vs goal.

    python scripts/run_reach_experiment.py --serial emulator-5610 \
        --config config/llm.bench.yaml --versions all --max-steps 20

Both arms use the same agent on the same build.  The graph arm is given the
description the Function Contract Graph's planner produces for the goal; the
raw arm is given the goal itself.  The oracle is the final UI dump: did the
screen the build's crash happens on appear?

Why this instead of counting crashes: the crash needs the agent to finish the
walk *and* land on the exact state that crashes, so with a weak executor both
arms sit at zero and the difference says nothing.  A run that reaches the
dialog is a success whether or not the bug fires, so the measurement sits
where the method's claim does.

The graph arm is skipped for a build whose graph has no plan for the goal; a
`no_plan` is recorded, not counted as a reach.  That is the graph's own
failure, and hiding it would flatter the arm.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.apk_source import (  # noqa: E402
    ApkUnavailable,
    download,
    find_apk,
    find_in_archive,
)
from specfcg.benchmark.device_ops import AdbOps  # noqa: E402
from specfcg.benchmark.reach_experiment import (  # noqa: E402
    ReachExperiment,
    ReachRun,
    paired_summary,
    target_for_version,
)
from specfcg.benchmark.themis import load_dataset  # noqa: E402
from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.executor.mobile_agent_backend import MobileAgentBackend  # noqa: E402


def _apk_for(version, apks: Path) -> Path | None:
    """The exact build's APK, from the project's releases then F-Droid."""
    for source in (
        lambda: find_apk(version.app, version.version_name),
        lambda: find_in_archive(version.package, version.version_name),
    ):
        try:
            return download(source(), apks)
        except ApkUnavailable:
            continue
    return None


# The benchmark's graph directories are named for the app's short name, while
# a dataset version carries its package.  Without the mapping every build
# would look like it has no graph.
GRAPH_DIR_BY_PACKAGE = {
    "net.gsantner.markor": "markor",
    "com.amaze.filemanager": "amaze",
    "it.feio.android.omninotes.foss": "omninotes",
    "de.rampro.activitydiary": "activitydiary",
}


def _graph_root(package: str, graph_dir: Path) -> Path | None:
    """The graph built for this app, if one exists."""
    names = [GRAPH_DIR_BY_PACKAGE.get(package, ""), package]
    for name in names:
        if not name:
            continue
        for candidate in (graph_dir / name, graph_dir / name / "graph"):
            if (candidate / "cards").is_dir():
                return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-reach-experiment")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--config", default="config/llm.bench.yaml")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--apks", default="/home/farong/hdd/android/themis")
    parser.add_argument("--graphs", default="runs/mobileworld")
    parser.add_argument("--out", default="runs/reach")
    parser.add_argument("--versions", default="all")
    parser.add_argument("--max-steps", type=int, default=20)
    args = parser.parse_args(argv)

    dataset = (
        Path(args.dataset)
        if args.dataset
        else ROOT / "benchmark" / "themis" / "dataset"
    )
    versions = load_dataset(dataset)
    wanted = {v.strip() for v in args.versions.split(",") if v.strip()}
    if "all" not in wanted:
        versions = [v for v in versions if v.id in wanted]

    config = load_config(ROOT / args.config)
    device = AdbOps(args.serial)
    runs: list[ReachRun] = []
    skipped: list[dict] = []

    for version in versions:
        target = target_for_version(version)
        if target is None:
            skipped.append(
                {"version": version.id, "reason": "no named screen in the stack"}
            )
            continue
        apk = _apk_for(version, Path(args.apks))
        if apk is None:
            skipped.append(
                {"version": version.id, "reason": "no APK for this exact build"}
            )
            continue

        agent = MobileAgentBackend(
            args.serial,
            config.agent.model,
            config.agent.fallback_model,
            Path(args.out) / version.id / "agent",
            base_url=config.llm.base_url,
            api_key=os.environ.get(config.llm.api_key_env, ""),
        )

        # The raw arm: the goal alone, which is what a user would type.
        raw_experiment = ReachExperiment(
            device, None, None, Path(args.out)
        )
        raw_run = raw_experiment.run(
            version, target, "raw", _callable_agent(agent), args.max_steps,
            apk=apk,
        )
        runs.append(raw_run)
        print(
            f"{version.id:40s} raw   reached={raw_run.reached} "
            f"steps={raw_run.steps} {raw_run.error[:40]}",
            flush=True,
        )

        # The graph arm: the same agent, given the graph's description.
        graph_root = _graph_root(version.package, Path(args.graphs))
        if graph_root is None:
            skipped.append(
                {"version": version.id, "reason": "no graph built for this app"}
            )
            continue
        cfg = load_config(ROOT / args.config)
        cfg.paths.root = str(graph_root)
        # The pipeline's own agent must act on the device this run was given;
        # the config's serial is one machine's default.
        cfg.device.serial = args.serial
        pipeline = build_pipeline(cfg, fake_llm=False, fake_device=False)
        graph_run = ReachExperiment(
            device, pipeline, None, Path(args.out)
        ).run(
            version,
            target,
            "graph",
            _graph_agent(pipeline, agent),
            args.max_steps,
            apk=apk,
        )
        runs.append(graph_run)
        print(
            f"{version.id:40s} graph reached={graph_run.reached} "
            f"steps={graph_run.steps} {graph_run.error[:40]}",
            flush=True,
        )

    summary = paired_summary(runs)
    report = {
        "runs": [run.as_record() for run in runs],
        "skipped": skipped,
        **summary,
    }
    out = Path(args.out) / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("per_arm", "paired")}, indent=2))
    print(f"skipped {len(skipped)}; report {out}")
    return 0


def _callable_agent(agent):
    """Adapt the backend to the runner's `agent(task) -> AgentRun` shape."""
    from specfcg.benchmark.suite_runner import AgentRun

    def run(task):
        trace = agent.run(task.goal, task.max_steps, app=task.package)
        return AgentRun(
            steps=[
                {
                    "action": step.action,
                    "target": step.target,
                    "args": step.args,
                    "ok": bool(step.success),
                }
                for step in trace.steps
            ],
            done=trace.done,
            observed_ui=[step.before_state for step in trace.steps]
            + ([trace.final_ui] if trace.final_ui else []),
            task_text=task.goal,
            error=trace.error,
        )

    return run


def _graph_agent(pipeline, agent):
    """Give the agent the planner's description instead of the goal.

    The plan is made once from the launch state, as the pipeline's own
    executor does; a build the graph cannot plan for records `no_plan`
    rather than silently falling back to the raw goal.
    """
    from specfcg.benchmark.suite_runner import AgentRun

    def run(task):
        state = agent.observe(task.package)
        plan = pipeline.plan(task.goal, state, app=task.package)
        if plan is None or not plan.path:
            return AgentRun(steps=[], no_plan=True, task_text=task.goal)
        trace = agent.run(plan.description, task.max_steps, app=task.package)
        return AgentRun(
            steps=[
                {
                    "action": step.action,
                    "target": step.target,
                    "args": step.args,
                    "ok": bool(step.success),
                }
                for step in trace.steps
            ],
            done=trace.done,
            observed_ui=[step.before_state for step in trace.steps]
            + ([trace.final_ui] if trace.final_ui else []),
            task_text=plan.description,
            error=trace.error,
            predicted_path=list(plan.path),
        )

    return run


if __name__ == "__main__":
    raise SystemExit(main())
