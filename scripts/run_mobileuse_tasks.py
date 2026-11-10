#!/usr/bin/env python3
"""Thin task runner + final-state evaluator around the open-source mobile-use agent.

The agent itself is third_party/mobile-use (Apache-2.0, minitap-ai).  This
script only:
  - resets/launches the app and keeps the device awake,
  - invokes mobile-use's own SDK (no policy/action code is reimplemented),
  - keeps mobile-use's real per-step trace screenshots and model I/O,
  - scores the FINAL observable state (not intermediate process evidence).

Success rule: the final screen must show the end state asked for by the goal,
or an unambiguous consequence of it.  Hidden database state and the exact
navigation path are not required.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MOBILEUSE = ROOT / "third_party" / "mobile-use"

# Must be set before importing minitap.mobile_use.config.
os.environ.setdefault("OPENAI_API_KEY", "magpie")
os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:3425/v1")
os.environ.setdefault("MOBILE_USE_TELEMETRY_ENABLED", "false")
os.environ.setdefault("MOBILE_USE_KEEP_TRACE_IMAGES", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MOBILEUSE))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from minitap.mobile_use.config import initialize_llm_config  # noqa: E402
from minitap.mobile_use.context import DevicePlatform  # noqa: E402
from minitap.mobile_use.sdk import Agent  # noqa: E402
from minitap.mobile_use.sdk.builders import Builders  # noqa: E402
from minitap.mobile_use.sdk.types.task import AgentProfile  # noqa: E402
from mobile_agent import prompts  # noqa: E402
from mobile_agent.llm import VLM  # noqa: E402


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
            goal=str(item["goal"]).strip(),
            expect_text=list(item.get("expect_text") or []),
            expect_absent=list(item.get("expect_absent") or []),
            max_steps=int(item.get("max_steps", 25)),
        )
        for item in data.get("tasks", [])
    ]


def adb(serial: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


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
    adb(
        serial, "shell", "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    time.sleep(2.5)


def dump_ui(serial: str, out_path: Path) -> str:
    """Capture the final UI hierarchy with a short retry, then fall back to adb."""
    last_error: Exception | None = None
    try:
        import uiautomator2 as u2

        for _ in range(3):
            try:
                device = u2.connect(serial)
                xml = device.dump_hierarchy()
                if xml and "<hierarchy" in xml:
                    out_path.write_text(xml, encoding="utf-8")
                    return xml
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(1.5)
    except Exception as exc:  # noqa: BLE001
        last_error = exc
    try:
        adb(serial, "shell", "uiautomator", "dump", "/sdcard/final_ui.xml", timeout=30)
        result = adb(serial, "exec-out", "cat", "/sdcard/final_ui.xml", timeout=30)
        if result.stdout and "<hierarchy" in result.stdout:
            out_path.write_text(result.stdout, encoding="utf-8")
            return result.stdout
    except Exception as exc:  # noqa: BLE001
        last_error = exc
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


def current_focus(serial: str) -> str:
    result = adb(serial, "shell", "dumpsys", "window")
    for line in (result.stdout or "").splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            return line.strip()
    return ""


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


def parse_tool_calls(stdout: str) -> list[dict[str, Any]]:
    """Parse mobile-use's own executor tool-call log lines, in order."""
    calls: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        success = "Tool call succeeded:" in line
        failed = "Tool call failed:" in line
        if not (success or failed):
            continue
        _, _, raw = line.partition("Tool call succeeded:" if success else "Tool call failed:")
        raw = raw.strip()
        try:
            data = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            calls.append({"raw": raw[:2000], "success": success})
            continue
        if not isinstance(data, dict):
            calls.append({"raw": raw[:2000], "success": success})
            continue
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        args = {key: value for key, value in args.items() if key != "state"}
        calls.append(
            {
                "name": str(data.get("name", "")),
                "args": args,
                "success": success,
                "raw": raw[:2000],
            }
        )
    return calls


