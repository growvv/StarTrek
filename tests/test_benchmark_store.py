from __future__ import annotations

import json

from specfcg.benchmark.store import LatestStore


def test_store_keeps_only_the_latest_record(tmp_path):
    store = LatestStore(tmp_path / "summary.json")
    store.update("omni_create", {"success": False, "run": 1})
    store.update("omni_create", {"success": True, "run": 2})
    store.update("omni_delete", {"success": True, "run": 1})

    data = store.load()
    assert data["omni_create"] == {"success": True, "run": 2}
    assert data["omni_delete"] == {"success": True, "run": 1}


def test_store_rewrites_atomically_and_is_readable(tmp_path):
    path = tmp_path / "summary.json"
    store = LatestStore(path)
    store.update("a", {"x": 1})

    assert json.loads(path.read_text(encoding="utf-8"))["a"]["x"] == 1
    assert list(tmp_path.glob("*.tmp")) == []


def test_store_fills_blank_or_corrupt_file(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text("not json", encoding="utf-8")
    store = LatestStore(path)
    store.update("a", {"x": 1})
    assert store.load()["a"]["x"] == 1
