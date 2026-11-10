"""Planner / executor / verifier / reflection loop for mobile GUI tasks."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mobile_agent import prompts
from mobile_agent.device import AndroidDevice
from mobile_agent.llm import VLM
from mobile_agent.memory import ExperienceStore


@dataclass
class TaskSpec:
    id: str
    app: str
    app_name: str
    goal: str
    expect_text: list[str] = field(default_factory=list)
    expect_absent: list[str] = field(default_factory=list)
    max_steps: int = 25


@dataclass
class TaskResult:
    id: str
    goal: str
    app: str
    app_name: str
    success: bool
    verifier_success: bool
    deterministic_ok: bool
    reason: str
    plan: str
    steps: int
    llm_calls: int
    llm_seconds: float
    elapsed_s: float
    model: str
    expect_text: list[str]
    expect_absent: list[str]
    screenshot_dir: str
    error: str = ""


def _image_part(path: Path) -> dict[str, Any]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + data},
    }


def _parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class MobileAgent:
    def __init__(
        self,
        device: AndroidDevice,
        llm: VLM,
        memory: ExperienceStore,
        out_root: Path,
        reflect_every: int = 6,
    ) -> None:
        self.device = device
        self.llm = llm
        self.memory = memory
        self.out_root = Path(out_root)
        self.reflect_every = reflect_every

    def _observation(
        self,
        task: TaskSpec,
        plan: str,
        history: list[str],
        memory_text: str,
        step: int,
        ui: str,
    ) -> str:
        recent = "\n".join(history[-14:]) or "None yet."
        return (
            f"Goal: {task.goal}\n"
            f"App: {task.app_name} ({task.app})\n\n"
            f"Plan:\n{plan}\n\n"
            f"Relevant lessons from similar past tasks:\n{memory_text}\n\n"
            f"Recent actions:\n{recent}\n\n"
            f"This is step {step} of at most {task.max_steps}.\n"
            f"Current UI elements:\n{ui}"
        )

    def _plan(self, task: TaskSpec, memory_text: str, shot: Path) -> str:
        ui = self.device.ui_text()
        content = [
            {"type": "text", "text": prompts.PLANNER.format(
                goal=task.goal, app=task.app_name, memory=memory_text
            ) + f"\n\nCurrent UI elements:\n{ui}"},
            _image_part(shot),
        ]
        message = self.llm.chat(
            [
                {"role": "system", "content": "You plan grounded GUI tasks."},
                {"role": "user", "content": content},
            ],
            max_tokens=700,
            purpose="planner",
        )
        plan = (message.content or "").strip()
        return plan or "1. Inspect the screen and work toward the goal."

    def _reflect(
        self,
        task: TaskSpec,
        plan: str,
        history: list[str],
        shot: Path,
    ) -> str:
        content = [
            {"type": "text", "text": prompts.REFLECT.format(
                goal=task.goal,
                plan=plan,
                history="\n".join(history[-14:]) or "None.",
            )},
            _image_part(shot),
        ]
        message = self.llm.chat(
            [
                {"role": "system", "content": "You supervise a GUI agent."},
                {"role": "user", "content": content},
            ],
            max_tokens=700,
            purpose="reflect",
        )
        return (message.content or "").strip()

    def _verify(
        self,
        task: TaskSpec,
        plan: str,
        history: list[str],
        shot: Path,
        final_ui: str,
        deterministic_ok: bool,
    ) -> tuple[bool, str]:
        content = [
            {"type": "text", "text": prompts.VERIFIER.format(
                goal=task.goal,
                expect=task.expect_text,
                expect_absent=task.expect_absent,
                plan=plan,
                history="\n".join(history[-18:]) or "None.",
            ) + f"\n\nFinal UI elements:\n{final_ui}"},
            _image_part(shot),
        ]
        message = self.llm.chat(
            [
                {"role": "system", "content": "You verify GUI task completion."},
                {"role": "user", "content": content},
            ],
            max_tokens=500,
            purpose="verifier",
        )
        data = _parse_json(message.content or "")
        if not data:
            return deterministic_ok, "Verifier output was not valid JSON."
        success = bool(data.get("success", False))
        reason = str(data.get("reason", "")).strip()
        if not deterministic_ok:
            success = False
            reason = (
                f"Expected visible evidence {task.expect_text} / absent "
                f"{task.expect_absent} was not confirmed. " + reason
            ).strip()
        return success, reason or "No reason provided."

    def _lessons(
        self,
        task: TaskSpec,
        success: bool,
        reason: str,
        history: list[str],
    ) -> str:
        content = prompts.EXPERIENCE.format(
            goal=task.goal,
            outcome="success" if success else "failure",
            reason=reason,
            history="\n".join(history[-18:]) or "None.",
        )
        try:
            message = self.llm.chat(
                [
                    {"role": "system", "content": "You distill reusable GUI lessons."},
                    {"role": "user", "content": content},
                ],
                max_tokens=600,
                purpose="experience",
            )
            return (message.content or "").strip()[:1600]
        except Exception as exc:
            return f"Task {'succeeded' if success else 'failed'}: {reason} ({exc!r})"

    def _execute(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        if name == "tap":
            return self.device.tap(
                text=args.get("text"), resource_id=args.get("id")
            )
        if name == "tap_xy":
            return self.device.tap_xy(int(args["x"]), int(args["y"]))
        if name == "type_text":
            return self.device.type_text(str(args.get("text", "")))
        if name == "press":
            return self.device.press(str(args.get("key", "")))
        if name == "swipe":
            return self.device.swipe(str(args.get("direction", "")))
        if name == "wait":
            return self.device.wait(float(args.get("seconds", 1)))
        if name == "done":
            return True, "DONE"
        return False, f"FAIL unknown tool {name}"

    def run(self, task: TaskSpec) -> TaskResult:
        started = time.perf_counter()
        calls_before = self.llm.calls
        seconds_before = self.llm.seconds
        out = self.out_root / task.id
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        error = ""
        plan = ""
        step_records: list[dict[str, Any]] = []
        history: list[str] = []
        final_shot = out / "00_initial.jpg"
        done_summary = ""
        last_signature = ""
        stall = 0
        final_ui = ""

        try:
            self.device.start_app()
            plan_shot = out / "00_plan.jpg"
            image = self.device.screenshot(plan_shot)
            memory_hits = self.memory.retrieve(task.goal, task.app)
            memory_text = ExperienceStore.format(memory_hits)
            (out / "memory.json").write_text(
                json.dumps(
                    [asdict(entry) for entry in memory_hits],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            plan = self._plan(task, memory_text, plan_shot)

            for step in range(1, task.max_steps + 1):
                before = out / f"step_{step:02d}_before.jpg"
                image = self.device.screenshot(before)
                ui = self.device.ui_text()
                ui_hash = hashlib.sha1(ui.encode("utf-8")).hexdigest()[:16]
                observation = self._observation(
                    task, plan, history, memory_text, step, ui
                )
                message = self.llm.chat(
                    [
                        {"role": "system", "content": prompts.SYSTEM},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": observation},
                                _image_part(before),
                            ],
                        },
                    ],
                    tools=prompts.TOOLS,
                    max_tokens=1200,
                    purpose=f"executor step {step}",
                )
                thought = (message.content or "").strip()
                calls = list(message.tool_calls or [])

                if not calls:
                    history.append(f"{step}. no tool call ({thought[:80]})")
                    step_records.append(
                        {
                            "step": step,
                            "thought": thought,
                            "tool": "none",
                            "args": {},
                            "result": "no tool call",
                            "before": before.name,
                            "after": before.name,
                            "ui_hash": ui_hash,
                        }
                    )
                    continue

                call = calls[0]
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                ok, result = self._execute(name, args)
                after = out / f"step_{step:02d}_after.jpg"
                self.device.screenshot(after)
                after_ui = self.device.ui_text()
                after_hash = hashlib.sha1(
                    after_ui.encode("utf-8")
                ).hexdigest()[:16]

                record = {
                    "step": step,
                    "thought": thought,
                    "tool": name,
                    "args": args,
                    "ok": ok,
                    "result": result,
                    "before": before.name,
                    "after": after.name,
                    "ui_hash_before": ui_hash,
                    "ui_hash_after": after_hash,
                }
                step_records.append(record)
                history.append(
                    f"{step}. {name}({json.dumps(args, ensure_ascii=False)}) "
                    f"-> {result}"
                )
                if name == "done":
                    done_summary = str(args.get("summary", ""))
                    break

                signature = f"{name}:{json.dumps(args, sort_keys=True)}:{after_hash}"
                if signature == last_signature:
                    stall += 1
                else:
                    stall = 0
                last_signature = signature
                if stall >= 2:
                    history.append(
                        "WARNING: the last two actions produced the same screen. "
                        "Try a different target or go back."
                    )
                if stall >= 4:
                    history.append("STOP: repeated identical actions with no progress.")
                    break

                if step % self.reflect_every == 0:
                    reflection = self._reflect(task, plan, history, after)
                    with (out / "reflections.jsonl").open(
                        "a", encoding="utf-8"
                    ) as handle:
                        handle.write(
                            json.dumps(
                                {"step": step, "text": reflection},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    if reflection.upper().startswith("REPLAN:"):
                        plan = reflection.split(":", 1)[1].strip() or plan

            final_shot = out / f"final.jpg"
            self.device.screenshot(final_shot)
            final_ui = self.device.ui_text()
            deterministic_ok = all(
                text.lower() in final_ui.lower() for text in task.expect_text
            ) and all(
                text.lower() not in final_ui.lower()
                for text in task.expect_absent
            )
            verified, reason = self._verify(
                task, plan, history, final_shot, final_ui, deterministic_ok
            )
            success = bool(verified and deterministic_ok)
            lessons = self._lessons(task, success, reason, history)
            self.memory.add(
                goal=task.goal,
                app=task.app,
                success=success,
                steps=len(step_records),
                lessons=lessons,
            )
        except Exception as exc:
            verified = False
            success = False
            deterministic_ok = False
            reason = f"agent error: {exc!r}"
            error = repr(exc)
            final_ui = ""
            try:
                self.device.screenshot(final_shot)
            except Exception:
                pass

        elapsed = time.perf_counter() - started
        result = TaskResult(
            id=task.id,
            goal=task.goal,
            app=task.app,
            app_name=task.app_name,
            success=success,
            verifier_success=verified,
            deterministic_ok=deterministic_ok,
            reason=reason,
            plan=plan,
            steps=len(step_records),
            llm_calls=self.llm.calls - calls_before,
            llm_seconds=round(self.llm.seconds - seconds_before, 1),
            elapsed_s=round(elapsed, 1),
            model=self.llm.models[0],
            expect_text=list(task.expect_text),
            expect_absent=list(task.expect_absent),
            screenshot_dir=str(out),
            error=error,
        )
        (out / "result.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out / "steps.json").write_text(
            json.dumps(step_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out / "final_ui.txt").write_text(final_ui, encoding="utf-8")
        (out / "done_summary.txt").write_text(done_summary, encoding="utf-8")
        return result
