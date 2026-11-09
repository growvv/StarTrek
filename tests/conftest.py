from __future__ import annotations

import pytest

from specfcg.models import FunctionCard
from tests.fakes import FakeLLMClient


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def sample_card() -> FunctionCard:
    return FunctionCard(
        name="create_note",
        intent="Create a new note with a title and optional content.",
        inputs=["title", "content"],
        preconditions="Logged in; on the notes list screen.",
        postconditions="A note with the given title appears in the notes list.",
        effects_outputs="Adds a note to the list; the new note is identified by its title.",
        steps=['Tap "+".', "Enter the title.", "Enter the content.", 'Tap "Save".'],
        evidence=["t1", "t2"],
        success_count=2,
        attempt_count=3,
    )


@pytest.fixture
def another_card() -> FunctionCard:
    return FunctionCard(
        name="share_note",
        intent="Share an existing note through another app.",
        inputs=["note", "channel"],
        preconditions="A note exists and is open.",
        postconditions="The note is shared through the chosen channel.",
        effects_outputs="Sends the note; returns to the note screen.",
        steps=['Tap "Share".', "Choose a channel."],
        evidence=["t1"],
        success_count=1,
        attempt_count=1,
    )


@pytest.fixture
def two_cards(sample_card, another_card) -> dict[str, FunctionCard]:
    return {sample_card.name: sample_card, another_card.name: another_card}
