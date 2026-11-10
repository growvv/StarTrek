"""Persistent natural-language experience memory (RSI-lite)."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
    "then", "it", "its", "is", "are", "be", "that", "this", "from", "by",
    "at", "as", "all", "any", "into", "after", "before", "and", "please",
}


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in _WORD_RE.findall(text.lower())
        if word not in _STOP and len(word) > 1
    }


@dataclass
class Experience:
    goal: str
    app: str
    success: bool
    steps: int
    lessons: str
    created: str


class ExperienceStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.entries: list[Experience] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self.entries.append(Experience(**data))
                except (json.JSONDecodeError, TypeError):
                    continue

    def retrieve(
        self, goal: str, app: str, k: int = 3
    ) -> list[Experience]:
        goal_tokens = _tokens(goal)
        scored: list[tuple[float, Experience]] = []
        for entry in self.entries:
            overlap = len(goal_tokens & _tokens(entry.goal))
            score = overlap / math.sqrt(max(1, len(goal_tokens)))
            if entry.app == app:
                score += 0.5
            if score >= 0.5:
                scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:k]]

    def add(
        self,
        goal: str,
        app: str,
        success: bool,
        steps: int,
        lessons: str,
    ) -> Experience:
        entry = Experience(
            goal=goal,
            app=app,
            success=success,
            steps=steps,
            lessons=lessons.strip(),
            created=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    @staticmethod
    def format(entries: list[Experience], max_chars: int = 1800) -> str:
        if not entries:
            return "None."
        lines = []
        for entry in entries:
            outcome = "success" if entry.success else "failure"
            lines.append(
                f"- [{outcome}, {entry.steps} steps] {entry.goal}\n"
                f"  Lessons: {entry.lessons}"
            )
        return "\n".join(lines)[:max_chars]
