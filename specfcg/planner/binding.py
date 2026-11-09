"""LLM parameter binding from goals, state, and prior outputs."""

from __future__ import annotations

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, Goal


def _param_name(declaration: str) -> str:
    stripped = declaration.strip()
    if not stripped:
        return ""
    first = stripped.split()[0]
    return first.split("(")[0].strip()


class ParamBinder:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _resolve(value: object, prior_outputs: dict[str, str]) -> str:
        if value is None:
            return ""
        text = str(value)
        if text.startswith("$"):
            return str(prior_outputs.get(text[1:], text))
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
        inputs: list[str] = []
        for declaration in card.inputs:
            name = _param_name(declaration)
            if name and name not in inputs:
                inputs.append(name)
        if not inputs:
            return {}

        prompt = (
            f"Card: {card.name}\nIntent: {card.intent}\n"
            f"Required inputs: {card.inputs}\n"
            f"Goal: {goal.description}\nState: {state}\n"
            f"Prior outputs: {prior_outputs}\n\n"
            "Bind every required input. Values may reference a prior "
            "output as $key. Return JSON."
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
                for name in inputs
                if name in raw
            }
            missing = [
                name
                for name in inputs
                if not self._is_bound(resolved.get(name, ""))
            ]
            if not missing:
                return resolved
            prompt += (
                f"\n\nMissing required inputs: {missing}. "
                "Return every required input."
            )
        return None
