"""OpenAI-compatible vision LLM wrapper with request logging."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    parts.append({"type": "image_url", "bytes": len(url)})
                else:
                    parts.append(part)
            clean.append({**message, "content": parts})
        else:
            clean.append(message)
    return clean


class VLM:
    def __init__(
        self,
        models: tuple[str, ...] = ("auto/gpt-6-luna", "auto/glm-5.3-flash"),
        base_url: str = "http://127.0.0.1:3425/v1",
        api_key: str = "magpie",
        log_path: Path | None = None,
    ) -> None:
        from openai import OpenAI

        self.models = models
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=180)
        self.log_path = log_path
        self.calls = 0
        self.seconds = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.0,
        purpose: str = "",
    ) -> Any:
        last_error: Exception | None = None
        for model in self.models:
            started = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                response = self.client.chat.completions.create(**kwargs)
                elapsed = time.perf_counter() - started
                self.calls += 1
                self.seconds += elapsed
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.prompt_tokens += usage.prompt_tokens or 0
                    self.completion_tokens += usage.completion_tokens or 0
                message = response.choices[0].message
                self._log(
                    {
                        "purpose": purpose,
                        "model": model,
                        "seconds": round(elapsed, 2),
                        "messages": _sanitize(messages),
                        "content": message.content,
                        "tool_calls": [
                            {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            }
                            for call in (message.tool_calls or [])
                        ],
                        "usage": (
                            {
                                "prompt": usage.prompt_tokens,
                                "completion": usage.completion_tokens,
                            }
                            if usage
                            else None
                        ),
                    }
                )
                return message
            except Exception as exc:
                last_error = exc
                self._log(
                    {
                        "purpose": purpose,
                        "model": model,
                        "seconds": round(time.perf_counter() - started, 2),
                        "error": repr(exc)[:500],
                    }
                )
                time.sleep(1.5)
        raise RuntimeError(f"all models failed: {last_error!r}")

    def _log(self, entry: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
