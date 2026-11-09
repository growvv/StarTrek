"""Test doubles shared across the suite."""

from __future__ import annotations

import json
from typing import Any

from specfcg.llm.client import LLMParseError


class FakeLLMClient:
    """A scripted LLM client: each call pops the next canned response."""

    def __init__(self, responses: list[str | dict[str, Any]] | None = None) -> None:
        self.responses: list[str | dict[str, Any]] = list(responses or [])
        self.calls = 0

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeLLMClient has no responses left")
        response = self.responses.pop(0)
        if isinstance(response, str):
            return response
        return json.dumps(response)

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        raw = self.complete(prompt, system=system)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"response is not valid JSON: {raw!r}") from exc
        if not isinstance(parsed, dict):
            raise LLMParseError(f"response is not a JSON object: {raw!r}")
        return parsed
