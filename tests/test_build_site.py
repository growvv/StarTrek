from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-11-10-specfcg-mvp.md"


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_site", ROOT / "scripts" / "build_site.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Point every output path at a temporary directory."""
    module = _module()
    docs = tmp_path / "docs"
    demo = docs / "demo"
    demo.mkdir(parents=True)
    monkeypatch.setattr(module, "SITE", docs)
    monkeypatch.setattr(module, "DEMO", demo)
    monkeypatch.setattr(module, "ASSETS", docs / "assets")
    monkeypatch.setattr(module, "EVIDENCE", docs / "evidence")
    return module, docs


def test_release_page_lists_every_release_with_its_tag(site):
    module, docs = site
    module.build_release_page()

    page = (docs / "releases.html").read_text(encoding="utf-8")
    releases = module.read_releases()
    assert releases, "releases.yaml must declare at least one release"
    for release in releases:
        assert release["version"] in page
        assert release["title"] in page


def test_release_page_links_the_github_release(site):
    module, docs = site
    module.build_release_page()

    page = (docs / "releases.html").read_text(encoding="utf-8")
    latest = module.read_releases()[0]
    assert f"{module.GITHUB}/releases/tag/{latest['tag']}" in page


def test_roadmap_marks_mvp_done_and_reports_the_current_next_round(site):
    """The roadmap reports status; it does not assume one.

    F is done as of v0.2.0 and G is still planned, so the test asserts the
    shape (a done MVP, a Next Round group) and that the page carries whatever
    status the ledger declares -- not a hard-coded snapshot that has to be
    edited every time a task lands.
    """
    module, docs = site
    module.build_roadmap_page()

    page = (docs / "roadmap.html").read_text(encoding="utf-8")
    statuses = module.read_roadmap()
    by_key = {item["key"]: item for item in statuses}

    assert all(by_key[str(n)]["status"] == "done" for n in range(1, 18))
    # The Next Round tasks report whatever the ledger says; the page must not
    # need an edit every time one lands.
    assert all(
        by_key[key]["status"] in {"done", "in_progress", "planned"}
        for key in ("F", "G", "H", "C", "A", "B", "D", "E")
    )
    assert "Stage 1 MVP" in page
    assert "Next Round" in page
    for item in statuses:
        if item["group"] == "next":
            label = {"done": "已完成", "planned": "计划中"}.get(item["status"])
            if label:
                assert label in page


def test_roadmap_keeps_the_declared_execution_order(site):
    module, _ = site
    order = [item["key"] for item in module.read_roadmap() if item["group"] == "next"]

    assert order == ["F", "G", "H", "C", "A", "B", "D", "E"]


def test_index_nav_links_releases_and_roadmap(site):
    module, docs = site
    module.build_index()

    page = (docs / "index.html").read_text(encoding="utf-8")
    assert 'href="releases.html"' in page
    assert 'href="roadmap.html"' in page


def test_index_reports_the_current_test_count(site):
    module, docs = site
    module.build_index()

    page = (docs / "index.html").read_text(encoding="utf-8")
    count = module.read_test_count()
    assert count > 0
    assert f'data-count-to="{count}"' in page
    assert "204" not in page, "the old hard-coded count must be gone"


def test_index_names_the_model_that_produced_the_numbers(site):
    module, docs = site
    module.build_index()

    page = (docs / "index.html").read_text(encoding="utf-8")
    # The pilot numbers were produced by the Magpie model, before the switch.
    assert "magpie" in page.lower()
    assert "Qwen3.8" in page


def test_evidence_copy_normalizes_line_endings(site, tmp_path, monkeypatch):
    module, docs = site
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "create_note.md").write_bytes(b"# create_note\r\n\r\n**Intent**: x\r\n")
    monkeypatch.setattr(module, "CARDS", cards)
    monkeypatch.setattr(module, "EDGES", tmp_path / "missing.jsonl")
    monkeypatch.setattr(module, "JOURNAL", tmp_path / "missing2.jsonl")
    monkeypatch.setattr(module, "REAL", tmp_path / "real")

    module.publish_evidence()

    copied = (docs / "evidence" / "cards" / "create_note.md").read_bytes()
    assert b"\r\n" not in copied
    assert copied == b"# create_note\n\n**Intent**: x\n"


def test_environment_notes_are_not_published(site):
    module, docs = site
    module.build_index()

    assert not (docs / "environment.md").exists()
    assert not (docs / "notes").exists()
    assert not (ROOT / "docs" / "environment.md").exists()
