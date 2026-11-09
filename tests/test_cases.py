from __future__ import annotations

from pathlib import Path

import pytest

from specfcg.benchmark.cases import (
    AppSpec,
    CompositionalGoal,
    NLTestCase,
    load_apps,
    load_cases,
    load_goals,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_apps_from_mapping(tmp_path):
    path = _write(
        tmp_path / "apps.yaml",
        "apps:\n"
        "  - name: OmniNotes\n"
        "    package: it.feio.android.omninotes\n"
        "    apk_path: third_party/apks/omninotes.apk\n",
    )

    apps = load_apps(path)

    assert apps == [
        AppSpec(
            name="OmniNotes",
            package="it.feio.android.omninotes",
            apk_path=Path("third_party/apks/omninotes.apk"),
        )
    ]


def test_load_apps_from_list(tmp_path):
    path = _write(
        tmp_path / "apps.yaml",
        "- name: PodListen\n"
        "  package: com.example.podlisten\n"
        "  apk_path: apps/podlisten.apk\n",
    )

    assert load_apps(path)[0].name == "PodListen"


def test_load_cases_from_directory(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    _write(
        cases_dir / "omninotes.yaml",
        "app: omninotes\n"
        "cases:\n"
        "  - id: omni-01\n"
        "    text: create a note\n"
        "  - id: omni-02\n"
        "    text: share a note\n",
    )
    _write(
        cases_dir / "newpipe.yaml",
        "app: newpipe\n"
        "cases:\n"
        "  - id: newpipe-01\n"
        "    text: search for music\n",
    )

    cases = load_cases(cases_dir)

    assert [case.id for case in cases] == [
        "newpipe-01",
        "omni-01",
        "omni-02",
    ]
    assert all(isinstance(case, NLTestCase) for case in cases)


def test_load_cases_from_single_file(tmp_path):
    path = _write(
        tmp_path / "cases.yaml",
        "- id: omni-01\n"
        "  app: omninotes\n"
        "  text: create a note\n",
    )

    assert load_cases(path) == [
        NLTestCase(id="omni-01", app="omninotes", text="create a note")
    ]


def test_load_goals_keeps_assertions(tmp_path):
    path = _write(
        tmp_path / "goals.yaml",
        "app: omninotes\n"
        "goals:\n"
        "  - id: omni-g01\n"
        "    text: create a note and share it\n"
        "    assertions:\n"
        "      - a note exists\n"
        "      - the share sheet appeared\n",
    )

    goals = load_goals(path)

    assert goals == [
        CompositionalGoal(
            id="omni-g01",
            app="omninotes",
            text="create a note and share it",
            assertions=[
                "a note exists",
                "the share sheet appeared",
            ],
        )
    ]


def test_load_goals_from_directory(tmp_path):
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir()
    _write(
        goals_dir / "omninotes.yaml",
        "app: omninotes\n"
        "goals:\n"
        "  - id: omni-g01\n"
        "    text: create and share\n"
        "    assertions: [a note exists]\n",
    )

    goals = load_goals(goals_dir)

    assert len(goals) == 1
    assert goals[0].assertions == ["a note exists"]


def test_load_cases_rejects_non_mapping_root(tmp_path):
    path = _write(tmp_path / "bad.yaml", "just a string\n")

    with pytest.raises(ValueError):
        load_cases(path)
