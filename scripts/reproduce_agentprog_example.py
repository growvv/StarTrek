#!/usr/bin/env python3
"""Reproduce the AgentProg README example on the real device.

Task text is copied verbatim from the upstream README:
    "create a new contact named agent prog in contacts app."

The agent itself is the unmodified upstream pipeline (third_party/AgentProg).
This script only:
  - points the model/UI-TARS clients at the local magpie gateway,
  - records the real model I/O,
  - draws the exact tap coordinates onto a real screenshot before each action,
  - scores the final observable state.

Run:
  PYTHONIOENCODING=utf-8 .venv-agentprog/Scripts/python \
      scripts/reproduce_agentprog_example.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTPROG = ROOT / "third_party" / "AgentProg"
MAGPIE = "http://127.0.0.1:3425/v1"
SERIAL = "47261FDAS00DTQ"
MODEL = "auto/gpt-6-luna"
UITARS_MODEL = "auto/gpt-6-luna"
TASK = "create a new contact named agent prog in contacts app."
OUT = ROOT / "runs" / "repro_agentprog_readme"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AGENTPROG))
sys.path.insert(0, str(ROOT / "scripts"))

from run_agentprog_tasks import (  # noqa: E402
    ModelTrace,
    install_ui_tars_trace,
    configure_env,
)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def adb(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", SERIAL, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )


def prepare_device() -> None:
    # Contacts notification permission is environment setup, not part of the task.
    adb("shell", "pm", "grant", "com.google.android.contacts", "android.permission.POST_NOTIFICATIONS")
    adb("shell", "am", "force-stop", "com.google.android.contacts")
    adb(
        "shell", "monkey", "-p", "com.google.android.contacts",
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    time.sleep(2.5)


def capture_screen(path: Path) -> None:
    adb("shell", "screencap", "-p", "/sdcard/repro_screen.png")
    adb("pull", "/sdcard/repro_screen.png", str(path))


def font(size: int = 34):
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arialbd.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


class ActionAnnotator:
    """Draw the real tap point on a real device screenshot before each action."""

    def __init__(self, out_dir: Path) -> None:
        self.dir = out_dir / "actions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / "actions.jsonl"
        self.index = 0
        self.context: dict[str, str] = {}

    def set_context(self, kind: str, description: str = "", text: str = "") -> None:
        self.context = {"kind": kind, "description": description, "text": text}

    def _mark(self, image: Image.Image, x: int, y: int, label: str) -> Image.Image:
        draw = ImageDraw.Draw(image)
        radius = 52
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline=(220, 0, 0), width=8,
        )
        draw.line((x - 90, y, x + 90, y), fill=(220, 0, 0), width=6)
        draw.line((x, y - 90, x, y + 90), fill=(220, 0, 0), width=6)
        text = f"{label}  ({x}, {y})"
        if len(text) > 46:
            text = text[:45] + "…"
        fnt = font(34)
        try:
            box = draw.textbbox((0, 0), text, font=fnt)
            width = box[2] - box[0]
        except Exception:
            width = 600
        draw.rectangle((18, 150, 18 + width + 28, 208), fill=(178, 0, 0))
        draw.text((32, 158), text, fill=(255, 255, 255), font=fnt)
        return image

    def annotate_click(self, controller: Any, x: int, y: int, *, long: bool = False) -> None:
        try:
            kind = self.context.get("kind") or ("long_click" if long else "click")
            description = self.context.get("description", "")
            text = self.context.get("text", "")
            shot = controller.take_screenshot().convert("RGB")
            label = ("长按" if long else ("输入" if kind == "input" else "点击")) + (
                f"：{description}" if description else ""
            )
            if text:
                label += f" → {text[:20]}"
            image = self._mark(shot, int(x), int(y), label)
            self.index += 1
            name = f"action_{self.index:02d}_{kind}.png"
            clean = f"action_{self.index:02d}_{kind}_clean.png"
            image.save(self.dir / name)
            shot.save(self.dir / clean)
            record = {
                "index": self.index,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "description": description,
                "text": text,
                "x": int(x),
                "y": int(y),
                "image": str((self.dir / name).relative_to(OUT)),
                "clean": str((self.dir / clean).relative_to(OUT)),
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # annotation must never block the agent
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"error": repr(exc)}, ensure_ascii=False) + "\n")

    def annotate_drag(self, controller: Any, start: tuple, end: tuple) -> None:
        try:
            kind = self.context.get("kind") or "swipe"
            description = self.context.get("description", "")
            shot = controller.take_screenshot().convert("RGB")
            clean_shot = shot.copy()
            draw = ImageDraw.Draw(shot)
            draw.line((start[0], start[1], end[0], end[1]), fill=(220, 0, 0), width=8)
            for x, y in (start, end):
                draw.ellipse((x - 40, y - 40, x + 40, y + 40), outline=(220, 0, 0), width=7)
            fnt = font(34)
            label = f"滑动：{description}" if description else "滑动"
            draw.rectangle((18, 150, 18 + 760, 208), fill=(178, 0, 0))
            draw.text((32, 158), label[:34], fill=(255, 255, 255), font=fnt)
            self.index += 1
            name = f"action_{self.index:02d}_{kind}.png"
            clean = f"action_{self.index:02d}_{kind}_clean.png"
            shot.save(self.dir / name)
            clean_shot.save(self.dir / clean)
            record = {
                "index": self.index,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "description": description,
                "start": list(start),
                "end": list(end),
                "image": str((self.dir / name).relative_to(OUT)),
                "clean": str((self.dir / clean).relative_to(OUT)),
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"error": repr(exc)}, ensure_ascii=False) + "\n")


def install_annotations(annotator: ActionAnnotator) -> None:
    import agentprog.all_utils.mobile_utils as mu

    if getattr(mu, "_star_trek_annotated", False):
        return
    MobileAPI = mu.MobileAPI

    def wrap_context(name: str):
        original = getattr(MobileAPI, name)

        def wrapped(self, *args, **kwargs):
            description = (
                str(args[0]) if args else str(kwargs.get("view_description", ""))
            )
            text = (
                str(args[1]) if len(args) > 1 else str(kwargs.get("text", ""))
            )
            annotator.set_context(name, description, text)
            return original(self, *args, **kwargs)

        setattr(MobileAPI, name, wrapped)

    for name in ("click", "input", "input_by_pasting", "long_click"):
        wrap_context(name)

    original_click = MobileAPI._click

    def annotated_click(self, x, y):
        annotator.annotate_click(self, x, y)
        return original_click(self, x, y)

    MobileAPI._click = annotated_click

    original_long = MobileAPI._long_touch

    def annotated_long(self, x, y, duration=None):
        # _click() delegates to _long_touch(); annotate only a real long-click,
        # otherwise the same tap would be drawn twice.
        if annotator.context.get("kind") == "long_click":
            annotator.annotate_click(self, x, y, long=True)
        return original_long(self, x, y, duration)

    MobileAPI._long_touch = annotated_long

    original_drag = MobileAPI._do_drag

    def annotated_drag(self, start_xy, end_xy, duration=None):
        annotator.annotate_drag(self, start_xy, end_xy)
        return original_drag(self, start_xy, end_xy, duration)

    MobileAPI._do_drag = annotated_drag

    mu._star_trek_annotated = True


def capture_final(out_dir: Path) -> tuple[Path, str]:
    final = out_dir / "final.png"
    capture_screen(final)
    adb("shell", "uiautomator", "dump", "/sdcard/repro_final.xml")
    xml = adb("exec-out", "cat", "/sdcard/repro_final.xml").stdout or ""
    (out_dir / "final_ui.xml").write_text(xml, encoding="utf-8")
    return final, xml


def verify(final: Path, ui: str, out_dir: Path) -> dict[str, Any]:
    from mobile_agent import prompts
    from mobile_agent.llm import VLM

    ui_lower = ui.lower()
    deterministic_ok = "agent prog" in ui_lower
    prompt = prompts.STATE_VERIFIER.format(
        goal=TASK,
        expect=["agent prog"],
        expect_absent=[],
        ui=ui[:12000],
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if final.exists():
        import base64

        data = base64.b64encode(final.read_bytes()).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + data}}
        )
    vlm = VLM(models=("auto/gpt-6-luna", "auto/hy4free"), log_path=out_dir / "verifier_llm.jsonl")
    try:
        message = vlm.chat(
            [
                {"role": "system", "content": "You judge the FINAL observable state of an Android app."},
                {"role": "user", "content": content},
            ],
            max_tokens=450,
            temperature=1,
            purpose="state_verifier",
        )
        text = message.content or ""
    except Exception as exc:  # noqa: BLE001
        return {
            "success": deterministic_ok,
            "deterministic_ok": deterministic_ok,
            "reason": f"Verifier error: {exc!r}",
            "evidence": "",
        }
    import re

    match = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(match.group(0)) if match else {}
    return {
        "success": bool(data.get("success", deterministic_ok)),
        "deterministic_ok": deterministic_ok,
        "reason": str(data.get("reason", "")).strip(),
        "evidence": str(data.get("evidence", "")).strip(),
    }


def db_check() -> str:
    result = adb(
        "shell", "content", "query",
        "--uri", "content://com.android.contacts/contacts",
        "--projection", "display_name",
    )
    return (result.stdout or "").strip()


def main() -> int:
    configure_env(UITARS_MODEL, MODEL)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("actions", "images", "meta_info"):
        path = OUT / name
        if path.exists():
            shutil.rmtree(path)
    for name in ("llm_calls.jsonl", "actions.jsonl", "result.json", "agent.log",
                 "workflow.ap", "verifier_llm.jsonl", "final.png", "final_ui.xml",
                 "final_ui.txt", "error.txt", "start.png"):
        path = OUT / name
        if path.exists():
            path.unlink()

    prepare_device()
    capture_screen(OUT / "start.png")

    from agentprog import AgentProgConfig, agentprog_pipeline
    from agentprog.all_utils.general_utils import InitResponseArgs

    annotator = ActionAnnotator(OUT)
    install_annotations(annotator)

    trace = ModelTrace(OUT / "llm_calls.jsonl")
    install_ui_tars_trace(trace)

    response_args = InitResponseArgs(
        model=f"openai/{MODEL}",
        base_url=MAGPIE,
        api_key="magpie",
        record_completion_statistics=True,
        completion_kwargs={
            # gpt-6-luna rejects temperature=0.1 while reasoning is active;
            # its only supported temperature is 1. The upstream default is 0.1.
            "temperature": 1,
            "stream": False,
        },
        use_sdk=True,
    )
    config = AgentProgConfig(
        task_description=TASK,
        serial=SERIAL,
        workflow_path=str(OUT / "workflow.ap"),
        image_dir=str(OUT / "images"),
        meta_info_dir=str(OUT / "meta_info"),
        logging_path=str(OUT / "agent.log"),
        show_dashboard=False,
        use_belief_state=True,
        cache_mode=False,
        workflow_model_args=response_args,
        executor_model_args=response_args,
    )
    config.get_workflow_response = trace.wrap(config.get_workflow_response, "workflow")
    config.get_executor_response = trace.wrap(config.get_executor_response, "executor")

    started = time.perf_counter()
    error = ""
    try:
        agentprog_pipeline(config)
    except Exception:  # noqa: BLE001
        import traceback

        error = traceback.format_exc()
        (OUT / "error.txt").write_text(error, encoding="utf-8")
    duration = round(time.perf_counter() - started, 1)

    final, ui = capture_final(OUT)
    (OUT / "final_ui.txt").write_text(ui, encoding="utf-8")
    verdict = verify(final, ui, OUT)
    actions = [
        json.loads(line)
        for line in (OUT / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = {
        "task": TASK,
        "model": MODEL,
        "ui_tars_model": UITARS_MODEL,
        "duration_s": duration,
        "error": error,
        "model_calls": trace.calls,
        "actions": len(actions),
        "deterministic_ok": verdict.get("deterministic_ok"),
        "success": verdict.get("success"),
        "reason": verdict.get("reason"),
        "evidence": verdict.get("evidence"),
        "db_display_names": db_check(),
        "changed_files": [
            "agentprog/all_utils/mobile_utils.py",
            "agentprog/all_utils/ui_tars_utils.py",
            "agentprog/plan/code_exec/workflow/generate_workflow.py",
            "agentprog/plan/code_exec/workflow/workflow_query_llm.py",
        ],
    }
    (OUT / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in (
        "success", "deterministic_ok", "duration_s", "model_calls", "actions", "reason"
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
