"""LLM-based natural-language UI state summaries."""

from __future__ import annotations

import logging

from specfcg.llm.client import LLMClient

logger = logging.getLogger(__name__)

_PROMPT = (
    "Summarize this Android UI hierarchy in at most 6 lines: current "
    "screen, visible widgets, user state, known entities, recent actions."
)


class PlainStateSummarizer:
    """Deterministic fallback: keep the compact UI dump, make no LLM call.

    The summary is only used as trace metadata, so paying a 1-4 minute
    reasoning-model call for it is waste.
    """

    @staticmethod
    def summarize(ui_dump: str) -> str:
        return ui_dump[:2000]


class StateSummarizer:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def summarize(self, ui_dump: str) -> str:
        prompt = f"{_PROMPT}\n\n{ui_dump[:6000]}"
        try:
            result = self.llm.complete(prompt)
        except Exception as exc:  # summaries are best-effort
            logger.warning("state summary failed: %s", exc)
            return ui_dump[:2000]
        if not result or not result.strip():
            return ui_dump[:2000]
        return result.strip()