def parse_trace(trace_dir: Path, out_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """Read mobile-use's per-step trace (JPEG + thought JSON) into a report form."""
    steps_path = trace_dir / "steps.json"
    if not steps_path.exists():
        return [], ""
    try:
        rows = json.loads(steps_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], ""
    normalized: list[dict[str, Any]] = []
    images_dir = out_dir / "trace_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, 1):
        timestamp = int(row.get("timestamp", 0))
        data_raw = row.get("data", "")
        thought = ""
        try:
            message = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            content = message.get("content", "") if isinstance(message, dict) else str(message)
            if isinstance(content, str) and content.startswith("["):
                try:
                    content = ast.literal_eval(content)
                except (ValueError, SyntaxError):
                    pass
            if isinstance(content, list):
                thought = "\n".join(str(item) for item in content)
            else:
                thought = str(content)
        except json.JSONDecodeError:
            thought = str(data_raw)
        source = trace_dir / f"{timestamp}.jpeg"
        target = images_dir / f"{index:03d}.jpg"
        screenshot = ""
        if source.exists():
            shutil.copy2(source, target)
            screenshot = str(target.relative_to(out_dir)).replace("\\", "/")
        normalized.append(
            {
                "step": index,
                "timestamp": timestamp,
                "thought": thought.strip(),
                "screenshot": screenshot,
            }
        )
    return normalized, str(steps_path.parent)


class LLMTraceCallback(BaseCallbackHandler):
    """Record real LangChain model requests/responses for the acceptance report.

    Base64 screenshots are replaced by a byte count so the log stays readable.
    This is instrumentation only; it does not alter agent behavior.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0
        self._lock = threading.Lock()

    def _write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _content(content: Any, limit: int = 6000) -> Any:
        if isinstance(content, str):
            return content[:limit]
        if isinstance(content, list):
            parts: list[Any] = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        parts.append({"type": "image_url", "omitted_bytes": len(url)})
                    else:
                        parts.append({**part, "text": str(part.get("text", ""))[:limit]})
                else:
                    parts.append(str(part)[:limit])
            return parts
        return str(content)[:limit]

    @classmethod
    def _message(cls, message: Any) -> dict[str, Any]:
        return {
            "type": getattr(message, "type", type(message).__name__),
            "content": cls._content(getattr(message, "content", "")),
            "tool_calls": [
                {
                    "name": call.get("name", ""),
                    "args": {
                        key: value
                        for key, value in (call.get("args") or {}).items()
                        if key != "state"
                    },
                }
                for call in (getattr(message, "tool_calls", None) or [])
            ],
        }

    def on_chat_model_start(self, serialized, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        flat = messages[0] if messages and isinstance(messages[0], list) else messages
        kwargs_dict = (serialized or {}).get("kwargs", {}) if isinstance(serialized, dict) else {}
        tools = kwargs_dict.get("tools") or []
        tool_names = [
            tool.get("function", {}).get("name") or tool.get("name")
            for tool in tools
            if isinstance(tool, dict)
        ]
        self._write(
            {
                "event": "request",
                "call": self.calls,
                "model": (
                    kwargs_dict.get("model")
                    or kwargs_dict.get("model_name")
                    or (serialized or {}).get("name", "")
                ),
                "tool_names": tool_names,
                "messages": [self._message(message) for message in flat],
            }
        )

    def on_llm_end(self, response, **kwargs):  # noqa: ANN001
        generations = getattr(response, "generations", None) or []
        first = generations[0][0] if generations and generations[0] else None
        message = getattr(first, "message", None)
        content = getattr(message, "content", None)
        if content is None:
            content = getattr(first, "text", "")
        usage = getattr(message, "usage_metadata", None) or {}
        self._write(
            {
                "event": "response",
                "call": self.calls,
                "content": self._content(content, limit=12000),
                "tool_calls": [
                    {
                        "name": call.get("name", ""),
                        "args": {
                            key: value
                            for key, value in (call.get("args") or {}).items()
                            if key != "state"
                        },
                    }
                    for call in (getattr(message, "tool_calls", None) or [])
                ],
                "usage": {
                    "input": usage.get("input_tokens"),
                    "output": usage.get("output_tokens"),
                },
            }
        )


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
        reason = (
            f"Final UI contains forbidden text {forbidden_present}. " + reason
        ).strip()
    return success, reason, evidence


async def run_task(
    task: Task,
    serial: str,
    out_root: Path,
    verifier_model: str,
    verifier_fallback: str,
    timeout: int,
    no_reset: bool,
) -> dict[str, Any]:
    out_dir = out_root / task.id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    error = ""
    agent_seconds = 0.0
    agent_content: Any = None
    trace_dir: Path | None = None

    if not no_reset:
        prepare_device(serial, task.app)

    # mobile-use's max_steps is a LangGraph recursion limit (graph nodes, not
    # taps).  Budget ~10 nodes per intended action, bounded for runtime.
    recursion_limit = min(450, max(120, int(task.max_steps) * 10))

    callback = LLMTraceCallback(out_dir / "llm_calls.jsonl")
    action_log = out_dir / "actions.log"
    action_handler = logging.FileHandler(action_log, encoding="utf-8")
    action_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    tool_logger = logging.getLogger("minitap.mobile_use.agents.executor.tool_node")
    tool_logger.addHandler(action_handler)

    llm_config = initialize_llm_config()
    profile = AgentProfile(name="default", llm_config=llm_config)
    config = (
        Builders.AgentConfig.with_default_profile(profile=profile)
        .for_device(DevicePlatform.ANDROID, serial)
        .with_graph_config_callbacks([callback])
        .build()
    )

    agent = Agent(config=config)
    agent_started = time.perf_counter()
    try:
        await agent.init(
            retry_count=int(os.getenv("MOBILE_USE_HEALTH_RETRIES", "4")),
            retry_wait_seconds=int(os.getenv("MOBILE_USE_HEALTH_DELAY", "2")),
        )
        request = (
            agent.new_task(task.goal)
            .with_name(task.id)
            .with_max_steps(recursion_limit)
            .with_trace_recording(path=str(out_dir / "traces"))
            .with_thoughts_output_saving(path=str(out_dir / "thoughts.json"))
            .with_llm_output_saving(path=str(out_dir / "llm_result.json"))
            .build()
        )
        try:
            agent_content = await asyncio.wait_for(
                agent.run_task(request=request), timeout=timeout
            )
        except asyncio.TimeoutError:
            error = f"mobile-use timeout after {timeout}s"
            try:
                agent.stop_current_task()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    finally:
        agent_seconds = round(time.perf_counter() - agent_started, 1)
        tool_logger.removeHandler(action_handler)
        action_handler.close()

    final_shot = out_dir / "final.png"
    final_ui_path = out_dir / "final_ui.xml"
    final_ui = ""
    focus = ""
    try:
        final_ui = dump_ui(serial, final_ui_path)
        focus = current_focus(serial)
        if agent._initialized:  # noqa: SLF001
            image = await agent.get_screenshot()
            image.save(final_shot)
    except Exception as exc:  # noqa: BLE001
        error = (error + f"; final capture error: {exc!r}").strip("; ")
    try:
        await agent.clean()
    except Exception as exc:  # noqa: BLE001
        error = (error + f"; clean error: {exc!r}").strip("; ")

    (out_dir / "agent_stdout.log").write_text(
        json.dumps(
            {
                "note": "mobile-use logs go to stdout/stderr; this runner captures "
                        "the SDK return value and trace instead.",
                "return_value": str(agent_content)[:20000],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    traces_root = out_dir / "traces"
    candidates = [
        path for path in traces_root.glob(f"{task.id}_*") if path.is_dir()
    ] if traces_root.exists() else []
    if candidates:
        trace_dir = max(candidates, key=lambda path: path.stat().st_mtime)
    steps: list[dict[str, Any]] = []
    trace_path = ""
    if trace_dir is not None:
        steps, trace_path = parse_trace(trace_dir, out_dir)
    trace_status = ""
    if trace_dir is not None:
        if "_PASS_" in trace_dir.name:
            trace_status = "PASS"
        elif "_FAIL_" in trace_dir.name:
            trace_status = "FAIL"

    actions: list[dict[str, Any]] = []
    if action_log.exists():
        actions = parse_tool_calls(action_log.read_text(encoding="utf-8", errors="replace"))
    (out_dir / "actions.json").write_text(
        json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ui = ui_text(final_ui)
    (out_dir / "final_ui.txt").write_text(ui, encoding="utf-8")
    ui_lower = ui.lower()
    missing_text = [text for text in task.expect_text if text.lower() not in ui_lower]
    forbidden_present = [text for text in task.expect_absent if text.lower() in ui_lower]
    deterministic_ok = not missing_text and not forbidden_present

    vlm_success, reason, evidence = verify_final_state(
        task,
        final_shot,
        ui,
        deterministic_ok,
        forbidden_present,
        out_dir,
        verifier_model,
        verifier_fallback,
    )
    success = bool(vlm_success and not forbidden_present)
    elapsed = round(time.perf_counter() - started, 1)
    result = {
        "id": task.id,
        "goal": task.goal,
        "app": task.app,
        "app_name": task.app_name,
        "success": success,
        "rule": "final_state_v1",
        "vlm_success": vlm_success,
        "deterministic_ok": deterministic_ok,
        "missing_text": missing_text,
        "forbidden_text_present": forbidden_present,
        "reason": reason,
        "evidence": evidence,
        "agent_trace_status": trace_status,
        "steps": len(steps),
        "actions": len(actions),
        "agent_seconds": agent_seconds,
        "elapsed_s": elapsed,
        "recursion_limit": recursion_limit,
        "intended_max_steps": task.max_steps,
        "model": "auto/gpt-6.1-sol",
        "verifier_model": verifier_model,
        "final_focus": focus,
        "trace_dir": trace_path,
        "error": error,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out_root / "summary.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-mobileuse-tasks")
    parser.add_argument("--tasks", default="benchmark/agent_tasks.yaml")
    parser.add_argument("--out", default="runs/mobileuse")
    parser.add_argument("--serial", default="47261FDAS00DTQ")
    parser.add_argument("--only", default="")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--verifier-model", default="auto/gpt-6.1-sol")
    parser.add_argument("--verifier-fallback", default="auto/gpt-6-luna")
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
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.id}: {task.goal[:110]}")
        result = asyncio.run(
            run_task(
                task,
                args.serial,
                out_root,
                args.verifier_model,
                args.verifier_fallback,
                args.timeout,
                args.no_reset,
            )
        )
        print(
            f"    success={result['success']} trace={result['agent_trace_status']} "
            f"steps={result['steps']} agent={result['agent_seconds']}s "
            f"total={result['elapsed_s']}s reason={result['reason'][:160]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
