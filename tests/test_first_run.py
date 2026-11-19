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
        self._dump = ""

    def shell(self, command: str) -> str:
        if command.startswith("rm -f"):
            self._dump = ""
            return ""
        if command.startswith("cat "):
            return self._dump
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
            parts = (
                self.controls[here].split(",") if here in self.controls else []
            )
            nodes = " ".join(
                f'<node id="{part}" clickable="true"/>'
                for part in parts
                if part
            )
            self._dump = f"<hierarchy>{nodes}</hierarchy>"
            return "UI hierchary dumped to: /sdcard/_ui.xml"
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


def test_a_dialog_inside_the_app_keeps_the_same_focus():
    """Markor's licences notice is a dialog in MainActivity.

    The window keeps focusing the activity, so "the app is in front" does not
    mean the app's own UI is reachable.  The UI has to be read.
    """
    device = FakeDevice(
        screens=["net.gsantner.markor", "net.gsantner.markor"],
        controls={"net.gsantner.markor": "net.gsantner.markor:id/button1"},
    )
    device.dialog_until = 1  # the first look finds the dialog

    state = settle_first_run(device, "net.gsantner.markor", settle_s=0)

    assert state.dismissed >= 1
    assert state.ready is True


def test_all_files_access_is_granted_and_read_back():
    """Without it a build shows an empty directory while files are on disk.

    The permission's own dialog opens a Settings page no in-app click can
    reach, so the experiment grants it and checks the answer rather than
    assuming the shell call worked.
    """
    from specfcg.benchmark.first_run import grant_storage_access

    class Device:
        def __init__(self, granted: bool) -> None:
            self.granted = granted
            self.calls: list[str] = []

        def shell(self, command: str) -> str:
            self.calls.append(command)
            if command.startswith("appops get"):
                return (
                    "MANAGE_EXTERNAL_STORAGE: allow"
                    if self.granted
                    else "MANAGE_EXTERNAL_STORAGE: default"
                )
            if command.startswith("dumpsys package"):
                state = "granted=true" if self.granted else "granted=false"
                return (
                    "android.permission.READ_EXTERNAL_STORAGE: " + state + "\n"
                    "android.permission.WRITE_EXTERNAL_STORAGE: " + state
                )
            return ""

    assert grant_storage_access(Device(True), "com.example") is True
    assert grant_storage_access(Device(False), "com.example") is False


def test_a_button_that_is_text_inside_a_panel_is_tapped_by_coordinate():
    """Markor 0.3.9's licences OK is a non-clickable TextView in a panel.

    A selector click finds the text and fails to act on it, so the dialog
    stayed up and became the agent's start screen.
    """
    class Device:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self._dump = ""

        def shell(self, command: str) -> str:
            if command.startswith("rm -f"):
                self._dump = ""
                return ""
            if command.startswith("cat "):
                return self._dump
            if "dumpsys window" in command:
                return "mCurrentFocus=Window{a u0 net.gsantner.markor/.Main}"
            if "uiautomator dump" in command:
                self._dump = (
                    '<hierarchy><node text="OK" resource-id="" '
                    'class="android.widget.TextView" bounds="[70,1603][1010,1751]"/>'
                    '</hierarchy>'
                )
                return "UI hierchary dumped to: /sdcard/_ui.xml"
            return ""

        def act(self, action: str, target: str) -> bool:
            self.calls.append(target)
            return target.startswith("xy=")

    device = Device()
    state = settle_first_run(device, "net.gsantner.markor", settle_s=0)

    assert state.dismissed >= 1
    assert any(call == "xy=540,1677" for call in device.calls)


def test_a_failed_dump_is_not_read_from_the_previous_file():
    """`uiautomator dump` leaves the old file behind when it fails.

    Reading it acts on a screen that is no longer showing; the control is
    gone, and the selector then waits out its whole timeout before failing.
    One round of settling took 129s because of this.
    """
    class Device:
        """A device whose dump fails, leaving the previous file in place."""

        def __init__(self) -> None:
            self.calls: list[str] = []
            self.file = ""

        def shell(self, command: str) -> str:
            self.calls.append(command)
            if command.startswith("rm -f"):
                self.file = ""
                return ""
            if command.startswith("cat "):
                return self.file
            if "uiautomator dump" in command:
                # The dump fails, so the file keeps its old contents.
                return "ERROR: null root node"
            if "dumpsys window" in command:
                return "mCurrentFocus=Window{a u0 net.gsantner.markor/.Main}"
            return ""

        def act(self, action: str, target: str) -> bool:
            raise AssertionError("must not act on a stale dump")

    device = Device()
    device.file = (
        '<hierarchy><node text="OK" clickable="true" '
        'bounds="[0,0][10,10]"/></hierarchy>'
    )

    state = settle_first_run(device, "net.gsantner.markor", settle_s=0, rounds=1)

    assert state.dismissed == 0
