"""Markdown function-card parser and renderer."""

from __future__ import annotations

import re

from specfcg.models import FunctionCard


class CardParseError(Exception):
    """Raised when a function card is missing required structure."""


_REQUIRED = (
    "Intent",
    "Inputs",
    "Preconditions",
    "Postconditions",
    "Effects/Outputs",
    "Steps",
    "Evidence",
)

_NAME_RE = re.compile(r"^#\s+(.+?)\s*$")
_SECTION_RE = re.compile(
    r"^\*\*(Intent|Inputs|Preconditions|Postconditions|Effects/Outputs|"
    r"Steps|Evidence)\*\*:\s*(.*)$"
)
_STEP_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")


def _split_names(text: str) -> list[str]:
    """Split a comma/newline-separated list, respecting parentheses."""
    if text.strip().lower() in {"", "none", "n/a"}:
        return []
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in text:
        if char == "," and depth == 0:
            parts.append("".join(buffer))
            buffer = []
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        buffer.append(char)
    parts.append("".join(buffer))

    result: list[str] = []
    for part in parts:
        for line in part.splitlines():
            item = line.strip()
            if item:
                result.append(item)
    return result


def _section_text(sections: dict[str, list[str]], key: str) -> str:
    return " ".join(
        line.strip() for line in sections[key] if line.strip()
    ).strip()


def _parse_steps(lines: list[str]) -> list[str]:
    steps = [match.group(1) for line in lines if (match := _STEP_RE.match(line))]
    if steps:
        return steps
    return [line.strip() for line in lines if line.strip()]


def _parse_evidence(text: str) -> tuple[list[str], int, int]:
    refs_match = re.search(r"traces?\s*:?\s*(.*?)(?:;|$)", text, re.IGNORECASE)
    refs = refs_match.group(1).strip() if refs_match else ""
    if refs.lower() in {"", "none", "n/a"}:
        evidence: list[str] = []
    else:
        evidence = [part.strip() for part in refs.split(",") if part.strip()]

    counts = re.search(
        r"(\d+)\s*/\s*(\d+)\s*success", text, re.IGNORECASE
    )
    if counts:
        return evidence, int(counts.group(1)), int(counts.group(2))
    return evidence, 0, 0


def parse_card(text: str) -> FunctionCard:
    """Parse a Markdown function card, raising CardParseError if malformed."""
    name: str | None = None
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.lstrip("﻿")
        if name is None:
            if not line.strip():
                continue
            match = _NAME_RE.match(line)
            if not match or not match.group(1).strip():
                raise CardParseError("first non-empty line must be '# <name>'")
            name = match.group(1).strip()
            continue

        match = _SECTION_RE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            rest = match.group(2).strip()
            if rest:
                sections[current].append(rest)
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            raise CardParseError(f"content outside a section: {line!r}")

    if name is None:
        raise CardParseError("card has no '# <name>' heading")

    missing = [key for key in _REQUIRED if key not in sections]
    if missing:
        raise CardParseError(
            "missing required headings: " + ", ".join(missing)
        )

    evidence, success_count, attempt_count = _parse_evidence(
        _section_text(sections, "Evidence")
    )
    return FunctionCard(
        name=name,
        intent=_section_text(sections, "Intent"),
        inputs=_split_names(_section_text(sections, "Inputs")),
        preconditions=_section_text(sections, "Preconditions"),
        postconditions=_section_text(sections, "Postconditions"),
        effects_outputs=_section_text(sections, "Effects/Outputs"),
        steps=_parse_steps(sections["Steps"]),
        evidence=evidence,
        success_count=success_count,
        attempt_count=attempt_count,
    )


def render_card(card: FunctionCard) -> str:
    """Render a function card as the canonical Markdown form."""
    inputs = ", ".join(card.inputs) if card.inputs else "none"
    evidence = "traces " + (", ".join(card.evidence) if card.evidence else "none")
    if card.success_count or card.attempt_count:
        evidence += f"; {card.success_count}/{card.attempt_count} successes"

    lines = [
        f"# {card.name}",
        "",
        f"**Intent**: {card.intent}",
        f"**Inputs**: {inputs}",
        f"**Preconditions**: {card.preconditions}",
        f"**Postconditions**: {card.postconditions}",
        f"**Effects/Outputs**: {card.effects_outputs}",
        "**Steps**:",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(card.steps, 1))
    lines.append(f"**Evidence**: {evidence}")
    return "\n".join(lines) + "\n"
