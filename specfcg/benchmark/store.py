"""Latest-only record store for benchmark runs.

Repeated measurements of the same task replace older ones, as requested:
the file always holds the newest record per task and no redundant copies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class LatestStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def update(self, key: str, record: dict[str, Any]) -> None:
        data = self.load()
        data[key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
