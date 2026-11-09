"""Disk cache wrapper for LLM clients."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from specfcg.llm.client import LLMClient


class CachedLLMClient:
    """Cache raw completions and JSON responses keyed by the full request."""

    def __init__(self, inner: LLMClient, cache_dir: Path) -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(
        method: str,
        prompt: str,
        system: str | None,
        temperature: float,
    ) -> str:
        payload = "\0".join(
            [method, prompt, system or "", str(temperature)]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _read(self, key: str) -> Any | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return envelope.get("value")

    def _write(self, key: str, value: Any) -> None:
        path = self.cache_dir / f"{key}.json"
        path.write_text(
            json.dumps({"value": value}, ensure_ascii=False),
            encoding="utf-8",
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        key = self._key("complete", prompt, system, temperature)
        cached = self._read(key)
        if cached is not None:
            return str(cached)
        result = self.inner.complete(
            prompt, system=system, temperature=temperature
        )
        self._write(key, result)
        return result

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        key = self._key(f"complete_json:{schema_hint}", prompt, system, 0.0)
        cached = self._read(key)
        if cached is not None:
            return cached
        result = self.inner.complete_json(
            prompt, schema_hint, system=system
        )
        self._write(key, result)
        return result
