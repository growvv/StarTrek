"""LLM parameter binding from goals, state, and prior outputs."""

from __future__ import annotations

import re

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, Goal

_PARAM_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)")


def _param_name(declaration: str) -> str:
    stripped = declaration.strip().lstrip("-*• ").strip().replace("`", "")
    if not stripped:
        return ""
    match = _PARAM_NAME_RE.match(stripped)
    if match:
        return match.group(1)
    first = stripped.split()[0]
    return first.split("(")[0].strip()


_OBSERVED_RE = re.compile(r";\s*observed:\s*(['\"])(.*?)\1")


def _observed_label(declaration: str) -> str | None:
    """The control label the trace observed for this input, if recorded.

    A card that names a control the build itself labels ("the delete menu
    item") cannot expect the goal to supply that label -- the goal is a
    user's sentence, not the build's resource strings.  The trace saw the
    label, so the card records it; the binder uses it when the goal names
    no value, and the caller can still override it.
    """
    match = _OBSERVED_RE.search(declaration)
    if not match:
        return None
    label = match.group(2).strip()
    return label or None


class ParamBinder:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _resolve(value: object, prior_outputs: dict[str, str]) -> str:
        if value is None:
            return ""
        text = str(value)
        if text.startswith("$"):
            key = text[1:]
            if key in prior_outputs:
                return str(prior_outputs[key])
            return text
        return text

    @staticmethod
    def _is_bound(value: str) -> bool:
        return bool(value) and not value.startswith("$")

    def bind(
        self,
        card: FunctionCard,
        goal: Goal,
        state: str,
        prior_outputs: dict[str, str],
    ) -> dict[str, str] | None:
        inputs: list[tuple[str, bool]] = []
        observed: dict[str, str] = {}
        for declaration in card.inputs:
            name = _param_name(declaration)
            if not name:
                continue
            observed_label = _observed_label(declaration)
            if observed_label is not None:
                observed[name] = observed_label
            if all(existing != name for existing, _ in inputs):
                inputs.append((name, "optional" in declaration.lower()))
        if not inputs:
            return {}
        required = [name for name, optional in inputs if not optional]

        prompt = (
            f"Card: {card.name}\nIntent: {card.intent}\n"
            f"Required inputs: {card.inputs}\n"
            f"Goal: {goal.description}\nState: {state}\n"
            f"Prior outputs: {prior_outputs}\n\n"
            "Bind every required input. The goal is authoritative for "
            "every value it names -- including when the same card runs "
            "again later in the plan and its earlier instance left a prior "
            "output; that prior output must not override the goal's value. "
            "Use a prior output only for inputs the goal itself does not "
            "name, referencing it as $key. Return JSON."
        )
        schema = '{"bindings": {"param": "value"}}'

        for _attempt in range(2):
            try:
                data = self.llm.complete_json(prompt, schema)
            except LLMParseError:
                data = {}
            raw = data.get("bindings") if isinstance(data, dict) else None
            if not isinstance(raw, dict):
                raw = {}

            resolved = {
                name: self._resolve(raw[name], prior_outputs)
                for name, _optional in inputs
                if name in raw
            }
            # A control the build labels is not something the goal can name:
            # fill an input the goal left empty with the label the trace
            # observed, rather than asking the model to invent the build's
            # wording.
            for name, _optional in inputs:
                if not str(resolved.get(name) or "").strip() and name in observed:
                    resolved[name] = observed[name]
            # An explicit empty value is an answer: the goal names no value
            # for this input, so the model's deliberate "" is the right one.
            # What is actually missing is a key it never returned, or a
            # reference to a prior output that does not exist.  A reference
            # that resolves to an empty value is resolved -- the earlier
            # step produced an empty value, and that is the value.
            def unanswered(name: str) -> bool:
                if name not in raw:
                    return True
                text = str(raw[name])
                if not text.startswith("$"):
                    return False
                return text[1:] not in prior_outputs

            missing = [name for name in required if unanswered(name)]
            if not missing:
                return resolved
            prompt += (
                f"\n\nMissing required inputs: {missing}. "
                "Return every required input."
            )
        return None
