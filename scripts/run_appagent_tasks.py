#!/usr/bin/env python3
"""Thin task runner + evaluator around the open-source AppAgent.

The agent itself is third_party/AppAgent (MIT). This script only:
  - resets/launches the app and dismisses first-run onboarding,
  - feeds the task description to AppAgent's own task_executor.py,
  - copies AppAgent's real screenshots/logs into runs/appagent/,
  - scores the final state with a strict external verifier + text check.

No AppAgent policy/loop/action code is reimplemented here.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
APPAGENT = ROOT / "third_party" / "AppAgent"
sys.path.insert(0, str(ROOT))

from mobile_agent import prompts  # noqa: E402  (evaluation prompt only)
from mobile_agent.device import AndroidDevice  # noqa: E402  (setup/evaluation only)
from mobile_agent.llm import VLM  # noqa: E402  (external verifier only)


@dataclass
class Task:
    id: str
    app: str
    app_name: str
    goal: str
    expect_text: list[str] = field(default_factory=list)
    expect_absent: list[str] = field(default_factory=list)
    max_steps: int = 25


def load_tasks(path: Path) -> list[Task]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Task(
            id=str(item["id"]),
            app=str(item["app"]),
            app_name=str(item.get("app_name", item["app"])),
            goal=str(item["goal"]),
            expect_text=list(item.get("expect_text") or []),
            expect_absent=list(item.get("expect_absent") or []),
            max_steps=int(item.get("max_steps", 25)),
        )
        for item in data.get("tasks", [])
    ]


def reset_and_prepare(serial: str, package: str) -> None:
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
    device = AndroidDevice(serial, package)
    device.start_app()
    # AppAgent uses `adb shell uiautomator dump`, which conflicts with the
    # uiautomator2/ATX instrumentation we use for setup. Stop ATX before
    # handing the device to AppAgent; this is setup-only, not agent logic.
    try:
        device._d().stop_uiautomator()
    except Exception:
        pass
    # uiautomator2 may have connected to an already-running server, in which
    # case stop_uiautomator() is a no-op. Kill its device-side app_process so
    # it cannot conflict with AppAgent's `adb shell uiautomator dump`.
    subprocess.run(
        ["adb", "-s", serial, "shell", "pkill", "-f", "com.wetest.uia2"],
        capture_output=True,
        text=True,
    )
    # AppAgent's uiautomator dump fails if the app is still animating.
    time.sleep(4.0)


def find_new_task_dir(before: set[Path], app: str) -> Path | None:
    after = set(APPAGENT.glob(f"tasks/task_{app}_*"))
    new = [path for path in after - before if path.is_dir()]
    if not new:
        return None
    return max(new, key=lambda path: path.stat().st_mtime)


def parse_log(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not log_path.exists():
        return rows
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def field(text: str, name: str, stops: tuple[str, ...]) -> str:
    stop = "|".join(re.escape(item) for item in stops)
    match = re.search(
        rf"{name}:\s*(.*?)(?=\n(?:{stop}):|\Z)", text, re.DOTALL
    )
    return match.group(1).strip() if match else ""


def parse_response(text: str) -> dict[str, str]:
    observation = field(text, "Observation", ("Thought", "Action", "Summary"))
    thought = field(text, "Thought", ("Action", "Summary"))
    action = field(text, "Action", ("Summary",))
    summary = field(text, "Summary", ())
    tool, action_args = "unknown", ""
    match = re.match(r"([A-Za-z_]+)\((.*)\)", action.strip(), re.DOTALL)
    if match:
        tool, action_args = match.group(1), match.group(2).strip()
    elif action.strip().upper().startswith("FINISH"):
        tool, action_args = "FINISH", ""
    return {
        "observation": observation,
        "thought": thought,
        "action": action,
        "action_tool": tool,
        "action_args": action_args,
        "summary": summary,
    }


def image_part(path: Path) -> dict[str, Any]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + data},
    }


def parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def verify(
    task: Task,
    steps: list[dict[str, Any]],
    final_shot: Path,
    final_ui: str,
    deterministic_ok: bool,
    out_dir: Path,
    model: str,
    fallback: str,
) -> tuple[bool, str]:
    history = "\n".join(
        f"{step['step']}. {step['action_tool']}({step['action_args']}) -> "
        f"{step['summary'][:160]}"
        for step in steps[-18:]
    ) or "None."
    prompt = prompts.VERIFIER.format(
        goal=task.goal,
        expect=task.expect_text,
        expect_absent=task.expect_absent,
        plan="AppAgent (open-source) has no separate planner; it acts one round at a time.",
        history=history,
    ) + f"\n\nFinal UI elements:\n{final_ui}"
    content: Any = [{"type": "text", "text": prompt}]
    if final_shot.exists():
        content.append(image_part(final_shot))
    vlm = VLM(
        models=(model, fallback),
        log_path=out_dir / "verifier_llm.jsonl",
    )
    try:
        message = vlm.chat(
            [
                {"role": "system", "content": "You verify GUI task completion."},
                {"role": "user", "content": content},
            ],
            max_tokens=500,
            purpose="verifier",
        )
        data = parse_json(message.content or "")
    except Exception as exc:
        return deterministic_ok, f"Verifier error: {exc!r}"
    if not data:
        return deterministic_ok, "Verifier output was not valid JSON."
    success = bool(data.get("success", False))
    reason = str(data.get("reason", "")).strip()
    if not deterministic_ok:
        success = False
        reason = (
            f"Expected visible evidence {task.expect_text} / absent "
            f"{task.expect_absent} was not confirmed. " + reason
        ).strip()
    return success, reason or "No reason provided."


def run_task(
    task: Task,
    serial: str,
    out_root: Path,
    model: str,
    fallback: str,
    timeout: int,
    no_reset: bool,
) -> dict[str, Any]:
    out_dir = out_root / task.id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    error = ""
    appagent_seconds = 0.0
    stdout = ""

    if not no_reset:
        reset_and_prepare(serial, task.app)

    before = set(APPAGENT.glob(f"tasks/task_{task.id}_*"))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    agent_started = time.perf_counter()
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/task_executor.py",
                "--app", task.id,
                "--root_dir", ".",
            ],
            cwd=APPAGENT,
            input=f"y\n{task.goal}\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        stdout = (proc.stdout or "") + "\n" + (proc.stderr or "")
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") + "\n" + (exc.stderr or "")
        returncode = -1
        error = f"AppAgent timeout after {timeout}s"
    appagent_seconds = round(time.perf_counter() - agent_started, 1)

    task_dir = find_new_task_dir(before, task.id)
    if task_dir is None:
        error = error or "AppAgent did not create a task directory"
        task_dir = APPAGENT / "tasks" / "_missing"
    (out_dir / "appagent_stdout.log").write_text(stdout, encoding="utf-8")
    if (APPAGENT / "config.yaml").exists():
        shutil.copy2(APPAGENT / "config.yaml", out_dir / "config.yaml")
    if task_dir.exists():
        for path in task_dir.glob("log_*.txt"):
            shutil.copy2(path, out_dir / "appagent_log.jsonl")
        for path in task_dir.glob("*_labeled.png"):
            match = re.search(r"_(\d+)_labeled\.png$", path.name)
            if not match:
                continue
            number = int(match.group(1))
            shutil.copy2(path, out_dir / f"step_{number:02d}_labeled.png")

    log_path = next(iter(task_dir.glob("log_*.txt")), None) if task_dir.exists() else None
    rows = parse_log(log_path) if log_path else []
    steps: list[dict[str, Any]] = []
    for row in rows:
        parsed = parse_response(str(row.get("response", "")))
        step_no = int(row.get("step", len(steps) + 1))
        steps.append(
            {
                "step": step_no,
                "observation": parsed["observation"],
                "thought": parsed["thought"],
                "action": parsed["action"],
                "action_tool": parsed["action_tool"],
                "action_args": parsed["action_args"],
                "summary": parsed["summary"],
                "response": str(row.get("response", "")),
                "before": f"step_{step_no:02d}_labeled.png",
            }
        )
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    final_shot = out_dir / "final.jpg"
    final_ui = ""
    try:
        device = AndroidDevice(serial, task.app)
        device.screenshot(final_shot)
        final_ui = device.ui_text()
    except Exception as exc:
        error = (error + f"; final capture error: {exc!r}").strip("; ")
    (out_dir / "final_ui.txt").write_text(final_ui, encoding="utf-8")

    deterministic_ok = all(
        text.lower() in final_ui.lower() for text in task.expect_text
    ) and all(
        text.lower() not in final_ui.lower() for text in task.expect_absent
    )
    verified, reason = verify(
        task, steps, final_shot, final_ui, deterministic_ok,
        out_dir, model, fallback,
    )
    success = bool(verified and deterministic_ok)
    elapsed = round(time.perf_counter() - started, 1)
    result = {
        "id": task.id,
        "goal": task.goal,
        "app": task.app,
        "app_name": task.app_name,
        "success": success,
        "verifier_success": verified,
        "deterministic_ok": deterministic_ok,
        "reason": reason,
        "rounds": len(steps),
        "appagent_seconds": appagent_seconds,
        "elapsed_s": elapsed,
        "model": model,
        "expect_text": task.expect_text,
        "expect_absent": task.expect_absent,
        "task_dir": str(task_dir),
        "returncode": returncode,
        "error": error,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out_root / "summary.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-appagent-tasks")
    parser.add_argument("--tasks", default="benchmark/agent_tasks.yaml")
    parser.add_argument("--out", default="runs/appagent")
    parser.add_argument("--serial", default="47261FDAS00DTQ")
    parser.add_argument("--model", default="auto/gpt-6-luna")
    parser.add_argument("--fallback-model", default="auto/glm-5.3-flash")
    parser.add_argument("--only", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args(argv)

    if not (APPAGENT / "scripts" / "task_executor.py").exists():
        print(f"AppAgent not found at {APPAGENT}", file=sys.stderr)
        return 2
    tasks = load_tasks(ROOT / args.tasks)
    wanted = {part.strip() for part in args.only.split(",") if part.strip()}
    if wanted:
        tasks = [task for task in tasks if task.id in wanted]
    if not tasks:
        print("no tasks selected", file=sys.stderr)
        return 2

    out_root = ROOT / args.out
    out_root.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.id}: {task.goal[:100]}")
        result = run_task(
            task, args.serial, out_root, args.model, args.fallback_model,
            args.timeout, args.no_reset,
        )
        print(
            f"    success={result['success']} rounds={result['rounds']} "
            f"agent={result['appagent_seconds']}s total={result['elapsed_s']}s "
            f"reason={result['reason'][:140]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
