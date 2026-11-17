from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_app_graph", ROOT / "scripts" / "build_app_graph.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SPEC = {"traces": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}


def test_select_traces_keeps_only_traces_present_on_disk(tmp_path):
    module = _module()
    _write(tmp_path / "a.json")
    _write(tmp_path / "c.json")

    paths = module.select_traces(SPEC, tmp_path, set())

    assert [path.name for path in paths] == ["a.json", "c.json"]


def test_select_traces_can_seed_a_graph_from_a_subset(tmp_path):
    """A seed graph mines only the named traces.

    The probes and the self-optimization curve need a graph that is
    deliberately incomplete, so the same builder has to accept a subset.
    """
    module = _module()
    for name in ("a", "b", "c"):
        _write(tmp_path / f"{name}.json")

    paths = module.select_traces(SPEC, tmp_path, {"a", "c"})

    assert [path.name for path in paths] == ["a.json", "c.json"]


def test_grow_mines_every_trace_before_deriving_semantic_edges(
    tmp_path, monkeypatch
):
    """Semantic edges are a function of the whole card set.

    Deriving them after each trace evaluates that function once per growing
    prefix: N traces cost N calls carrying 1+2+...+N card rows.  The same
    answer comes from one call once the last card is in.
    """
    module = _module()
    monkeypatch.setattr(module, "trace_from_dict", lambda raw: raw["id"])
    paths = [
        _write(tmp_path / f"{name}.json", json.dumps({"id": name}))
        for name in ("a", "b", "c")
    ]

    events: list[tuple[str, object]] = []

    class FakePipeline:
        graph = SimpleNamespace(cards={})

        def mine_trace(self, trace):
            events.append(("mine", trace))
            return SimpleNamespace(
                new_cards=[SimpleNamespace(name=trace)]
            )

        def build_graph(self, segments):
            events.append(("build", tuple(segments)))
            return []

    module.grow(FakePipeline(), paths)

    assert events == [
        ("mine", "a"),
        ("mine", "b"),
        ("mine", "c"),
        ("build", ()),
    ]
