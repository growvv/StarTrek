"""Task initialisation and final-state collection for benchmark runs.

Mirrors the two halves of AndroidWorld/MobileWorld task design:

* ``prepare_state`` is the ``initialize_task`` hook: reset the app, seed the
  files the task talks about, and remove stale artefacts.
* ``collect_final_state`` is the input to ``is_successful``: read back only
  what the oracle asks about, so the evaluation is cheap and cannot pass by
  inspecting unrelated state.

Device operations go through a small protocol so tests never touch adb.
"""

from __future__ import annotations

from typing import Protocol

from specfcg.benchmark.oracles import FinalState
from specfcg.benchmark.suite import BenchTask


class Ops(Protocol):
    def shell(self, command: str) -> str: ...

    def act(self, action: str, target: str, args: str = "") -> bool: ...

    def write_file(self, path: str, content: str) -> None: ...

    def remove(self, path: str) -> None: ...

    def read_file(self, path: str) -> str | None: ...

    def is_dir(self, path: str) -> bool: ...

    def dump_ui(self) -> str: ...

    def focused_package(self) -> str: ...

    def clear_app(self, package: str) -> None: ...

    def launch(self, package: str) -> None: ...


def _oracle_paths(oracle: dict) -> list[str]:
    paths: list[str] = []
    for key in ("fs_exists", "fs_absent", "fs_dir", "fs_not_dir"):
        value = oracle.get(key) or []
        if isinstance(value, str):
            value = [value]
        paths.extend(str(item) for item in value)
    content = oracle.get("fs_content") or {}
    if isinstance(content, dict):
        paths.extend(str(path) for path in content)
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def run_onboarding(ops: Ops, onboarding: list[dict]) -> None:
    """Walk the app past its first-run screens.

    This is part of ``initialize_task`` in AndroidWorld and MobileWorld: every
    episode starts from the same post-onboarding state.
    """
    for step in onboarding:
        ops.act(
            str(step.get("action", "")),
            str(step.get("target", "")),
            str(step.get("args", "")),
        )


def fresh_app(
    ops: Ops, package: str, onboarding: list[dict] | None = None
) -> None:
    """Reset and launch an app, then run its onboarding.

    The random-traversal baseline and the coverage probes have no task to
    prepare, but they must still start from the same state a task does --
    otherwise they measure the first-run wizard instead of the app.
    """
    ops.clear_app(package)
    ops.launch(package)
    run_onboarding(ops, list(onboarding or []))


def prepare_state(ops: Ops, task: BenchTask) -> None:
    init = task.init or {}
    if init.get("clear_app"):
        ops.clear_app(task.package)
    for path, content in (init.get("seed_files") or {}).items():
        ops.write_file(str(path), str(content))
    for path in init.get("seed_dirs") or []:
        ops.shell(f"mkdir -p {path}")
        if hasattr(ops, "dirs") and isinstance(getattr(ops, "dirs"), set):
            ops.dirs.add(str(path))
    for path in init.get("remove_paths") or []:
        ops.remove(str(path))
    ops.launch(task.package)
    # Onboarding is part of task initialisation, like AndroidWorld's
    # ``initialize_task``: it gets the app past its first-run screens so the
    # agent starts from the same state for every episode.
    run_onboarding(ops, task.onboarding)


def collect_final_state(ops: Ops, oracle: dict) -> FinalState:
    state = FinalState(
        ui_text=ops.dump_ui(),
        focused_package=ops.focused_package(),
    )
    for path in _oracle_paths(oracle):
        try:
            state.files[path] = ops.read_file(path)
        except Exception:  # a dead adb must not crash the oracle
            state.files[path] = None
        try:
            if ops.is_dir(path):
                state.dirs.add(path)
        except Exception:
            pass
    return state
