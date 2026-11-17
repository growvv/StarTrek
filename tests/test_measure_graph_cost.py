from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "measure_graph_cost", ROOT / "scripts" / "measure_graph_cost.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_journal_finds_either_graph_layout(tmp_path):
    module = _module()

    nested = tmp_path / "recorded"
    (nested / "graph").mkdir(parents=True)
    (nested / "graph" / "journal.jsonl").write_text("", encoding="utf-8")
    assert module.journal(nested) == nested / "graph" / "journal.jsonl"

    flat = tmp_path / "fresh"
    flat.mkdir()
    (flat / "journal.jsonl").write_text("", encoding="utf-8")
    assert module.journal(flat) == flat / "journal.jsonl"

    assert module.journal(tmp_path / "absent") is None


def test_cost_counts_the_semantic_frames_of_a_journal(tmp_path):
    module = _module()
    (tmp_path / "journal.jsonl").write_text(
        "\n".join(
            [
                '{"ts": "2026-11-14T00:00:00Z", "reason": "mined trace a -> x"}',
                '{"ts": "2026-11-14T00:02:45Z", '
                '"reason": "semantic edges over 1 card"}',
            ]
        ),
        encoding="utf-8",
    )

    assert module.cost(tmp_path) == {"calls": 1, "seconds": 165.0}
