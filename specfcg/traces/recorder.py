"""Trace recorder and JSON trace store."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from specfcg.models import Step, Trace

logger = logging.getLogger(__name__)


class TraceParseError(Exception):
    """Raised when a trace file is not valid trace JSON."""


def _trace_slug(trace_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", trace_id).strip("_")
    return slug or "trace"


def trace_to_dict(trace: Trace) -> dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "app": trace.app,
        "start_state": trace.start_state,
        "goal": trace.goal,
        "metadata": trace.metadata,
        "steps": [asdict(step) for step in trace.steps],
    }


def trace_from_dict(data: Any) -> Trace:
    if not isinstance(data, dict):
        raise TraceParseError("trace JSON must be an object")
    trace_id = data.get("trace_id")
    app = data.get("app")
    raw_steps = data.get("steps", [])
    if not isinstance(trace_id, str) or not trace_id:
        raise TraceParseError("trace_id must be a non-empty string")
    if not isinstance(app, str):
        raise TraceParseError("app must be a string")
    if not isinstance(raw_steps, list):
        raise TraceParseError("steps must be a list")

    steps: list[Step] = []
    for raw in raw_steps:
        if not isinstance(raw, dict) or "action" not in raw:
            raise TraceParseError("each step must be an object with an action")
        steps.append(
            Step(
                action=str(raw["action"]),
                target=str(raw.get("target", "")),
                args=str(raw.get("args", "")),
                before_state=str(raw.get("before_state", "")),
                after_state=str(raw.get("after_state", "")),
                success=bool(raw.get("success", True)),
            )
        )

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TraceParseError("metadata must be an object")
    return Trace(
        trace_id=trace_id,
        app=app,
        steps=steps,
        start_state=str(data.get("start_state", "")),
        goal=str(data.get("goal", "")),
        metadata=metadata,
    )


class TraceRecorder:
    """Accumulates steps for one in-progress trace."""

    def __init__(self, app: str, trace_id: str) -> None:
        self.app = app
        self.trace_id = trace_id
        self._steps: list[Step] = []

    def record(self, step: Step) -> None:
        self._steps.append(step)

    def trace(self) -> Trace:
        return Trace(
            trace_id=self.trace_id,
            app=self.app,
            steps=list(self._steps),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                trace_to_dict(self.trace()), indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )


class TraceStore:
    """JSON trace files under `<root>/traces/<trace_id>.json`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.traces_dir = self.root / "traces"

    def _path(self, trace_id: str) -> Path:
        return self.traces_dir / f"{_trace_slug(trace_id)}.json"

    def save(self, trace: Trace) -> Path:
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(trace.trace_id)
        path.write_text(
            json.dumps(trace_to_dict(trace), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def load(self, trace_id: str) -> Trace:
        path = self._path(trace_id)
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceParseError(f"cannot parse trace {path}: {exc}") from exc
        return trace_from_dict(data)

    def all(self) -> list[Trace]:
        traces: list[Trace] = []
        if not self.traces_dir.exists():
            return traces
        for path in sorted(self.traces_dir.glob("*.json")):
            try:
                traces.append(self.load(path.stem))
            except (TraceParseError, OSError) as exc:
                logger.warning("skipping malformed trace %s: %s", path, exc)
        return traces
