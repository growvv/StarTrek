"""Compile function-card steps into concrete UI actions."""

from __future__ import annotations

import logging
import re

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, PlanStep

logger = logging.getLogger(__name__)

_ACTIONS = {"click", "input", "swipe", "back", "wait"}
_QUOTED_RE = re.compile(r'["“](.+?)["”]')


class StepCompiler:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _substitute(text: str, bindings: dict[str, str]) -> str:
        for key, value in bindings.items():
            text = text.replace("{" + key + "}", str(value))
            text = text.replace("$" + key, str(value))
        return text

    def _fallback(
        self, card: FunctionCard, bindings: dict[str, str]
    ) -> list[PlanStep]:
        steps: list[PlanStep] = []
        for line in card.steps:
            cleaned = line.strip()
            if not cleaned:
                continue
            lower = cleaned.lower()
            if lower.startswith(("tap", "click")):
                action = "click"
            elif lower.startswith(("enter", "input", "type")):
                action = "input"
            elif lower.startswith("swipe"):
                action = "swipe"
            elif lower.startswith("back"):
                action = "back"
            else:
                action = "click"

            quoted = _QUOTED_RE.search(cleaned)
            target = quoted.group(1) if quoted else cleaned
            args = ""
            if action == "input":
                for name, value in bindings.items():
                    if name.lower() in lower:
                        args = str(value)
                        break
            steps.append(
                PlanStep(
                    card=card.name,
                    action=action,
                    target=self._substitute(target, bindings),
                    args=args,
                )
            )
        if not steps:
            steps.append(
                PlanStep(card=card.name, action="wait", target="", args="1")
            )
        return steps

    def compile(
        self, card: FunctionCard, bindings: dict[str, str]
    ) -> list[PlanStep]:
        step_lines = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(card.steps, 1)
        )
        prompt = (
            f"Convert these function-card steps and bindings into concrete "
            f"UI actions.\nCard: {card.name}\nIntent: {card.intent}\n"
            f"Bindings: {bindings}\nSteps:\n{step_lines}\n\n"
            "Return JSON {steps:[{action,target,args}]}; action is "
            "click/input/swipe/back/wait; target uses text=... or "
            "resourceId=..."
        )
        schema = '{"steps": [{"action": "click", "target": "text=Save", "args": ""}]}'
        try:
            data = self.llm.complete_json(prompt, schema)
        except LLMParseError as exc:
            logger.warning("step compilation failed: %s", exc)
            return self._fallback(card, bindings)

        raw_steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(raw_steps, list):
            return self._fallback(card, bindings)

        steps: list[PlanStep] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).lower()
            if action not in _ACTIONS:
                continue
            steps.append(
                PlanStep(
                    card=card.name,
                    action=action,
                    target=self._substitute(
                        str(item.get("target", "")), bindings
                    ),
                    args=self._substitute(
                        str(item.get("args", "")), bindings
                    ),
                )
            )
        return steps or self._fallback(card, bindings)
