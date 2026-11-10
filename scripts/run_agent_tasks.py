#!/usr/bin/env python3
"""Run the screenshot-first agent on long-horizon mobile tasks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mobile_agent.agent import MobileAgent, TaskSpec  # noqa: E402
from mobile_agent.device import AndroidDevice  # noqa: E402
from mobile_agent.llm import VLM  # noqa: E402
from mobile_agent.memory import ExperienceStore  # noqa: E402


def load_tasks(path: Path) -> list[TaskSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = []
    for item in data.get("tasks", []):
        tasks.append(
            TaskSpec(
                id=str(item["id"]),
                app=str(item["app"]),
                app_name=str(item.get("app_name", item["app"])),
                goal=str(item["goal"]),
                expect_text=list(item.get("expect_text") or []),
                expect_absent=list(item.get("expect_absent") or []),
                max_steps=int(item.get("max_steps", 25)),
            )
        )
    return tasks


def reset_app(serial: str, package: str) -> None:
    subprocess.run(
        ["adb", "-s", serial, "shell", "pm", "clear", package],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "adb", "-s", serial, "shell", "monkey",
            "-p", package, "-c", "android.intent.category.LAUNCHER", "1",
        ],
        capture_output=True,
        text=True,
    )
    time.sleep(2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-agent-tasks")
    parser.add_argument("--tasks", default="benchmark/agent_tasks.yaml")
    parser.add_argument("--out", default="runs/agent")
    parser.add_argument("--serial", default="47261FDAS00DTQ")
    parser.add_argument("--model", default="auto/gpt-6-luna")
    parser.add_argument(
        "--fallback-model", default="auto/glm-5.3-flash"
    )
    parser.add_argument("--memory", default="runs/agent/experience.jsonl")
    parser.add_argument("--only", default="")
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args(argv)

    tasks = load_tasks(ROOT / args.tasks)
    wanted = {part.strip() for part in args.only.split(",") if part.strip()}
    if wanted:
        tasks = [task for task in tasks if task.id in wanted]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2

    out_root = ROOT / args.out
    out_root.mkdir(parents=True, exist_ok=True)
    memory = ExperienceStore(ROOT / args.memory)

    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.id}: {task.goal[:100]}")
        if not args.no_reset:
            reset_app(args.serial, task.app)
        out = out_root / task.id
        llm = VLM(
            models=(args.model, args.fallback_model),
            log_path=out / "llm_calls.jsonl",
        )
        device = AndroidDevice(args.serial, task.app)
        agent = MobileAgent(device, llm, memory, out_root)
        result = agent.run(task)
        (out_root / "summary.jsonl").open("a", encoding="utf-8").write(
            json.dumps(asdict(result), ensure_ascii=False) + "\n"
        )
        print(
            f"    success={result.success} steps={result.steps} "
            f"calls={result.llm_calls} time={result.elapsed_s}s "
            f"reason={result.reason[:140]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
