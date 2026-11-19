"""A control the agent can see has to be a control it can tap.

Android labels many controls only by `content-desc`: the overflow menu, the
wizard's NEXT button, a search icon.  The agent sees them in the UI text it
receives — `ImageView desc='More options' clickable=true` — and then its tap
fails with "tap needs text or id", because the device wrapper had no way to
address a description at all.

The runs showed this as a dead end rather than a crash: Markor's agent tapped
`desc='More options'` at step 2, the call returned FAIL, and the agent
concluded the menu was not on screen.
"""
from __future__ import annotations

from mobile_agent.device import AndroidDevice


class FakeElement:
    def __init__(self, found: bool = True) -> None:
        self.exists = found
        self.clicked = 0

    def click(self) -> None:
        self.clicked += 1


class FakeU2:
    """The few uiautomator2 calls `tap` makes."""

    def __init__(self, by_desc: bool = True) -> None:
        self.by_desc = by_desc
        self.selectors: list[dict] = []

    def __call__(self, **kwargs) -> FakeElement:
        self.selectors.append(kwargs)
        if "description" in kwargs or "descriptionContains" in kwargs:
            return FakeElement(self.by_desc)
        return FakeElement(True)


def _device(u2: FakeU2) -> AndroidDevice:
    device = AndroidDevice("emulator-0", "app.pkg", settle_s=0)
    device._device = u2
    return device


def test_a_description_is_a_tappable_target():
    u2 = FakeU2(by_desc=True)

    ok, message = _device(u2).tap(description="More options")

    assert ok is True
    assert u2.selectors[0] == {"description": "More options"}


def test_a_missing_description_fails_with_a_reason():
    u2 = FakeU2(by_desc=False)

    ok, message = _device(u2).tap(description="Not here")

    assert ok is False
    assert "Not here" in message


def test_text_and_id_still_work():
    u2 = FakeU2()

    assert _device(u2).tap(text="Save")[0] is True
    assert _device(u2).tap(resource_id="app:id/save")[0] is True


def test_the_agent_can_long_press():
    """Selection menus open on a long press, and the agent had no such action.

    Markor's file operations (rename, details, delete) live behind a long
    press on the file row; without it the agent could see the row and never
    reach any of them.
    """
    class Element(FakeElement):
        long_pressed = 0

        def long_click(self) -> None:
            self.long_pressed += 1

    class U2(FakeU2):
        def __call__(self, **kwargs) -> Element:
            self.selectors.append(kwargs)
            return Element(True)

    device = AndroidDevice("emulator-0", "app.pkg", settle_s=0)
    u2 = U2()
    device._device = u2

    ok, message = device.long_press(description="File Readme.md")

    assert ok is True
    assert u2.selectors[0] == {"description": "File Readme.md"}


def test_a_dead_accessibility_session_is_dropped_and_reconnected():
    """`UiAutomationService already registered` repeats on the same session.

    The retry has to reconnect, or every following dump fails the same way and
    the agent reads the screen as blank for the rest of the run.
    """
    class FlakyU2:
        def __init__(self) -> None:
            self.dumps = 0

        def dump_hierarchy(self) -> str:
            self.dumps += 1
            if self.dumps == 1:
                raise RuntimeError(
                    "UiAutomationService ... already registered!"
                )
            return "<hierarchy><node text='ok' package='app.pkg'/></hierarchy>"

    first = FlakyU2()
    second = FlakyU2()
    second.dumps = 1  # its first dump succeeds
    device = AndroidDevice("emulator-0", "app.pkg", settle_s=0)
    device._device = first

    original = device._d

    def reconnect():
        if device._device is None:
            device._device = second
        return device._device

    device._d = reconnect  # type: ignore[method-assign]
    device._scale = lambda: 1.0  # type: ignore[method-assign]

    text = device.ui_text()

    assert "text='ok'" in text
    assert device._device is second
