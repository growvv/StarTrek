"""Compile function-card steps into concrete UI actions."""

from __future__ import annotations

import logging
import re

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, PlanStep

logger = logging.getLogger(__name__)

_ACTIONS = {"click", "input", "swipe", "back", "wait", "press"}
_QUOTED_RE = re.compile(r'["“](.+?)["”]')
_CODE_RE = re.compile(r"`([^`]+)`")
_BACK_RE = re.compile(r"\bback\b", re.IGNORECASE)
_ENTER_RE = re.compile(
    r"(?:\b(?:press|hit)\b.*\b(?:enter|ime|keyboard)\b)"
    r"|(?:\bsubmit\b.*\bsearch\b)",
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}")
_INLINE_TARGET_RE = re.compile(
    r"(?P<key>resourceId|text|desc|description|content-desc)="
    r"(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)'|(?P<bare>[^\s`\"',;)]+))"
)
_BARE_ID_RE = re.compile(r"[A-Za-z_][\w.]*:id/\w+")
_TARGET_PREFIXES = (
    "text=",
    "resourceId=",
    "desc=",
    "description=",
    "content-desc=",
)


class StepCompiler:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _substitute(text: str, bindings: dict[str, str]) -> str:
        for key, value in bindings.items():
            text = text.replace("{" + key + "}", str(value))
            text = text.replace("$" + key, str(value))
        return text

    @staticmethod
    def _clean_target(value: str) -> str:
        return re.sub(r"^[`\"']+|[`\"']+$", "", value.strip()).strip()

    @classmethod
    def _inline_target(cls, text: str) -> str:
        """Return a canonical target from `key=value` (quotes allowed)."""
        match = _INLINE_TARGET_RE.search(text)
        if not match:
            return ""
        value = (
            match.group("dq")
            or match.group("sq")
            or match.group("bare")
            or ""
        ).strip()
        if match.group("bare") is not None:
            value = value.rstrip(".,;:)")
        if not value:
            return ""
        return f"{match.group('key')}={value}"

    @classmethod
    def _explicit_target(cls, step: str) -> str:
        """Return a concrete target encoded directly in a card step."""
        for token in _CODE_RE.findall(step):
            token = token.strip()
            inline = cls._inline_target(token)
            if inline:
                return inline
            if token.startswith(_TARGET_PREFIXES):
                return cls._clean_target(token)
            if ":id/" in token:
                bare = _BARE_ID_RE.search(token)
                if bare:
                    return f"resourceId={bare.group(0)}"
                return f"resourceId={cls._clean_target(token)}"
        inline = cls._inline_target(step)
        if inline:
            return inline
        match = _BARE_ID_RE.search(step)
        if match:
            return f"resourceId={match.group(0)}"
        return ""

    @staticmethod
    def _bound_label(
        step: str, target: str, bindings: dict[str, str]
    ) -> str | None:
        """Return the binding a click step uses as a visible label."""
        if not target.startswith("resourceId="):
            return None

        names: list[str] = []
        label = re.search(
            r"\b(?:label|text|titled|named)\b\s+(?:is\s+)?"
            r"\{([A-Za-z_][\w-]*)\}",
            step,
            re.IGNORECASE,
        )
        if label:
            names.append(label.group(1))

        entry = target.rsplit("/", 1)[-1].lower()
        if re.search(r"title|text|label|name", entry):
            names.extend(_PLACEHOLDER_RE.findall(step))

        for name in names:
            value = bindings.get(name)
            if value is not None and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def _input_args(step: str, bindings: dict[str, str]) -> str | None:
        for name in _PLACEHOLDER_RE.findall(step):
            if name in bindings:
                return str(bindings[name])
        lower = step.lower()
        for name, value in bindings.items():
            if re.search(rf"\b{re.escape(name.lower())}\b", lower):
                return str(value)
        if len(bindings) == 1:
            return str(next(iter(bindings.values())))
        return None

    def _explicit(
        self, card: FunctionCard, bindings: dict[str, str]
    ) -> list[PlanStep] | None:
        """Compile cards whose steps already name concrete UI targets.

        Mined cards usually embed resource ids observed in the trace. Parsing
        those directly avoids an LLM round trip and avoids model drift. Cards
        without explicit targets still go through the LLM compiler.
        """
        steps: list[PlanStep] = []
        for line in card.steps:
            cleaned = line.strip()
            if not cleaned:
                continue
            lower = cleaned.lower()

            if "swipe" in lower:
                numbers = re.findall(r"-?\d+", cleaned)
                if len(numbers) < 4:
                    return None
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="swipe",
                        target="",
                        args=",".join(numbers[:4]),
                    )
                )
                continue

            if lower.startswith("wait"):
                numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="wait",
                        target="",
                        args=numbers[0] if numbers else "1",
                    )
                )
                continue

            target = self._substitute(
                self._explicit_target(cleaned), bindings
            )
            if not target and _BACK_RE.search(lower):
                steps.append(
                    PlanStep(card=card.name, action="back", target="")
                )
                continue
            if not target and _ENTER_RE.search(lower):
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="press",
                        target="",
                        args="enter",
                    )
                )
                continue
            if not target:
                return None

            if any(
                marker in lower
                for marker in ("enter ", "input ", "type ", "fill ")
            ):
                args = self._input_args(cleaned, bindings)
                if args is None:
                    return None
                steps.append(
                    PlanStep(
                        card=card.name,
                        action="input",
                        target=target,
                        args=args,
                    )
                )
                continue

            label = self._bound_label(cleaned, target, bindings)
            if label is not None:
                target = f"{target}|text={label}"
            steps.append(
                PlanStep(card=card.name, action="click", target=target)
            )
        return steps or None

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
            elif lower.startswith(("press ", "hit ")):
                action = "press"
            else:
                action = "click"

            quoted = _QUOTED_RE.search(cleaned)
            target = quoted.group(1) if quoted else cleaned
            args = "enter" if action == "press" else ""
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
        explicit = self._explicit(card, bindings)
        if explicit is not None:
            return explicit

        step_lines = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(card.steps, 1)
        )
        prompt = (
            f"Convert these function-card steps and bindings into concrete "
            f"UI actions.\nCard: {card.name}\nIntent: {card.intent}\n"
            f"Bindings: {bindings}\nSteps:\n{step_lines}\n\n"
            "Return JSON {steps:[{action,target,args}]}; action is "
            "click/input/swipe/back/wait/press; target uses text=..., "
            "desc=..., or resourceId=...; press uses args=enter for the "
            "keyboard search/enter key."
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
            action = str(item.get("action", "")).strip().lower()
            if action not in _ACTIONS:
                continue
            target = self._substitute(
                str(item.get("target", "")), bindings
            )
            steps.append(
                PlanStep(
                    card=card.name,
                    action=action,
                    target=self._clean_target(target),
                    args=self._substitute(
                        str(item.get("args", "")), bindings
                    ),
                )
            )
        return steps or self._fallback(card, bindings)
