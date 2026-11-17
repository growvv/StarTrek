from __future__ import annotations

from specfcg.benchmark.graph_cost import semantic_cost


def _frame(stamp: str, reason: str) -> dict:
    return {"ts": stamp, "reason": reason}


def test_one_call_over_the_whole_card_set_records_one_call():
    frames = [
        _frame("2026-11-14T00:00:00Z", "mined trace a -> x"),
        _frame("2026-11-14T00:00:05Z", "mined trace b -> y"),
        _frame("2026-11-14T00:02:45Z", "semantic edges over 2 cards"),
    ]

    assert semantic_cost(frames) == {"calls": 1, "seconds": 160.0}


def test_a_rebuild_after_every_trace_records_one_call_per_trace():
    """The quadratic build is visible in its own journal.

    Deriving the edges after each mined trace writes one semantic frame per
    trace; the time charged to each is the gap from the write before it.
    """
    frames = [
        _frame("2026-11-14T00:00:00Z", "mined trace a -> x"),
        _frame("2026-11-14T00:00:30Z", "semantic edges over 1 card"),
        _frame("2026-11-14T00:00:50Z", "mined trace b -> y"),
        _frame("2026-11-14T00:01:50Z", "semantic edges over 2 cards"),
    ]

    assert semantic_cost(frames) == {"calls": 2, "seconds": 90.0}


def test_a_journal_with_no_semantic_frame_costs_nothing():
    frames = [_frame("2026-11-14T00:00:00Z", "mined trace a -> x")]

    assert semantic_cost(frames) == {"calls": 0, "seconds": 0.0}


def test_a_frame_without_a_timestamp_is_skipped_not_counted():
    frames = [
        _frame("2026-11-14T00:00:00Z", "mined trace a -> x"),
        {"reason": "semantic edges over 1 card"},
    ]

    assert semantic_cost(frames) == {"calls": 0, "seconds": 0.0}
