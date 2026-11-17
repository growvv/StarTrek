"""Programmatic final-state oracles in the style of AndroidWorld/MobileWorld.

Oracles are evaluated after the agent stops, against the final observable
state only: the final UI hierarchy (text and focused package) and, where the
task is about a file the user can see in the app, the file system.  No
intermediate action or navigation path is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FinalState:
    ui_text: str = ""
    ui_xml: str = ""
    focused_package: str = ""
    files: dict[str, str | None] = field(default_factory=dict)
    dirs: set[str] = field(default_factory=set)


@dataclass
class OracleResult:
    success: bool
    reason: str
    evidence: str


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def evaluate_oracle(
    oracle: dict[str, Any], state: FinalState
) -> OracleResult:
    checks: list[tuple[str, bool, str]] = []
    text = state.ui_text or ""

    for needle in _as_list(oracle.get("ui_all")):
        checks.append(
            (
                "ui_all",
                _contains(text, needle),
                f"ui contains {needle!r}",
            )
        )

    any_values = _as_list(oracle.get("ui_any"))
    if any_values:
        hit = next(
            (value for value in any_values if _contains(text, value)),
            None,
        )
        checks.append(
            (
                "ui_any",
                hit is not None,
                f"ui contains one of {any_values!r} (hit={hit!r})",
            )
        )

    for needle in _as_list(oracle.get("ui_absent")):
        checks.append(
            (
                "ui_absent",
                not _contains(text, needle),
                f"ui does not contain {needle!r}",
            )
        )

    focus = str(oracle.get("focus_package") or "").strip()
    if focus:
        checks.append(
            (
                "focus_package",
                focus.casefold() in (state.focused_package or "").casefold(),
                f"focused package contains {focus!r} "
                f"(got {state.focused_package!r})",
            )
        )

    for path in _as_list(oracle.get("fs_exists")):
        checks.append(
            (
                "fs_exists",
                state.files.get(path) is not None,
                f"{path} exists",
            )
        )

    for path in _as_list(oracle.get("fs_absent")):
        checks.append(
            (
                "fs_absent",
                state.files.get(path) is None and path not in state.dirs,
                f"{path} is absent",
            )
        )

    for path in _as_list(oracle.get("fs_dir")):
        checks.append(
            ("fs_dir", path in state.dirs, f"{path} is a directory")
        )

    for path in _as_list(oracle.get("fs_not_dir")):
        checks.append(
            (
                "fs_not_dir",
                path not in state.dirs and state.files.get(path) is not None,
                f"{path} is a file",
            )
        )

    content = oracle.get("fs_content") or {}
    if isinstance(content, dict):
        for path, needles in content.items():
            body = state.files.get(str(path))
            for needle in _as_list(needles):
                checks.append(
                    (
                        "fs_content",
                        body is not None and _contains(body, str(needle)),
                        f"{path} contains {needle!r}",
                    )
                )

    failed = [line for _name, ok, line in checks if not ok]
    evidence = "\n".join(
        f"{'PASS' if ok else 'FAIL'} {name}: {line}"
        for name, ok, line in checks
    )
    if failed:
        return OracleResult(
            success=False,
            reason="; ".join(failed[:4]) or "oracle failed",
            evidence=evidence,
        )
    return OracleResult(
        success=True, reason="all oracle checks passed", evidence=evidence
    )
