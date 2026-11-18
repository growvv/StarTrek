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
    "Evidence",
)

# A section a card used to carry and must no longer carry.  Rejecting it is
# deliberate: without a rule the heading is unrecognised and its prose is
# silently absorbed into the section above it, so a card would keep its
# recorded taps alive as preconditions.
_RETIRED = ("Steps",)

_NAME_RE = re.compile(r"^#\s+(.+?)\s*$")
_SECTION_RE = re.compile(
    r"^\*\*(Intent|Inputs|Preconditions|Postconditions|Effects/Outputs|"
    r"Evidence)\s*:?\*\*\s*:?\s*(.*)$"
)
_RETIRED_RE = re.compile(r"^\*\*(Steps)\s*:?\*\*\s*:?\s*(.*)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")
# A declaration starts with `name (required|optional)`.  Only that shape
# starts a new input: every other comma belongs to the description of the
# input it follows.
_DECLARATION_RE = re.compile(
    r"^[A-Za-z_][\w-]*\s*\((?:required|optional)\)", re.IGNORECASE
)


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


def _split_declarations(text: str) -> list[str]:
    """Split a plain input list where every item declares itself.

    An input declaration starts with ``name (required|optional)``.  Splitting
    on every comma cuts a description in half and invents an input: Amaze's
    "file_name (required): Name to assign to the new empty file, including
    any desired extension." became a second required input named
    "including".  A comma starts a new input only when a declaration follows
    it.
    """
    if not _DECLARATION_RE.search(text):
        return _split_names(text)
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            rest = text[index + 1 :].lstrip()
            if _DECLARATION_RE.match(rest):
                parts.append(text[start:index])
                start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _parse_inputs(lines: list[str]) -> list[str]:
    """Parse comma-separated canonical inputs or Markdown bullet inputs.

    A bullet's description may contain commas; only an input section written
    without bullets is split on commas.  In either form a comma inside a
    description is punctuation, not a separator.
    """
    bullets: list[str] = []
    plain: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        match = _BULLET_RE.match(line)
        if match:
            bullets.append(match.group(1).strip())
        elif bullets:
            bullets[-1] = f"{bullets[-1]} {line.strip()}"
        else:
            plain.append(line.strip())

    if bullets:
        return [item for item in bullets if item]
    return [
        item
        for line in plain
        for item in _split_declarations(line)
        if item.strip()
    ]


def _parse_evidence(text: str) -> tuple[list[str], int, int]:
    refs_match = re.search(r"traces?\s*:?\s*(.*?)(?:;|$)", text, re.IGNORECASE)
    refs = refs_match.group(1).strip() if refs_match else ""

    # Models often explain the evidence in prose. A trace id is the first
    # backticked token in each comma-separated reference; resource ids later
    # in the same prose are not evidence.
    evidence: list[str] = []
    for part in refs.split(","):
        match = re.search(r"`([^`]+)`", part)
        if match and match.group(1).strip():
            evidence.append(match.group(1).strip())
    if not evidence and refs.lower() not in {"", "none", "n/a"}:
        refs = re.sub(r"^evidence\s*:?\s*", "", refs, flags=re.IGNORECASE)
        evidence = [
            part.strip().strip("`'\"")
            for part in refs.split(",")
            if part.strip().strip("`'\"")
        ]

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
            continue
        retired = _RETIRED_RE.match(line)
        if retired:
            raise CardParseError(
                f"the {retired.group(1)} section was removed: "
                "a card is a contract, not a script"
            )
        if current is not None:
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
        inputs=_parse_inputs(sections["Inputs"]),
        preconditions=_section_text(sections, "Preconditions"),
        postconditions=_section_text(sections, "Postconditions"),
        effects_outputs=_section_text(sections, "Effects/Outputs"),
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
        f"**Evidence**: {evidence}",
    ]
    return "\n".join(lines) + "\n"
