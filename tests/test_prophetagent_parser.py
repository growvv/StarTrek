from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from specfcg.integrations.prophetagent import (
    PROPHETAGENT_COMMIT,
    ProphetAgentCollector,
    parse_droidbot_output,
)


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "prophetagent"


def _write_events(path: Path, events) -> None:
    path.write_text(json.dumps(events), encoding="utf-8")


def test_parse_droidbot_output_builds_traces(fixture_dir):
    traces = parse_droidbot_output(fixture_dir, "omninotes")
    assert len(traces) == 1
    assert traces[0].trace_id.startswith("omninotes-")
    assert traces[0].steps[0].action == "click"
    assert traces[0].steps[0].target
    assert traces[0].steps[1].action == "input"
    assert traces[0].steps[1].args == "Trip"


def test_parse_missing_events_returns_empty(tmp_path):
    assert parse_droidbot_output(tmp_path, "omninotes") == []


def test_parse_malformed_events_returns_empty(tmp_path):
    (tmp_path / "events.json").write_text("{not json", encoding="utf-8")
    assert parse_droidbot_output(tmp_path, "omninotes") == []


def test_parse_skips_events_without_target(tmp_path):
    _write_events(
        tmp_path / "events.json",
        [
            {
                "event_type": "touch",
                "view_str": "",
                "event_str": "",
                "from_state": "s1",
                "to_state": "s2",
            },
            {
                "event_type": "touch",
                "view_str": "Save",
                "from_state": "s2",
                "to_state": "s3",
            },
        ],
    )

    traces = parse_droidbot_output(tmp_path, "omninotes")

    assert len(traces) == 1
    assert len(traces[0].steps) == 1
    assert traces[0].steps[0].target == "Save"


def test_parse_splits_traces_at_state_discontinuity(tmp_path):
    _write_events(
        tmp_path / "events.json",
        [
            {
                "event_type": "touch",
                "view_str": "A",
                "from_state": "s1",
                "to_state": "s2",
            },
            {
                "event_type": "touch",
                "view_str": "B",
                "from_state": "s2",
                "to_state": "s3",
            },
            {
                "event_type": "touch",
                "view_str": "C",
                "from_state": "s5",
                "to_state": "s6",
            },
        ],
    )

    traces = parse_droidbot_output(tmp_path, "omninotes")

    assert [len(trace.steps) for trace in traces] == [2, 1]


def test_parse_groups_explicit_trace_ids(tmp_path):
    _write_events(
        tmp_path / "events.json",
        [
            {
                "event_type": "touch",
                "view_str": "A",
                "from_state": "s1",
                "to_state": "s2",
                "trace_id": "t1",
            },
            {
                "event_type": "touch",
                "view_str": "B",
                "from_state": "s3",
                "to_state": "s4",
                "trace_id": "t2",
            },
            {
                "event_type": "touch",
                "view_str": "C",
                "from_state": "s5",
                "to_state": "s6",
                "trace_id": "t1",
            },
        ],
    )

    traces = parse_droidbot_output(tmp_path, "omninotes")

    assert len(traces) == 2
    assert [len(trace.steps) for trace in traces] == [2, 1]


def test_collect_runs_start_py_and_parses_output(
    monkeypatch, tmp_path, fixture_dir
):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output_dir = Path(command[command.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "events.json").write_text(
            (fixture_dir / "events.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "specfcg.integrations.prophetagent.subprocess.run", fake_run
    )
    collector = ProphetAgentCollector(
        repo, tmp_path / "output", device_serial="emulator-5554"
    )

    traces = collector.collect(
        "omninotes",
        tmp_path / "app.apk",
        policy="dfs",
        count=3,
        timeout_s=9,
    )

    assert len(traces) == 1
    command, kwargs = calls[0]
    assert command[1] == "start.py"
    assert command[command.index("-a") + 1] == str(tmp_path / "app.apk")
    assert command[command.index("-policy") + 1] == "dfs"
    assert command[command.index("-count") + 1] == "3"
    assert command[command.index("-timeout") + 1] == "9"
    assert kwargs["cwd"] == repo
    assert kwargs["env"]["ANDROID_SERIAL"] == "emulator-5554"


def test_setup_script_pins_prophetagent_commit():
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "setup_prophetagent.sh"
    )
    text = script.read_text(encoding="utf-8")
    assert PROPHETAGENT_COMMIT in text
    assert "checkout" in text
    assert "$COMMIT" in text
    assert "ProphetAgent/Home" in text
