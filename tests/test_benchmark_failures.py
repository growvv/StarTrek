from __future__ import annotations

from specfcg.benchmark.failures import classify_failure


def test_success_has_no_failure_type():
    assert (
        classify_failure(
            success=True,
            timed_out=False,
            crashed=False,
            init_error="",
            no_plan=False,
            steps=3,
            max_steps=20,
            looped=False,
            action_failed=False,
            oracle_error="",
        )
        is None
    )


def test_timeout_wins_over_other_signals():
    assert classify_failure(
        success=False,
        timed_out=True,
        crashed=True,
        init_error="x",
        no_plan=True,
        steps=20,
        max_steps=20,
        looped=True,
        action_failed=True,
        oracle_error="",
    ) == "timeout"


def test_init_error_is_reported_before_planning():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="pm clear failed",
        no_plan=True,
        steps=0,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="",
    ) == "init_failure"


def test_no_plan_is_a_graph_gap():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=True,
        steps=0,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="",
    ) == "no_plan"


def test_step_limit():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=False,
        steps=20,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="",
    ) == "step_limit"


def test_loop_detected():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=False,
        steps=8,
        max_steps=20,
        looped=True,
        action_failed=False,
        oracle_error="",
    ) == "loop_detected"


def test_action_failure_before_oracle_failure():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=False,
        steps=4,
        max_steps=20,
        looped=False,
        action_failed=True,
        oracle_error="",
    ) == "action_failure"


def test_oracle_failure_is_the_default():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=False,
        steps=5,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="",
    ) == "goal_oracle_failure"


def test_oracle_error_is_distinct():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=False,
        init_error="",
        no_plan=False,
        steps=5,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="adb unavailable",
    ) == "oracle_error"


def test_app_crash():
    assert classify_failure(
        success=False,
        timed_out=False,
        crashed=True,
        init_error="",
        no_plan=False,
        steps=5,
        max_steps=20,
        looped=False,
        action_failed=False,
        oracle_error="",
    ) == "app_crash"
