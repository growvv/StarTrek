"""The function list each dataset build's own graph records.

FuncDroid publishes, per build, the functional graph its tool built: one entry
per function with a description, the pages it touches, and the data it reads
and writes.  That list is the closest thing the dataset has to a statement of
"what this build can do", and it is what a coverage number needs a denominator
for.

**It is also an answer key.**  The list was produced by the tool this work is
compared against, so scoring our graph's coverage against it measures how
closely two tools name the same functions — not whether our graph covers the
app.  `FunctionInventory.is_answer_key` is True for this source, and the
report must say so wherever the number appears.  The honest use is as a
reference for scale ("this build's own graph names 76 functions"), never as
the denominator of a claim that our graph covers 90% of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InventoryFunction:
    """One function a build's graph names."""

    id: str
    description: str = ""
    data_in: list[str] = field(default_factory=list)
    data_out: list[str] = field(default_factory=list)
    to_test: bool = True
    entry_page: str = ""


@dataclass
class FunctionInventory:
    """A build's function list, and where it came from."""

    version_id: str
    functions: list[InventoryFunction] = field(default_factory=list)
    source: str = ""
    is_answer_key: bool = False

    @property
    def total(self) -> int:
        return len([f for f in self.functions if f.to_test])

    def as_record(self) -> dict:
        return {
            "version": self.version_id,
            "source": self.source,
            "is_answer_key": self.is_answer_key,
            "functions": self.total,
        }


def _list(value) -> list[str]:
    """Read a field that may be a list or its string form.

    The dataset stores some fields as Python literals (`"['notes']"`) rather
    than JSON, because they were written by `str()` on a list.  `ast.literal_eval`
    reads both spellings without executing anything.
    """
    import ast

    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if not isinstance(value, str) or value.strip() in {"", "[]"}:
        return []
    for reader in (ast.literal_eval, json.loads):
        try:
            parsed = reader(value)
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue
        if isinstance(parsed, list):
            return [str(v) for v in parsed if str(v).strip()]
    return [value]


def load_inventory(version_dir: Path) -> FunctionInventory | None:
    """Read a build's `fdg.json`, or None when it has none.

    A directory without the file carries no function list; returning an empty
    inventory would make the build look like it has zero functions, which
    would then divide by zero in a coverage score.
    """
    version_dir = Path(version_dir)
    path = version_dir / "fdg.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = data.get("FDG")
    if not isinstance(entries, list):
        return None

    functions: list[InventoryFunction] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        description = str(entry.get("function_description") or "").strip()
        if not description:
            continue
        logic = entry.get("core_logic") or {}
        entry_page = ""
        if isinstance(logic, dict):
            entry_page = str(logic.get("entry_page") or "")
        functions.append(
            InventoryFunction(
                id=str(entry.get("index", index)),
                description=description,
                data_in=_list(entry.get("data_in")),
                data_out=_list(entry.get("data_out")),
                to_test=bool(entry.get("to_test", True)),
                entry_page=entry_page,
            )
        )
    return FunctionInventory(
        version_id=version_dir.name,
        functions=functions,
        source="funcDroid fdg.json (the compared tool's own graph)",
        is_answer_key=True,
    )


def scale_summary(root: Path) -> dict:
    """How many builds have a function list, and how large they are."""
    root = Path(root)
    inventories = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        inventory = load_inventory(entry)
        if inventory is not None:
            inventories.append(inventory)
    return {
        "builds": len(inventories),
        "functions": sum(i.total for i in inventories),
        "answer_key": all(i.is_answer_key for i in inventories) if inventories else False,
        "per_build": {
            i.version_id: i.total for i in inventories
        },
    }
