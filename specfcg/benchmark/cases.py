"""Benchmark manifests: apps, natural-language cases, and goals."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml


@dataclass
class AppSpec:
    name: str
    package: str
    apk_path: Path


@dataclass
class NLTestCase:
    id: str
    app: str
    text: str


@dataclass
class CompositionalGoal:
    id: str
    app: str
    text: str
    assertions: list[str] = field(default_factory=list)


def _yaml_files(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_dir():
        return sorted(
            [*path.glob("*.yaml"), *path.glob("*.yml")]
        )
    return [path]


def _iter_records(
    path: Path, key: str
) -> Iterator[tuple[Path, str, dict[str, Any]]]:
    for file in _yaml_files(path):
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            items: Any = raw
            file_app = ""
        elif isinstance(raw, dict):
            items = raw.get(key, [])
            if not isinstance(items, list):
                raise ValueError(
                    f"{file}: '{key}' must be a list"
                )
            file_app = str(raw.get("app") or "")
        else:
            raise ValueError(
                f"{file}: root must be a mapping or list"
            )
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{file}: entries must be mappings")
            yield file, file_app, item


def load_apps(path: Path) -> list[AppSpec]:
    apps: list[AppSpec] = []
    for file, _file_app, item in _iter_records(path, "apps"):
        name = str(item.get("name") or item.get("app") or "").strip()
        package = str(item.get("package") or "").strip()
        apk_path = str(item.get("apk_path") or "").strip()
        if not name or not package or not apk_path:
            raise ValueError(
                f"{file}: app needs name, package, and apk_path"
            )
        apps.append(
            AppSpec(
                name=name,
                package=package,
                apk_path=Path(apk_path),
            )
        )
    return apps


def load_cases(path: Path) -> list[NLTestCase]:
    cases: list[NLTestCase] = []
    for file, file_app, item in _iter_records(path, "cases"):
        case_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        app = str(item.get("app") or file_app or file.stem).strip()
        if not case_id or not text:
            raise ValueError(
                f"{file}: case needs id and text"
            )
        cases.append(
            NLTestCase(id=case_id, app=app, text=text)
        )
    return cases


def load_goals(path: Path) -> list[CompositionalGoal]:
    goals: list[CompositionalGoal] = []
    for file, file_app, item in _iter_records(path, "goals"):
        goal_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        app = str(item.get("app") or file_app or file.stem).strip()
        if not goal_id or not text:
            raise ValueError(
                f"{file}: goal needs id and text"
            )
        raw_assertions = item.get("assertions") or []
        if not isinstance(raw_assertions, list):
            raw_assertions = [raw_assertions]
        assertions = [
            str(value).strip()
            for value in raw_assertions
            if str(value).strip()
        ]
        goals.append(
            CompositionalGoal(
                id=goal_id,
                app=app,
                text=text,
                assertions=assertions,
            )
        )
    return goals
