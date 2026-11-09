"""Run ProphetAgent and convert its Droidbot output into trace objects."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from specfcg.models import Step, Trace

PROPHETAGENT_COMMIT = "97667bfe109e71f57d84a2f7df9bcb03aba55b11"

_ACTION_MAP = {
    "touch": "click",
    "click": "click",
    "tap": "click",
    "text": "input",
    "set_text": "input",
    "input": "input",
    "swipe": "swipe",
    "scroll": "swipe",
    "back": "back",
    "key": "back",
    "press": "back",
    "wait": "wait",
    "sleep": "wait",
}


def _action(event: dict[str, Any]) -> str:
    raw = str(event.get("event_type") or "").strip().lower()
    if raw in {"click", "input", "swipe", "back", "wait"}:
        return raw
    return _ACTION_MAP.get(raw, "click")


def _target(event: dict[str, Any]) -> str:
    for key in ("view_str", "target", "event_str"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    view = event.get("view")
    if isinstance(view, dict):
        for key in ("text", "content_description", "resource_id"):
            value = view.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _args(event: dict[str, Any]) -> str:
    for key in ("event_text", "text", "args", "input"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _continues(
    previous: dict[str, Any], current: dict[str, Any]
) -> bool:
    from_state = str(current.get("from_state") or "").strip()
    previous_to = str(previous.get("to_state") or "").strip()
    if from_state and previous_to:
        return from_state == previous_to
    return not from_state and not previous_to


def _parse_events(
    raw_events: list[Any], app: str
) -> list[Trace]:
    groups: dict[str, list[tuple[dict[str, Any], Step]]] = {}
    previous_raw: dict[str, Any] | None = None
    last_key = ""
    chain_index = 0

    for raw in raw_events:
        if not isinstance(raw, dict):
            continue
        target = _target(raw)
        if not target:
            continue
        step = Step(
            action=_action(raw),
            target=target,
            args=_args(raw),
            before_state=str(raw.get("from_state") or ""),
            after_state=str(raw.get("to_state") or ""),
        )

        trace_id = raw.get("trace_id")
        if isinstance(trace_id, str) and trace_id.strip():
            key = f"trace:{trace_id.strip()}"
        elif previous_raw is not None and _continues(previous_raw, raw):
            key = last_key
        else:
            chain_index += 1
            key = f"chain:{chain_index}"

        groups.setdefault(key, []).append((raw, step))
        previous_raw = raw
        last_key = key

    traces: list[Trace] = []
    for index, items in enumerate(groups.values(), 1):
        first_raw = items[0][0]
        traces.append(
            Trace(
                trace_id=f"{app}-{index:03d}",
                app=app,
                steps=[step for _raw, step in items],
                start_state=str(first_raw.get("from_state") or ""),
                goal="",
                metadata={"source": "prophetagent"},
            )
        )
    return traces


def parse_droidbot_output(
    output_dir: Path, app: str
) -> list[Trace]:
    path = Path(output_dir) / "events.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(raw, dict):
        raw_events = raw.get("events", [])
    elif isinstance(raw, list):
        raw_events = raw
    else:
        return []
    if not isinstance(raw_events, list):
        return []
    return _parse_events(raw_events, app)


class ProphetAgentCollector:
    """Run ProphetAgent's Droidbot front end and parse its traces."""

    def __init__(
        self,
        repo_path: Path,
        output_root: Path,
        device_serial: str | None = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.output_root = Path(output_root)
        self.device_serial = device_serial

    def collect(
        self,
        app: str,
        apk_path: Path,
        policy: str = "greedy_dfs",
        count: int = 500,
        timeout_s: int = 600,
    ) -> list[Trace]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output_dir = self.output_root / f"{app}-{stamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            "start.py",
            "-a",
            str(apk_path),
            "-o",
            str(output_dir),
            "-policy",
            policy,
            "-count",
            str(count),
            "-timeout",
            str(timeout_s),
        ]
        env = dict(os.environ)
        if self.device_serial:
            env["ANDROID_SERIAL"] = self.device_serial
        subprocess.run(
            command,
            cwd=self.repo_path,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s + 60,
        )
        return parse_droidbot_output(output_dir, app)
