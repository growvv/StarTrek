"""Stage-reporting summaries for benchmark runs."""

from __future__ import annotations

from typing import Any


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tasks = len(rows)
    success = sum(1 for row in rows if row.get("success"))
    failure_types: dict[str, int] = {}
    by_app: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.get("success"):
            key = str(row.get("failure_type") or "unknown")
            failure_types[key] = failure_types.get(key, 0) + 1
        app = str(row.get("app") or "")
        bucket = by_app.setdefault(
            app, {"tasks": 0, "success": 0, "failure_types": {}}
        )
        bucket["tasks"] += 1
        bucket["success"] += 1 if row.get("success") else 0
        if not row.get("success"):
            app_key = str(row.get("failure_type") or "unknown")
            bucket["failure_types"][app_key] = (
                bucket["failure_types"].get(app_key, 0) + 1
            )
    for bucket in by_app.values():
        bucket["success_rate"] = (
            round(bucket["success"] / bucket["tasks"], 3)
            if bucket["tasks"]
            else 0.0
        )
    return {
        "tasks": tasks,
        "success": success,
        "success_rate": round(success / tasks, 3) if tasks else 0.0,
        "failure_types": failure_types,
        "by_app": by_app,
        "mean_steps": _mean([float(row.get("steps", 0)) for row in rows]),
        "mean_predicted_confidence": _mean(
            [float(row.get("predicted_confidence", 0)) for row in rows]
        ),
    }
