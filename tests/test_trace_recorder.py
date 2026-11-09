import pytest

from specfcg.models import Step
from specfcg.traces.collector import FixtureCollector
from specfcg.traces.recorder import TraceParseError, TraceRecorder, TraceStore


def test_trace_round_trip(tmp_path, sample_trace):
    store = TraceStore(tmp_path)
    path = store.save(sample_trace)
    assert store.load(sample_trace.trace_id) == sample_trace
    assert path.exists()


def test_fixture_collector_returns_traces(tmp_path, sample_trace):
    store = TraceStore(tmp_path)
    store.save(sample_trace)
    assert FixtureCollector(tmp_path).collect("omninotes") == [sample_trace]


def test_fixture_collector_returns_empty_when_no_match(tmp_path, sample_trace):
    store = TraceStore(tmp_path)
    store.save(sample_trace)
    assert FixtureCollector(tmp_path).collect("newpipe") == []


def test_malformed_trace_json_raises(tmp_path):
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(TraceParseError):
        TraceStore(tmp_path).load("bad")


def test_recorder_collects_steps():
    recorder = TraceRecorder("omninotes", "t1")
    recorder.record(Step(action="click", target="text=+"))
    trace = recorder.trace()
    assert trace.trace_id == "t1"
    assert trace.app == "omninotes"
    assert trace.steps == [Step(action="click", target="text=+")]
