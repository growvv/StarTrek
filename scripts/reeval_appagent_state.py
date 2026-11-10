#!/usr/bin/env python3
"""Re-score the completed AppAgent runs with the new FINAL-STATE rule.

This does not rerun the agent and does not change its old strict results.  It
only applies the same final-state verifier used for the mobile-use baseline to
the AppAgent final screenshot + final UI text, so the two agents can be
compared under one rule.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mobile_agent import prompts  # noqa: E402
from mobile_agent.llm import VLM  # noqa: E402


def image_part(path: Path) -> dict:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + data},
    }


def parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```[a-zA-Z]*", "", text.strip())
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def main() -> int:
    tasks = yaml.safe_load(
        (ROOT / "benchmark" / "agent_tasks.yaml").read_text(encoding="utf-8")
    )["tasks"]
    rows = []
    for item in tasks:
        task_id = str(item["id"])
        run_dir = ROOT / "runs" / "appagent" / task_id
        final_shot = run_dir / "final.jpg"
        final_ui = (run_dir / "final_ui.txt").read_text(encoding="utf-8", errors="replace") \
            if (run_dir / "final_ui.txt").exists() else ""
        expect = [str(text) for text in (item.get("expect_text") or [])]
        absent = [str(text) for text in (item.get("expect_absent") or [])]
        ui_lower = final_ui.lower()
        missing = [text for text in expect if text.lower() not in ui_lower]
        forbidden = [text for text in absent if text.lower() in ui_lower]
        deterministic_ok = not missing and not forbidden
        prompt = prompts.STATE_VERIFIER.format(
            goal=str(item["goal"]).strip(),
            expect=expect,
            expect_absent=absent,
            ui=final_ui[:12000],
        )
        content = [{"type": "text", "text": prompt}]
        if final_shot.exists():
            content.append(image_part(final_shot))
        vlm = VLM(
            models=("auto/gpt-6.1-sol", "auto/gpt-6-luna"),
            log_path=run_dir / "state_verifier_llm.jsonl",
        )
        success = False
        reason = ""
        evidence = ""
        try:
            message = vlm.chat(
                [
                    {
                        "role": "system",
                        "content": "You judge the FINAL observable state of an Android app.",
                    },
                    {"role": "user", "content": content},
                ],
                max_tokens=450,
                purpose="state_verifier",
            )
            data = parse_json(message.content or "") or {}
            success = bool(data.get("success", False))
            reason = str(data.get("reason", "")).strip()
            evidence = str(data.get("evidence", "")).strip()
        except Exception as exc:  # noqa: BLE001
            success = deterministic_ok
            reason = f"Verifier error: {exc!r}"
        if forbidden:
            success = False
            reason = f"Final UI contains forbidden text {forbidden}. " + reason
        old = {}
        if (run_dir / "result.json").exists():
            old = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        rows.append(
            {
                "id": task_id,
                "app_name": item.get("app_name", item["app"]),
                "new_rule_success": success,
                "deterministic_ok": deterministic_ok,
                "missing_text": missing,
                "forbidden_text_present": forbidden,
                "reason": reason,
                "evidence": evidence,
                "old_strict_success": old.get("success"),
                "old_verifier_success": old.get("verifier_success"),
                "old_deterministic_ok": old.get("deterministic_ok"),
            }
        )
        print(
            f"{task_id}: new={success} old_strict={old.get('success')} "
            f"det={deterministic_ok} reason={reason[:140]}"
        )
    out = ROOT / "runs" / "appagent" / "state_reeval.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
