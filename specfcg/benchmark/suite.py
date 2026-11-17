"""AndroidWorld/MobileWorld-style benchmark suite manifests.

A task is a goal template plus parameters, a task complexity, optional app
state initialisation, and a programmatic final-state oracle.  The design
follows AndroidWorld's ``TaskEval`` (``template`` + ``params`` -> ``goal``,
``complexity``, ``initialize_task``, ``is_successful``) and MobileWorld's
``BaseTask`` (``goal``, ``app_names``, ``is_successful``), adapted to YAML so
the suite can be reviewed without reading Python.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MAX_STEPS_CAP = 20

ORACLE_KEYS = frozenset(
    {
        "ui_all",
        "ui_any",
        "ui_absent",
        "focus_package",
        "fs_exists",
        "fs_absent",
        "fs_dir",
        "fs_not_dir",
        "fs_content",
    }
)


@dataclass
class BenchTask:
    id: str
    app: str
    package: str
    template: str
    params: dict[str, Any] = field(default_factory=dict)
    complexity: float = 1.0
    tags: list[str] = field(default_factory=list)
    init: dict[str, Any] = field(default_factory=dict)
    onboarding: list[dict[str, Any]] = field(default_factory=list)
    oracle: dict[str, Any] = field(default_factory=dict)
    max_steps: int = MAX_STEPS_CAP

    @property
    def goal(self) -> str:
        names = [
            name
            for _literal, name, _spec, _conv in string.Formatter().parse(
                self.template
            )
            if name
        ]
        missing = [name for name in names if name not in self.params]
        if missing:
            raise ValueError(
                f"{self.id}: template needs parameter(s) {missing}"
            )
        return self.template.format(**self.params)

    @property
    def budget(self) -> int:
        """Step budget: AndroidWorld scales with complexity, capped at 20."""
        return min(MAX_STEPS_CAP, max(1, int(round(self.complexity * 10))))


@dataclass
class AppSuite:
    app: str
    package: str
    source: str
    tasks: list[BenchTask] = field(default_factory=list)


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    raise ValueError(f"expected a string or list, got {type(value).__name__}")


def _task(
    item: dict[str, Any],
    app: str,
    package: str,
    file: Path,
    app_onboarding: list[Any] | None = None,
) -> BenchTask:
    task_id = str(item.get("id") or "").strip()
    template = str(item.get("template") or item.get("goal") or "").strip()
    if not task_id or not template:
        raise ValueError(f"{file}: task needs id and template")
    params = item.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"{file}: {task_id} params must be a mapping")
    oracle = item.get("oracle") or {}
    if not isinstance(oracle, dict) or not oracle:
        raise ValueError(f"{file}: {task_id} needs an oracle")
    unknown = sorted(set(oracle) - ORACLE_KEYS)
    if unknown:
        raise ValueError(
            f"{file}: {task_id} has unknown oracle key(s) {unknown}"
        )
    max_steps = int(item.get("max_steps", MAX_STEPS_CAP))
    if max_steps > MAX_STEPS_CAP:
        raise ValueError(
            f"{file}: {task_id} max_steps={max_steps} exceeds the "
            f"{MAX_STEPS_CAP}-step cap"
        )
    init = item.get("init") or {}
    if not isinstance(init, dict):
        raise ValueError(f"{file}: {task_id} init must be a mapping")
    onboarding = item.get("onboarding")
    if onboarding is None:
        onboarding = list(app_onboarding or [])
    if not isinstance(onboarding, list):
        raise ValueError(
            f"{file}: {task_id} onboarding must be a list of actions"
        )
    task = BenchTask(
        id=task_id,
        app=app,
        package=package,
        template=template,
        params=params,
        complexity=float(item.get("complexity", 1.0)),
        tags=_list(item.get("tags")),
        init=init,
        onboarding=onboarding,
        oracle=oracle,
        max_steps=max_steps,
    )
    task.goal  # fail early on a missing template parameter
    return task


def load_suite(path: Path) -> list[AppSuite]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    entries = raw.get("apps")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'apps' must be a list")
    suites: list[AppSuite] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: app entries must be mappings")
        app = str(entry.get("name") or "").strip()
        package = str(entry.get("package") or "").strip()
        if not app or not package:
            raise ValueError(f"{path}: app needs name and package")
        tasks_raw = entry.get("tasks") or []
        if not isinstance(tasks_raw, list):
            raise ValueError(f"{path}: {app} tasks must be a list")
        app_onboarding = entry.get("onboarding") or []
        if not isinstance(app_onboarding, list):
            raise ValueError(f"{path}: {app} onboarding must be a list")
        tasks = [
            _task(item, app, package, path, app_onboarding)
            for item in tasks_raw
            if isinstance(item, dict)
        ]
        suites.append(
            AppSuite(
                app=app,
                package=package,
                source=str(entry.get("source") or "").strip(),
                tasks=tasks,
            )
        )
    return suites
