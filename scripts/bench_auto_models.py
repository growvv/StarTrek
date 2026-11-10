#!/usr/bin/env python3
"""Speed benchmark of all auto/* text models on one real AgentProg request.

The request is taken verbatim from runs/repro_agentprog_readme/llm_calls.jsonl
(the workflow-generation call).  All models get the same messages, temperature
default, max_tokens=4000; requests run concurrently.

Run:
  PYTHONIOENCODING=utf-8 .venv-agentprog/Scripts/python scripts/bench_auto_models.py
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:3425/v1"
KEY = "magpie"


def list_models() -> list[str]:
    request = urllib.request.Request(
        f"{BASE}/models", headers={"Authorization": f"Bearer {KEY}"}
    )
    data = json.load(urllib.request.urlopen(request, timeout=30))["data"]
    models = []
    for item in data:
        model_id = item.get("id", "")
        if not model_id.startswith("auto/"):
            continue
        if "text" not in (item.get("modalities") or {}).get("input", []):
            continue
        models.append(model_id)
    return models


def run_one(client: Any, model: str, messages: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=False,
        )
        elapsed = round(time.perf_counter() - started, 2)
        choice = response.choices[0]
        message = choice.message
        usage = response.usage
        return {
            "model": model,
            "seconds": elapsed,
            "finish_reason": choice.finish_reason,
            "content": message.content or "",
            "reasoning": getattr(message, "reasoning_content", None) or "",
            "content_chars": len(message.content or ""),
            "reasoning_chars": len(getattr(message, "reasoning_content", None) or ""),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "model": model,
            "seconds": round(time.perf_counter() - started, 2),
            "error": repr(exc)[:300],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calls",
        type=Path,
        default=ROOT / "runs" / "repro_agentprog_readme" / "llm_calls.jsonl",
    )
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--models",
        default="",
        help="comma-separated subset; default: every auto/ text model",
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "runs" / "model_speed_bench.json"
    )
    args = parser.parse_args()

    from openai import OpenAI

    rows = [
        json.loads(line)
        for line in args.calls.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    messages = rows[args.index]["request"]
    models = (
        [name.strip() for name in args.models.split(",") if name.strip()]
        if args.models
        else list_models()
    )
    print(f"testing {len(models)} models on request #{args.index} "
          f"({len(json.dumps(messages, ensure_ascii=False))} chars)", flush=True)

    client = OpenAI(base_url=BASE, api_key=KEY, timeout=300)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_one, client, model, messages, args.max_tokens): model
            for model in models
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = (
                f"{result['seconds']}s"
                if "error" not in result
                else f"ERROR {result['error'][:80]}"
            )
            print(f"{result['model']}: {status}", flush=True)

    results.sort(key=lambda row: (row.get("error") is not None, row.get("seconds", 1e9)))
    args.out.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n== sorted by latency ==")
    for row in results:
        if "error" in row:
            print(f"{row['model']:<38} ERROR {row['error'][:100]}")
        else:
            print(
                f"{row['model']:<38} {row['seconds']:>7}s "
                f"finish={row['finish_reason']:<8} "
                f"out={row['completion_tokens']} tok "
                f"content={row['content_chars']} chars"
            )
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
