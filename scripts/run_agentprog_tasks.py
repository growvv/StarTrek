#!/usr/bin/env python3
"""Thin task runner + final-state evaluator around the open-source AgentProg agent.

AgentProg is third_party/AgentProg (Tsinghua AIR, arXiv 2512.10371).  This
script only:
  - resets/launches the app and keeps the device awake,
  - invokes AgentProg's own ``agentprog_pipeline`` (no policy/action code is
    reimplemented),
  - records AgentProg's real model I/O and per-step screenshots,
  - scores the FINAL observable state (not intermediate process evidence).

Success rule: the final screen must show the end state asked for by the goal,
or an unambiguous consequence of it.  Hidden database state and the exact
navigation path are not required.

Run with the AgentProg virtualenv:
  .venv-agentprog/Scripts/python scripts/run_agentprog_tasks.py --tasks all
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
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTPROG = ROOT / "third_party" / "AgentProg"
MAGPIE = "http://127.0.0.1:3425/v1"
DEFAULT_SERIAL = "47261FDAS00DTQ"
DEFAULT_MODEL = "auto/gpt-6-luna"
DEFAULT_FALLBACK = "auto/gpt-6.1-sol"
DEFAULT_UITARS_MODEL = "auto/gpt-6-luna"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AGENTPROG))


def configure_env(ui_tars_model: str, model: str) -> None:
    """Set the magpie endpoint before AgentProg is imported."""
    os.environ["GEMINI_BASE_URL"] = MAGPIE
    os.environ["GEMINI_API_KEY"] = "magpie"
    os.environ["DOUBAO_BASE_URL"] = MAGPIE
    os.environ["ARK_API_KEY"] = "magpie"
    os.environ["MODEL"] = f"openai/{model}"
    os.environ["UITARS_MODEL"] = ui_tars_model
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"


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
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Task(
            id=str(item["id"]),
            app=str(item["app"]),
            app_name=str(item.get("app_name", item["app"])),
            goal=str(item["goal"]).strip(),
            expect_text=list(item.get("expect_text") or []),
            expect_absent=list(item.get("expect_absent") or []),
            max_steps=int(item.get("max_steps") or 25),
        )
        for item in data["tasks"]
    ]


# ---------------------------------------------------------------- device helpers

def adb(serial: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


INTRO_ACTIVITIES = {
    # First-run onboarding is app setup, not part of any benchmark task.
    "it.feio.android.omninotes.foss": "it.feio.android.omninotes.intro.IntroActivity",
}


def _focused_activity(serial: str) -> str:
    out = adb(serial, "shell", "dumpsys", "window").stdout or ""
    match = re.search(r"mCurrentFocus=Window\{\S+ \S+ (\S+)\}", out)
    return match.group(1) if match else ""


def _dump_ui_raw(serial: str) -> str:
    adb(serial, "shell", "uiautomator", "dump", "/sdcard/_setup_ui.xml", timeout=30)
    return adb(serial, "exec-out", "cat", "/sdcard/_setup_ui.xml", timeout=30).stdout or ""


def dismiss_known_intro(serial: str, package: str, limit: int = 8) -> int:
    """Dismiss a known first-run intro by tapping its Next button.

    Only the app's own intro is touched; any real task screen is left alone.
    Returns the number of taps performed (0 if there was no intro).
    """
    activity = INTRO_ACTIVITIES.get(package)
    if not activity:
        return 0
    taps = 0
    for _ in range(limit):
        if activity not in _focused_activity(serial):
            break
        xml = _dump_ui_raw(serial)
        if "<hierarchy" not in xml:
            break
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            break
        target = None
        for node in root.iter("node"):
            resource_id = node.get("resource-id") or ""
            if resource_id.endswith(":id/next") or resource_id.endswith(":id/done"):
                target = node
                break
        if target is None:
            break
        bounds = re.findall(r"-?\d+", target.get("bounds") or "")
        if len(bounds) != 4:
            break
        x1, y1, x2, y2 = (int(value) for value in bounds)
        # UI-TARS grounding on this screen resolves to the button's reported
        # center (verified at 865, 2121 on 1008x2244); use the same point.
        adb(serial, "shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        taps += 1
        time.sleep(0.8)
    if taps:
        print(f"[runner] dismissed {package} first-run intro with {taps} tap(s)", flush=True)
    return taps


def prepare_device(serial: str, package: str) -> None:
    """Reset the app and put the device in a stable state (setup only)."""
    installed = adb(serial, "shell", "pm", "list", "packages", package).stdout or ""
    if package not in installed:
        raise RuntimeError(f"{package} is not installed on {serial}")
    adb(serial, "shell", "svc", "power", "stayon", "true")
    adb(serial, "shell", "wm", "dismiss-keyguard")
    adb(serial, "shell", "settings", "put", "global", "window_animation_scale", "0")
    adb(serial, "shell", "settings", "put", "global", "transition_animation_scale", "0")
    adb(serial, "shell", "settings", "put", "global", "animator_duration_scale", "0")
    adb(serial, "shell", "am", "force-stop", package)
    adb(serial, "shell", "pm", "clear", package)
    # Android 13+ shows a notification-permission dialog on first launch.
    # Grant it as part of environment setup (it is not part of any task).
    adb(serial, "shell", "pm", "grant", package, "android.permission.POST_NOTIFICATIONS")
    adb(
        serial, "shell", "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    time.sleep(2.5)
    dismiss_known_intro(serial, package)


def capture_screenshot(serial: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"],
            stdout=handle,
            timeout=60,
        )


def capture_final(serial: str, out_dir: Path) -> tuple[Path, str]:
    png = out_dir / "final.png"
    jpg = out_dir / "final.jpg"
    capture_screenshot(serial, png)
    try:
        from PIL import Image

        Image.open(png).convert("RGB").save(jpg, quality=88)
    except Exception:  # noqa: BLE001
        jpg = png
    xml = dump_ui(serial, out_dir / "final_ui.xml")
    text = ui_text(xml)
    (out_dir / "final_ui.txt").write_text(text, encoding="utf-8")
    return jpg, text


def dump_ui(serial: str, out_path: Path) -> str:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            adb(serial, "shell", "uiautomator", "dump", "/sdcard/agentprog_ui.xml", timeout=30)
            result = adb(serial, "exec-out", "cat", "/sdcard/agentprog_ui.xml", timeout=30)
            if result.stdout and "<hierarchy" in result.stdout:
                out_path.write_text(result.stdout, encoding="utf-8")
                return result.stdout
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.0)
    out_path.write_text(f"<!-- UI dump failed: {last_error!r} -->", encoding="utf-8")
    return ""


def ui_text(xml: str) -> str:
    if not xml:
        return ""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "\n".join(re.findall(r'(?:text|content-desc)="([^"]+)"', xml))
    parts: list[str] = []
    seen: set[str] = set()
    for node in root.iter("node"):
        for attr in ("text", "content-desc"):
            value = (node.get(attr) or "").strip()
            if value and value not in seen:
                seen.add(value)
                parts.append(value)
    return "\n".join(parts)


# ---------------------------------------------------------------- model tracing

def _truncate_text(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return (
        text[:head]
        + f"\n...[truncated {len(text) - limit} chars; tail follows]...\n"
        + text[-tail:]
    )


def _clean_messages(messages: Any, text_limit: int = 6000) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    if not isinstance(messages, list):
        return [{"raw": str(messages)[:text_limit]}]
    for message in messages:
        if not isinstance(message, dict):
            clean.append({"raw": str(message)[:text_limit]})
            continue
        content = message.get("content")
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if not isinstance(part, dict):
                    parts.append({"type": "text", "text": str(part)[:text_limit]})
                elif part.get("type") == "image_url":
                    url = str(part.get("image_url", {}).get("url", ""))
                    parts.append({"type": "image_url", "bytes": len(url)})
                elif part.get("type") == "text":
                    text = str(part.get("text", ""))
                    parts.append(
                        {
                            "type": "text",
                            "text": _truncate_text(text, text_limit),
                            "truncated": len(text) > text_limit,
                            "chars": len(text),
                        }
                    )
                else:
                    parts.append(part)
            clean.append({**message, "content": parts})
        else:
            clean.append({**message, "content": str(content)[:text_limit]})
    return clean


def _response_text(response: Any) -> tuple[str, dict[str, Any] | None]:
    try:
        raw = response.get_raw()
    except Exception:  # noqa: BLE001
        raw = None
    usage = None
    if raw is not None:
        try:
            usage = {
                "prompt_tokens": getattr(raw.usage, "prompt_tokens", None),
                "completion_tokens": getattr(raw.usage, "completion_tokens", None),
            }
        except Exception:  # noqa: BLE001
            usage = None
    try:
        return str(response), usage
    except Exception:  # noqa: BLE001
        return repr(response), usage


class ModelTrace:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def wrap(self, fn, purpose: str):
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            request = _clean_messages(args[0] if args else kwargs.get("messages"))
            try:
                response = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                self._write(
                    {
                        "purpose": purpose,
                        "duration_s": round(time.perf_counter() - started, 2),
                        "request": request,
                        "error": repr(exc),
                    }
                )
                raise
            text, usage = _response_text(response)
            self._write(
                {
                    "purpose": purpose,
                    "duration_s": round(time.perf_counter() - started, 2),
                    "request": request,
                    "response": text,
                    "usage": usage,
                }
            )
            return response

        return wrapped

    def _write(self, record: dict[str, Any]) -> None:
        self.calls += 1
        record = {"call": self.calls, **record}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def install_ui_tars_trace(trace: ModelTrace) -> None:
    """Wrap AgentProg's UI-TARS grounding client without changing behavior."""
    import agentprog.all_utils.ui_tars_utils as ui_tars_utils

    if getattr(ui_tars_utils, "_star_trek_traced", False):
        return
    original = ui_tars_utils.init_get_ui_tars_response

    def traced_init(*args, **kwargs):
        get_response = original(*args, **kwargs)
        return trace.wrap(get_response, "ui_tars_grounding")

    ui_tars_utils.init_get_ui_tars_response = traced_init
    ui_tars_utils._star_trek_traced = True


