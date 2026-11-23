"""One lazily-connected uiautomator2 session, shared by every device wrapper.

Two wrappers had each grown their own `_d()`: connect on first use, and — in
one of them — drop the handle when uiautomator answers "UiAutomationService
already registered", because that error means the accessibility service
outlived the dump that registered it and retrying on the same handle repeats
it.  The other wrapper never learned that, so a session that died stayed dead
for the rest of its run and every screen read as blank.

Keeping the connection here means the recovery is written once and both
wrappers get it.  uiautomator2 is imported inside `get()`, not at module
scope: the offline suite runs without it installed.
"""

from __future__ import annotations

# The one error that means "reconnect", not "retry".
_DEAD_SESSION = "already registered"


class DeviceSession:
    """A uiautomator2 handle that reconnects when its session dies."""

    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial
        self._device = None
        self.reconnects = 0

    @property
    def device(self):
        """The live handle, connecting on first use."""
        if self._device is None:
            import uiautomator2 as u2

            self._device = (
                u2.connect(self.serial) if self.serial else u2.connect()
            )
        return self._device

    def replace(self, device) -> None:
        """Install a handle directly, for tests and for injected transports."""
        self._device = device

    @property
    def installed(self):
        """The handle without connecting, or None.

        A wrapper that exposed `_device` for tests kept working when the
        connection moved here; this is the same view without the connect.
        """
        return self._device

    def drop(self) -> None:
        """Forget the handle, so the next use reconnects."""
        self._device = None
        self.reconnects += 1

    def handle_failure(self, error: BaseException) -> bool:
        """React to a failed call; True when the session was dropped.

        Only the dead-session error drops the handle.  A dump that failed
        because a window was animating is retried on the same session, and
        dropping it there would cost a reconnect for nothing.
        """
        if _DEAD_SESSION in str(error):
            self.drop()
            return True
        return False
