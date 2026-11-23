"""A dead uiautomator session is a reconnection, not a retry."""
from __future__ import annotations

from specfcg.android.session import DeviceSession


def test_a_dead_session_is_dropped():
    """`UiAutomationService already registered` outlives the dump.

    Retrying on the same handle repeats the failure for the rest of the run,
    so every later screen read as blank. One wrapper had learned this; the
    other had not, because the recovery was written twice.
    """
    session = DeviceSession("emulator-0")
    session.replace(object())

    dropped = session.handle_failure(
        RuntimeError("UiAutomationService ... already registered!")
    )

    assert dropped is True
    assert session.installed is None
    assert session.reconnects == 1


def test_an_ordinary_failure_keeps_the_session():
    """A dump that failed mid-animation is retried on the same handle."""
    session = DeviceSession("emulator-0")
    handle = object()
    session.replace(handle)

    assert session.handle_failure(RuntimeError("null root node")) is False
    assert session.installed is handle
    assert session.reconnects == 0


def test_reconnecting_happens_on_next_use(monkeypatch):
    """The wrapper must not reconnect eagerly; that costs a call per failure."""
    session = DeviceSession("emulator-0")
    session.replace(object())
    session.drop()

    assert session.installed is None
    assert session.reconnects == 1
