"""Get a freshly installed app past the screens it shows before its own UI.

Every one of these dialogs is outside the app: a permission grant, a licences
notice, a "what's new" panel.  An agent that meets one has to spend steps
dismissing it, and a small agent spends all of them — Markor 0.3.9 opens a
licences dialog on first launch, and the agent looked at it and reported the
task done.

Dismissing them is the experiment's job, not the agent's: the measurement is
about the app's functions, and a build's own onboarding is not a function.
Each handler names a control that only appears on that dialog, so a screen
that merely looks similar is left alone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Controls that exist only on a first-run or system dialog.  The value is what
# to click to leave the app usable: `OK` on a licences notice, `Allow` on a
# permission prompt.
DISMISS_CONTROLS = (
    # Android 13 notification permission.
    "com.android.permissioncontroller:id/permission_allow_button",
    # Storage / all-files permission, and the legacy dialog's OK.
    "com.android.permissioncontroller:id/permission_allow_foreground_only_button",
    "android:id/button1",
    # Markor's licences notice.
    "net.gsantner.markor:id/button1",
)

# Text a dialog shows; clicking the matching button is what closes it.  Kept
# separate from ids because some builds use the platform button.
DISMISS_TEXTS = ("OK", "Allow", "ALLOW", "确定", "允许", "Got it", "Close")

# Screens that are not the app at all: the package installer, the settings
# page an all-files grant opens.
FOREIGN_PACKAGES = (
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.settings",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
)

# Storage permissions, by the mechanism the build was written for.  A 2018
# build asks for READ/WRITE_EXTERNAL_STORAGE (runtime permissions, granted by
# `pm grant`); a 2021+ build asks for MANAGE_EXTERNAL_STORAGE (an appop whose
# dialog opens a Settings page).  Granting only one leaves the other build
# showing an empty directory while its files sit on disk, so every file task
# would fail for a reason that has nothing to do with the app.
RUNTIME_STORAGE_PERMISSIONS = (
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
)
APPOPS_STORAGE_PERMISSIONS = ("MANAGE_EXTERNAL_STORAGE",)


@dataclass
class LaunchState:
    """Where the app ended up after its first-run screens were cleared."""

    package: str
    foreground: str = ""
    dismissed: int = 0
    stuck_on: str = ""

    @property
    def ready(self) -> bool:
        return self.foreground == self.package


def grant_storage_access(device, package: str) -> bool:
    """Give the build all-files access, which it cannot ask for itself.

    `pm clear` keeps appops grants but a fresh install has none, and the
    dialog for this permission opens a Settings page outside the app.  The
    check is read back so a failed grant is reported rather than assumed.
    """
    granted = True
    for permission in RUNTIME_STORAGE_PERMISSIONS:
        device.shell(f"pm grant {package} {permission}")
    for operation in APPOPS_STORAGE_PERMISSIONS:
        device.shell(f"appops set {package} {operation} allow")
    # Read back whichever mechanism this build actually declares: a 2018 build
    # has no MANAGE_EXTERNAL_STORAGE line at all, and demanding it would call
    # a working grant a failure.
    declared = device.shell(f"dumpsys package {package}")
    for permission in RUNTIME_STORAGE_PERMISSIONS:
        if permission in declared and f"{permission}: granted=true" not in declared:
            granted = False
    if "MANAGE_EXTERNAL_STORAGE" in device.shell(
        f"appops get {package} MANAGE_EXTERNAL_STORAGE"
    ):
        if "allow" not in device.shell(
            f"appops get {package} MANAGE_EXTERNAL_STORAGE"
        ):
            granted = False
    return granted


def settle_first_run(
    device,
    package: str,
    *,
    rounds: int = 6,
    settle_s: float = 1.5,
) -> LaunchState:
    """Clear the dialogs a freshly installed build shows before its own UI.

    Bounded on purpose: an app that never leaves its dialogs is reported as
    stuck rather than clicked at forever.  A build that needs a permission
    nobody can grant without a human is a build this experiment cannot run,
    and saying so is more useful than a run that measures the dialog.
    """
    state = LaunchState(package=package)
    for _ in range(rounds):
        state.foreground = _foreground(device)
        if state.foreground == package:
            # A dialog drawn by the app itself keeps the window focused on the
            # activity, so focus alone cannot tell "ready" from "blocked":
            # Markor's licences notice is a dialog *in* MainActivity.  The UI
            # has to be read to know whether a dismissable control is showing.
            if not _dismiss_once(device):
                # The control may be present but unclickable the first time;
                # give it one more look before calling the app ready, or a
                # dialog that stays up silently becomes the agent's start.
                time.sleep(settle_s)
                state.foreground = _foreground(device)
                if state.foreground == package and _dismiss_once(device):
                    state.dismissed += 1
                    time.sleep(settle_s)
                    continue
                return state
            state.dismissed += 1
            time.sleep(settle_s)
            continue
        if state.foreground not in FOREIGN_PACKAGES:
            # Not a known dialog and not the app: back out once, then stop.
            device.shell("input keyevent 4")
            time.sleep(settle_s)
            state.foreground = _foreground(device)
            if state.foreground == package:
                return state
            state.stuck_on = state.foreground
            return state
        if _dismiss_once(device):
            state.dismissed += 1
            time.sleep(settle_s)
            continue
        state.stuck_on = state.foreground
        return state
    state.stuck_on = state.foreground
    return state


def _foreground(device) -> str:
    """The package whose window has focus."""
    import re

    text = device.shell("dumpsys window")
    # `mCurrentFocus=Window{hash u0 <package>/<activity>}` — the package is
    # what matters, and a fake may hand back the package alone.
    match = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+?)(?:/[\w.$]+)?\}", text)
    return match.group(1) if match else ""


def _dismiss_once(device) -> bool:
    """Click one control that closes a first-run dialog, if one is there.

    One dump decides what to try.  Asking the device for each control in turn
    makes every absent one wait out its selector timeout — four ids and six
    labels is minutes per round — and a settle that slow hides behind its own
    latency.
    """
    ui = _dump(device)
    if not ui:
        return False
    for resource_id in DISMISS_CONTROLS:
        if f'id="{resource_id}"' in ui and _click_attr(
            device, ui, "id", resource_id
        ):
            return True
    for label in DISMISS_TEXTS:
        if f'text="{label}"' in ui and _click_attr(
            device, ui, "text", label
        ):
            return True
    return False


def _dump(device) -> str:
    """A fresh UI dump, or "" when the dump failed.

    `uiautomator dump` leaves the previous file in place when it fails, so a
    plain `cat` hands back a screen that is no longer showing.  Acting on it
    is worse than doing nothing: the control is gone, and the selector then
    waits out its whole timeout before failing.  The file is removed first,
    so a failed dump reads as empty.
    """
    device.shell("rm -f /sdcard/_ui.xml")
    device.shell("uiautomator dump /sdcard/_ui.xml >/dev/null 2>&1")
    ui = device.shell("cat /sdcard/_ui.xml 2>/dev/null")
    return ui if "<hierarchy" in ui else ""


def _click_attr(device, ui: str, attr: str, value: str) -> bool:
    """Click the node carrying this attribute value.

    A selector click on a non-clickable node does not fail fast: it waits out
    the selector timeout first.  A node the dump marks `clickable="false"` is
    therefore tapped at its centre directly.
    """
    import re

    pattern = re.compile(
        rf'<node\b[^>]*{attr}="{re.escape(value)}"[^>]*>'
    )
    match = pattern.search(ui)
    if not match:
        return False
    node = match.group(0)
    clickable = 'clickable="true"' in node
    selector = (
        f"resourceId={value}" if attr == "id" else f"text={value}"
    )
    if clickable:
        return device.act("click", selector)
    bounds = re.search(
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node
    )
    if not bounds:
        return False
    left, top, right, bottom = (int(v) for v in bounds.groups())
    return device.act(
        "click", f"xy={(left + right) // 2},{(top + bottom) // 2}"
    )