# ---------------------------------------------------------------- final-state check

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


def verify_final_state(
    task: Task,
    final_shot: Path,
    final_ui: str,
    deterministic_ok: bool,
    forbidden_present: list[str],
    out_dir: Path,
    model: str,
    fallback: str,
) -> tuple[bool, str, str]:
    from mobile_agent import prompts
    from mobile_agent.llm import VLM

    prompt = prompts.STATE_VERIFIER.format(
        goal=task.goal,
        expect=task.expect_text,
        expect_absent=task.expect_absent,
        ui=final_ui[:12000],
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if final_shot.exists():
        content.append(image_part(final_shot))
    vlm = VLM(models=(model, fallback), log_path=out_dir / "verifier_llm.jsonl")
    try:
        message = vlm.chat(
            [
                {"role": "system", "content": "You judge the FINAL observable state of an Android app."},
                {"role": "user", "content": content},
            ],
            max_tokens=450,
            temperature=1,
            purpose="state_verifier",
        )
        data = parse_json(message.content or "")
    except Exception as exc:  # noqa: BLE001
        return deterministic_ok, f"Verifier error: {exc!r}", ""
    if not data:
        return deterministic_ok, "Verifier output was not valid JSON; used deterministic check.", ""
    success = bool(data.get("success", False))
    reason = str(data.get("reason", "")).strip() or "No reason provided."
    evidence = str(data.get("evidence", "")).strip()
    if forbidden_present:
        success = False
        reason = f"Final UI contains forbidden text {forbidden_present}. " + reason
    return success, reason.strip(), evidence


def evaluate_task(task: Task, serial: str, out_dir: Path, model: str, fallback: str) -> dict[str, Any]:
    final_shot, final_ui = capture_final(serial, out_dir)
    ui_lower = final_ui.lower()
    missing = [text for text in task.expect_text if text.lower() not in ui_lower]
    forbidden = [text for text in task.expect_absent if text.lower() in ui_lower]
    deterministic_ok = not missing and not forbidden
    success, reason, evidence = verify_final_state(
        task, final_shot, final_ui, deterministic_ok, forbidden, out_dir, model, fallback
    )
    return {
        "success": success,
        "reason": reason,
        "evidence": evidence,
        "deterministic_ok": deterministic_ok,
        "missing_text": missing,
        "forbidden_text_present": forbidden,
    }


# ---------------------------------------------------------------- single-task child

def run_single_task(
    task: Task,
    serial: str,
    out_root: Path,
    model: str,
    fallback: str,
    ui_tars_model: str,
    no_reset: bool,
) -> dict[str, Any]:
    configure_env(ui_tars_model, model)
    from agentprog import AgentProgConfig, agentprog_pipeline
    from agentprog.all_utils.general_utils import InitResponseArgs

    out_dir = out_root / task.id
    out_dir.mkdir(parents=True, exist_ok=True)
    # The parent keeps console.log open in this directory; clean only the
    # artifacts this child owns.
    for name in (
        "llm_calls.jsonl",
        "agent.log",
        "workflow.ap",
        "final.png",
        "final.jpg",
        "final_ui.xml",
        "final_ui.txt",
        "verifier_llm.jsonl",
        "result.json",
        "error.txt",
    ):
        path = out_dir / name
        if path.exists():
            path.unlink()
    for name in ("images", "meta_info"):
        path = out_dir / name
        if path.exists():
            shutil.rmtree(path)

    if not no_reset:
        prepare_device(serial, task.app)
    capture_screenshot(serial, out_dir / "start.png")

    trace = ModelTrace(out_dir / "llm_calls.jsonl")
    install_ui_tars_trace(trace)

    response_args = InitResponseArgs(
        model=f"openai/{model}",
        base_url=MAGPIE,
        api_key="magpie",
        record_completion_statistics=True,
        completion_kwargs={"temperature": 1, "stream": False},
        use_sdk=True,
    )
    config = AgentProgConfig(
        task_description=task.goal,
        serial=serial,
        workflow_path=str(out_dir / "workflow.ap"),
        image_dir=str(out_dir / "images"),
        meta_info_dir=str(out_dir / "meta_info"),
        logging_path=str(out_dir / "agent.log"),
        show_dashboard=False,
        use_belief_state=True,
        cache_mode=False,
        workflow_model_args=response_args,
        executor_model_args=response_args,
    )
    config.get_workflow_response = trace.wrap(config.get_workflow_response, "workflow")
    config.get_executor_response = trace.wrap(config.get_executor_response, "executor")

    started = time.perf_counter()
    error = ""
    try:
        agentprog_pipeline(config)
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()
        (out_dir / "error.txt").write_text(error, encoding="utf-8")
    agent_seconds = round(time.perf_counter() - started, 2)

    result: dict[str, Any] = {
        "id": task.id,
        "app": task.app,
        "app_name": task.app_name,
        "goal": task.goal,
        "expect_text": task.expect_text,
        "expect_absent": task.expect_absent,
        "max_steps": task.max_steps,
        "agent": "AgentProg",
        "agent_seconds": agent_seconds,
        "error": error,
        "model_calls": trace.calls,
        "workflow_path": str(out_dir / "workflow.ap"),
        "images": sorted(str(path) for path in (out_dir / "images").glob("*.png")),
    }
    result.update(evaluate_task(task, serial, out_dir, model, fallback))
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


# ---------------------------------------------------------------- parent driver

def build_child_command(task: Task, args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single-task",
        task.id,
        "--out",
        str(args.out),
        "--serial",
        args.serial,
        "--model",
        args.model,
        "--fallback",
        args.fallback,
        "--ui-tars-model",
        args.ui_tars_model,
    ]
    if args.no_reset:
        command.append("--no-reset")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AgentProg on real-device benchmark tasks")
    parser.add_argument("--tasks", default="all", help="comma-separated task ids or 'all'")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "agentprog")
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--fallback", default=DEFAULT_FALLBACK)
    parser.add_argument("--ui-tars-model", default=DEFAULT_UITARS_MODEL)
    parser.add_argument("--per-task-timeout", type=int, default=1800)
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--single-task", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    tasks = load_tasks(ROOT / "benchmark" / "agent_tasks.yaml")
    by_id = {task.id: task for task in tasks}

    if args.single_task:
        task = by_id[args.single_task]
        result = run_single_task(
            task,
            args.serial,
            args.out,
            args.model,
            args.fallback,
            args.ui_tars_model,
            args.no_reset,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if not result["error"] else 1

    if args.tasks.strip().lower() == "all":
        selected = tasks
    else:
        wanted = [item.strip() for item in args.tasks.split(",") if item.strip()]
        selected = [by_id[item] for item in wanted if item in by_id]
        missing = [item for item in wanted if item not in by_id]
        if missing:
            print(f"unknown task ids: {missing}", file=sys.stderr)
            return 2

    args.out.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for task in selected:
        out_dir = args.out / task.id
        out_dir.mkdir(parents=True, exist_ok=True)
        console_path = out_dir / "console.log"
        print(f"=== {task.id} ===", flush=True)
        timed_out = False
        returncode: int | None = None
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        with console_path.open("w", encoding="utf-8") as console:
            try:
                completed = subprocess.run(
                    build_child_command(task, args),
                    stdout=console,
                    stderr=subprocess.STDOUT,
                    timeout=args.per_task_timeout,
                    env=child_env,
                )
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                console.write(f"\n[runner] task timed out after {args.per_task_timeout}s\n")
                console.flush()

        result_path = out_dir / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            # The child was killed mid-run, so it never wrote result.json. The
            # agent still left evidence behind: recover the call count and the
            # screenshots it captured before scoring the final screen, so a
            # timed-out task is not reported as "0 calls, no images".
            calls_path = out_dir / "llm_calls.jsonl"
            calls = 0
            if calls_path.exists():
                calls = sum(
                    1 for line in calls_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            images = sorted(str(p) for p in (out_dir / "images").glob("*.png"))
            result = {
                "id": task.id,
                "app": task.app,
                "app_name": task.app_name,
                "goal": task.goal,
                "expect_text": task.expect_text,
                "expect_absent": task.expect_absent,
                "max_steps": task.max_steps,
                "agent": "AgentProg",
                "error": "timed out" if timed_out else f"child exited with {returncode}",
                "model_calls": calls,
                "images": images,
            }
            result.update(evaluate_task(task, args.serial, out_dir, args.model, args.fallback))
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        result["timed_out"] = timed_out
        result["returncode"] = returncode
        summary.append(result)
        print(
            f"{task.id}: success={result.get('success')} "
            f"error={'yes' if result.get('error') else 'no'} "
            f"calls={result.get('model_calls')}",
            flush=True,
        )

    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {args.out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
