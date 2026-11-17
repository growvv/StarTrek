from __future__ import annotations

from specfcg.benchmark.oracles import FinalState, evaluate_oracle


def test_ui_all_requires_every_string():
    state = FinalState(ui_text="Grocery list\nMilk and eggs\nNotes")
    result = evaluate_oracle(
        {"ui_all": ["Grocery list", "Milk and eggs"]}, state
    )
    assert result.success is True

    result = evaluate_oracle(
        {"ui_all": ["Grocery list", "Bread"]}, state
    )
    assert result.success is False
    assert "Bread" in result.reason


def test_ui_match_is_case_insensitive():
    state = FinalState(ui_text="GROCERY LIST")
    assert evaluate_oracle({"ui_all": ["grocery list"]}, state).success


def test_ui_absent_rejects_forbidden_strings():
    state = FinalState(ui_text="Grocery list\nArchive")
    result = evaluate_oracle({"ui_absent": ["grocery"]}, state)
    assert result.success is False
    assert "grocery" in result.reason.lower()


def test_ui_any_needs_one_string():
    state = FinalState(ui_text="复制\n附近分享")
    assert evaluate_oracle(
        {"ui_any": ["Gmail", "附近分享"]}, state
    ).success
    assert not evaluate_oracle(
        {"ui_any": ["Gmail", "QQ"]}, state
    ).success


def test_focus_package_checks_current_window():
    state = FinalState(
        ui_text="", focused_package="com.android.intentresolver"
    )
    assert evaluate_oracle(
        {"focus_package": "intentresolver"}, state
    ).success
    assert not evaluate_oracle(
        {"focus_package": "omninotes"}, state
    ).success


def test_filesystem_oracles_use_collected_state():
    state = FinalState(
        ui_text="",
        files={
            "/sdcard/Documents/a.md": "# hello\nworld",
        },
        dirs={"/sdcard/Documents/Work"},
    )
    ok = evaluate_oracle(
        {
            "fs_exists": ["/sdcard/Documents/a.md"],
            "fs_dir": ["/sdcard/Documents/Work"],
            "fs_content": {"/sdcard/Documents/a.md": ["hello", "world"]},
        },
        state,
    )
    assert ok.success is True

    missing = evaluate_oracle(
        {"fs_exists": ["/sdcard/Documents/b.md"]}, state
    )
    assert missing.success is False
    assert "b.md" in missing.reason


def test_fs_absent_and_not_dir():
    state = FinalState(
        ui_text="",
        files={"/sdcard/Documents/a.md": "x"},
        dirs={"/sdcard/Documents/Work"},
    )
    result = evaluate_oracle(
        {
            "fs_absent": ["/sdcard/Documents/b.md"],
            "fs_not_dir": ["/sdcard/Documents/a.md"],
        },
        state,
    )
    assert result.success is True

    bad = evaluate_oracle({"fs_not_dir": ["/sdcard/Documents/Work"]}, state)
    assert bad.success is False


def test_oracle_reports_evidence_lines():
    state = FinalState(ui_text="Grocery list")
    result = evaluate_oracle({"ui_all": ["Grocery list"]}, state)
    assert "ui_all" in result.evidence
