#!/usr/bin/env python3
"""Probe whether GPT models expose reasoning under different request switches."""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:3425/v1"


def main() -> int:
    rows = [
        json.loads(line)
        for line in (ROOT / "runs/repro_agentprog_readme/llm_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    messages = rows[0]["request"]
    client = OpenAI(base_url=BASE, api_key="magpie", timeout=300)

    variants = {
        "default": {},
        "reasoning_effort=low": {"reasoning_effort": "low"},
        "reasoning_effort=high": {"reasoning_effort": "high"},
        "extra_body reasoning": {"extra_body": {"reasoning": {"effort": "low"}}},
        "extra_body thinking": {"extra_body": {"thinking": {"type": "enabled"}}},
    }
    results = []
    for model in ("auto/gpt-6-sol", "auto/gpt-5.6-sol"):
        for name, kwargs in variants.items():
            started = time.perf_counter()
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1200,
                    stream=False,
                    **kwargs,
                )
                elapsed = round(time.perf_counter() - started, 2)
                message = response.choices[0].message
                raw = message.model_dump()
                results.append(
                    {
                        "model": model,
                        "variant": name,
                        "seconds": elapsed,
                        "finish": response.choices[0].finish_reason,
                        "completion_tokens": response.usage.completion_tokens,
                        "keys": sorted(raw.keys()),
                        "reasoning_chars": len(raw.get("reasoning_content") or ""),
                        "content_chars": len(raw.get("content") or ""),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {"model": model, "variant": name, "error": repr(exc)[:200]}
                )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    out = ROOT / "runs" / "gpt_reasoning_probe.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
