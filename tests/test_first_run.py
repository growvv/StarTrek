"""First-run dialogs are cleared by the experiment, not guessed by the agent."""
from __future__ import annotations

from specfcg.benchmark.first_run import LaunchState, settle_first_run


class FakeDevice:
    """A device whose screens change as controls are clicked."""

    def __init__(self, screens: list[str], controls: dict[str, str]) -> None:
        self.screens = screens
        self.controls = controls
        self.index = 0
        self.clicks: list[str] = []
        self.keys: list[str] = []

    def shell(self, command: str) -> str:
        if "dumpsys window" in command:
            return f"mCurrentFocus=Window{{abc u0 {self.screens[self.index]}/.MainActivity}}"
        if command.startswith("input keyevent"):
            self.keys.append(command.split()[-1])
            # Back leaves a foreign wizard; the screen behind it is next.
            self.index = min(self.index + 1, len(self.screens) - 1)
            return ""
        if "uiautomator dump" in command:
            # The current screen exposes every control that leads out of it.
            here = self.screens[self.index]
            ids = " ".join(self.controls[here].split(",")) if here in self.controls else ""
            return ids
        return ""

    def act(self, action: str, target: str) -> bool:
        self.clicks.append(target)
        for screen, controls in self.controls.items():
            if screen != self.screens[self.index]:
                continue
            if any(part and part in target for part in controls.split(",")):
                self.index = min(self.index + 1, len(self.screens) - 1)
                return True
        return False


def test_a_licences_dialog_is_cleared_before_the_agent_runs():
    """Markor 0.3.9 shows a licences notice; the agent read it and stopped."""
    device = FakeDevice(
        screens=["com.android.permissioncontroller", "net.gsantner.markor"],
        controls={
            "com.android.permissioncontroller":
                "com.android.permissioncontroller:id/permission_allow_button",
        },
    )

    state = settle_first_run(device, "net.gsantner.markor", settle_s=0)

    assert state.ready is True
    assert state.dismissed == 1


def test_an_app_already_in_front_is_left_alone():
    device = FakeDevice(screens=["com.example.app"], controls={})

    state = settle_first_run(device, "com.example.app", settle_s=0)

    assert state.ready is True
    assert device.clicks == []


def test_a_dialog_nobody_can_clear_is_reported_not_clicked_forever():
    """A build that cannot get past a dialog is not a run this experiment can make."""
    device = FakeDevice(
        screens=["com.android.settings"] * 10,
        controls={},
    )

    state = settle_first_run(device, "com.example.app", rounds=3, settle_s=0)

    assert state.ready is False
    assert state.stuck_on == "com.android.settings"
    assert len(device.clicks) <= 3


def test_an_unknown_foreign_screen_is_backed_out_of_once():
    device = FakeDevice(
        screens=["com.vendor.wizard", "com.example.app"],
        controls={},
    )

    state = settle_first_run(device, "com.example.app", settle_s=0)

    assert device.keys == ["4"]
    assert state.ready is True


def test_the_licences_button_is_named_so_it_can_be_clicked():
    """The control has to exist in the list, or the dialog is never cleared."""
    from specfcg.benchmark.first_run import DISMISS_CONTROLS

    assert "net.gsantner.markor:id/button1" in DISMISS_CONTROLS
