from __future__ import annotations

from pathlib import Path

import pytest

from specfcg.benchmark.suite import (
    BenchTask,
    load_suite,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


SUITE = """
apps:
  - name: omninotes
    package: it.feio.android.omninotes.foss
    source: https://github.com/omnivore-app/OmniNotes
    tasks:
      - id: omni_create_note
        template: "Create a note titled {title} with content {content}."
        params:
          title: Grocery list
          content: Milk and eggs
        complexity: 1
        tags: [notes, create]
        init:
          clear_app: true
        oracle:
          ui_all: [Grocery list, Milk and eggs]
          ui_absent: [Error]
        max_steps: 20
      - id: omni_delete_note
        template: "Delete the note titled {title}."
        params:
          title: Grocery list
        oracle:
          ui_absent: [Grocery list]
"""


def test_load_suite_expands_templates_into_goals(tmp_path):
    suites = load_suite(_write(tmp_path / "suite.yaml", SUITE))

    assert len(suites) == 1
    suite = suites[0]
    assert suite.app == "omninotes"
    assert suite.package == "it.feio.android.omninotes.foss"
    assert [task.id for task in suite.tasks] == [
        "omni_create_note",
        "omni_delete_note",
    ]
    assert suite.tasks[0].goal == (
        "Create a note titled Grocery list with content Milk and eggs."
    )
    assert suite.tasks[0].params["title"] == "Grocery list"
    assert suite.tasks[0].complexity == 1
    assert suite.tasks[0].max_steps == 20
    assert suite.tasks[0].oracle["ui_all"] == [
        "Grocery list",
        "Milk and eggs",
    ]
    assert suite.tasks[1].max_steps == 20  # default cap


def test_suite_rejects_more_than_twenty_steps(tmp_path):
    text = SUITE.replace("max_steps: 20", "max_steps: 25")
    with pytest.raises(ValueError, match="max_steps"):
        load_suite(_write(tmp_path / "suite.yaml", text))


def test_suite_rejects_missing_template_parameter(tmp_path):
    text = SUITE.replace(
        "          content: Milk and eggs\n", ""
    )
    with pytest.raises(ValueError, match="content"):
        load_suite(_write(tmp_path / "suite.yaml", text))


def test_suite_rejects_unknown_oracle_key(tmp_path):
    text = SUITE.replace("ui_absent: [Error]", "ui_magic: [Error]")
    with pytest.raises(ValueError, match="ui_magic"):
        load_suite(_write(tmp_path / "suite.yaml", text))


def test_bench_task_goal_requires_all_parameters():
    task = BenchTask(
        id="t",
        app="a",
        package="p",
        template="Do {thing}.",
        params={},
    )
    with pytest.raises(ValueError, match="thing"):
        _ = task.goal


SUITE_WITH_ONBOARDING = """
apps:
  - name: markor
    package: net.gsantner.markor
    onboarding:
      - {action: click, target: "text=Next"}
      - {action: click, target: "text=Done"}
    tasks:
      - id: markor_create
        template: "Create a file named {name}."
        params:
          name: notes
        oracle:
          fs_exists: [/sdcard/notes.md]
"""


def test_app_level_onboarding_is_attached_to_every_task(tmp_path):
    suites = load_suite(
        _write(tmp_path / "suite.yaml", SUITE_WITH_ONBOARDING)
    )
    task = suites[0].tasks[0]
    assert [step["target"] for step in task.onboarding] == [
        "text=Next",
        "text=Done",
    ]


def test_task_onboarding_overrides_the_app_default(tmp_path):
    text = SUITE_WITH_ONBOARDING.replace(
        "        oracle:",
        '        onboarding:\n'
        '          - {action: click, target: "text=Skip"}\n'
        "        oracle:",
    )
    suites = load_suite(_write(tmp_path / "suite2.yaml", text))
    task = suites[0].tasks[0]
    assert [step["target"] for step in task.onboarding] == ["text=Skip"]
