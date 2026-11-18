"""A GuiAgent backed by the repository's screenshot-first MobileAgent."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mobile_agent.agent import MobileAgent, TaskSpec
from mobile_agent.device import AndroidDevice
from mobile_agent.llm import VLM
from mobile_agent.memory import ExperienceStore

from specfcg.executor.agent import AgentTrace
from specfcg.models import Step


def _target_from_args(args: dict[str, Any]) -> str:
    """Express the agent's tap arguments as the repo's action-target syntax."""
    resource_id = args.get("id") or args.get("resourceId")
    if resource_id:
        return f"resourceId={resource_id}"
    text = args.get("text")
    if text:
        return f"text={text}"
    return ""


class MobileAgentBackend:
    """Run tasks with MobileAgent, converting its record into an AgentTrace.

    One ``VLM`` and one ``ExperienceStore`` live on the backend: the model is
    the same for every app, and the store is read but never written, because
    the agent runs with ``verify=False`` and a lesson from an unjudged run is
    a guess.  An ``AndroidDevice`` is created per app and connects lazily, so
    observation and action go through the same client.
    """

    def __init__(
        self,
        serial: str,
        model: str,
        fallback_model: str,
        out_root: Path | str,
        base_url: str | None = None,
        api_key: str = "",
    ) -> None:
        self.serial = serial
        self.out_root = Path(out_root)
        self._models = (model, fallback_model)
        # The endpoint travels with the backend: VLM's own default is the
        # Magpie gateway, and a local vLLM model name is not served there.
        self._base_url = base_url
        self._api_key = api_key
        # Built on first use, so constructing a pipeline for a command that
        # never executes a plan (mine, build-graph, plan) opens no client.
        self._llm: VLM | None = None
        self._memory: ExperienceStore | None = None
        self._devices: dict[str, AndroidDevice] = {}

    @property
    def models(self) -> tuple[str, str]:
        return self._models

    @property
    def endpoint(self) -> str:
        """The OpenAI-compatible base URL this backend talks to."""
        return self._base_url or "http://127.0.0.1:3425/v1"

    @property
    def llm(self) -> VLM:
        if self._llm is None:
            self._llm = VLM(
                models=self._models,
                base_url=self.endpoint,
                api_key=self._api_key or "local",
            )
        return self._llm

    @property
    def memory(self) -> ExperienceStore:
        if self._memory is None:
            self._memory = ExperienceStore(self.out_root / "memory")
        return self._memory

    def _device(self, app: str) -> AndroidDevice:
        if app not in self._devices:
            self._devices[app] = AndroidDevice(self.serial, app)
        return self._devices[app]

    def observe(self, app: str) -> str:
        return self._device(app).ui_text()

    def run(self, task: str, max_steps: int, *, app: str) -> AgentTrace:
        agent = MobileAgent(
            self._device(app),
            self.llm,
            self.memory,
            self.out_root,
            verify=False,
        )
        spec = TaskSpec(
            id=hashlib.sha256(task.encode("utf-8")).hexdigest()[:16],
            app=app,
            app_name=app,
            goal=task,
            max_steps=max_steps,
        )
        try:
            result = agent.run(spec)
        except Exception as exc:  # the caller wants a trace, not a crash
            return AgentTrace(error=repr(exc))
        return self._convert(result)

    @staticmethod
    def _convert(result: Any) -> AgentTrace:
        steps: list[Step] = []
        for record in getattr(result, "step_records", []) or []:
            name = record.get("tool", "")
            args = record.get("args") or {}
            steps.append(_to_step(name, args, record))
        return AgentTrace(
            steps=steps,
            initial_ui=getattr(result, "initial_ui", ""),
            final_ui=getattr(result, "final_ui", ""),
            done=getattr(result, "done", False),
            error=getattr(result, "error", ""),
        )


def _to_step(name: str, args: dict[str, Any], record: dict[str, Any]) -> Step:
    """Map one agent tool call onto the repo's Step vocabulary.

    The screen before and after each action is carried on the step: the
    trace is evidence of what the app showed along the way, not only of
    where it ended.
    """
    ok = bool(record.get("ok", True))
    before = record.get("ui_before", "") or ""
    after = record.get("ui_after", "") or ""
    if name == "tap":
        return Step(action="click", target=_target_from_args(args),
                    before_state=before, after_state=after, success=ok)
    if name == "tap_xy":
        coords = f"{args.get('x', '')},{args.get('y', '')}"
        return Step(action="click", target="", args=coords,
                    before_state=before, after_state=after, success=ok)
    if name == "type_text":
        return Step(action="input", target="", args=str(args.get("text", "")),
                    before_state=before, after_state=after, success=ok)
    if name == "press":
        return Step(action="press", target=str(args.get("key", "")),
                    before_state=before, after_state=after, success=ok)
    if name == "swipe":
        return Step(action="swipe", target=str(args.get("direction", "")),
                    before_state=before, after_state=after, success=ok)
    if name == "wait":
        return Step(action="wait", target=str(args.get("seconds", "")),
                    before_state=before, after_state=after, success=ok)
    return Step(action=name or "unknown", target="",
                before_state=before, after_state=after, success=ok)
