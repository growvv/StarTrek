from __future__ import annotations

import importlib.util
from pathlib import Path

from specfcg.cards.store import CardStore
from specfcg.models import FunctionCard

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "measure_granularity", ROOT / "scripts" / "measure_granularity.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _card(name: str, step: str) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"do {name}",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[step],
    )


def test_measure_reads_the_graph_under_the_app_directory(tmp_path):
    module = _module()
    store = CardStore(tmp_path / "omninotes" / "graph")
    store.save(_card("open_note", "Tap the title (`id/note_title`)."))
    store.save(
        _card("open_note_from_list", "Tap the title ( `id/note_title` ).")
    )

    record = module.measure("omninotes", tmp_path)

    assert record["cards"] == 2
    assert record["duplicate_groups"] == [
        ["open_note", "open_note_from_list"]
    ]
    assert record["score"] == 0.5


def test_measure_skips_an_app_with_no_graph(tmp_path):
    module = _module()

    assert module.measure("markor", tmp_path) is None
