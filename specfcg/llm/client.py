"""LLM client protocol and OpenAI-compatible implementation."""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


class LLMParseError(Exception):
    """Raised when a model response cannot be parsed as the expected JSON."""


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str: ...

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        *,
        system: str | None = None,
    ) -> dict[str, Any]: ...


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model text.

    Handles bare JSON, fenced code blocks, and prose around an object. Raises
    LLMParseError for anything that does not yield a JSON object.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise LLMParseError(f"no JSON object found in response: {text!r}")
        try:
            value, _ = json.JSONDecoder().raw_decode(stripped[start:])
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"invalid JSON in response: {text!r}") from exc

    if not isinstance(value, dict):
        raise LLMParseError(f"response is not a JSON object: {text!r}")
    return value


class OpenAICompatibleClient:
    """Client for any OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client: Any = None

    def _sdk(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._sdk().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        full_prompt = (
            f"{prompt}\n\nReturn only a JSON object matching this shape:\n"
            f"{schema_hint}"
        )
        return extract_json_object(self.complete(full_prompt, system=system))
