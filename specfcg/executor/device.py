"""Device protocol plus fake and uiautomator2 implementations."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

from specfcg.executor.ui import compact_ui

logger = logging.getLogger(__name__)


class Device(Protocol):
    def start_app(self, app: str) -> None: ...

    def dump_ui(self) -> str: ...

    def execute(self, action: str, target: str, args: str = "") -> bool: ...

    def screenshot(self, path: Path) -> None: ...


class FakeDevice:
    """Scripted device for offline tests: states and action outcomes."""

    def __init__(
        self,
        states: list[str],
        action_results: list[bool],
    ) -> None:
        self.states = list(states)
        self.action_results = list(action_results)
        self.calls: list[tuple[str, str, str]] = []
        self.app: str | None = None
        self._state_index = 0
        self._result_index = 0

    def start_app(self, app: str) -> None:
        self.app = app

    def dump_ui(self) -> str:
        if not self.states:
            return ""
        index = min(self._state_index, len(self.states) - 1)
        return self.states[index]

    def execute(self, action: str, target: str, args: str = "") -> bool:
        self.calls.append((action, target, args))
        if self._result_index < len(self.action_results):
            result = bool(self.action_results[self._result_index])
            self._result_index += 1
        else:
            result = False
        if self.states:
            self._state_index = min(
                self._state_index + 1, len(self.states) - 1
            )
        return result

    def screenshot(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake screenshot")


class Uiautomator2Device:
    """Real device bridge; imports uiautomator2 only on first use."""

    def __init__(
        self,
        serial: str | None = None,
        settle_s: float = 1.0,
        overlay_packages: tuple[str, ...] = (
            "com.android.intentresolver",
            "com.google.android.intentresolver",
        ),
    ) -> None:
        self.serial = serial
        self.settle_s = settle_s
        self.overlay_packages = overlay_packages
        self._device = None
        self._package: str | None = None

    def _d(self):
        if self._device is None:
            import uiautomator2 as u2

            if self.serial:
                self._device = u2.connect(self.serial)
            else:
                self._device = u2.connect()
        return self._device

    def set_app(self, app: str) -> None:
        """Set the package used to filter UI dumps without launching it."""
        self._package = app

    def start_app(self, app: str, restart: bool = True) -> None:
        """Launch the app's launcher activity.

        ``app_start`` alone resumes whatever activity stack the package left
        behind, so a trace recorded after a previous trace would start in
        that trace's final screen.  Stopping the package first makes every
        recorded trace start from the launcher activity.
        """
        self.set_app(app)
        if restart:
            self._d().app_stop(app)
        self._d().app_start(app)

    def dump_ui(self) -> str:
        return compact_ui(
            self._d().dump_hierarchy(),
            self._package,
            extra_packages=self.overlay_packages,
        )

    _SELECTOR_KEYS = {
        "text": "text",
        "textContains": "textContains",
        "resourceId": "resourceId",
        "desc": "description",
        "descContains": "descriptionContains",
        "description": "description",
        "content-desc": "description",
    }

    # XPath spells the same three attributes differently.
    _XPATH_ATTRS = {
        "text": "text",
        "resourceId": "resource-id",
        "desc": "content-desc",
        "description": "content-desc",
        "content-desc": "content-desc",
    }

    @staticmethod
    def _xpath_literal(value: str) -> str:
        """Quote a value for XPath, choosing a quote it does not contain."""
        if '"' not in value:
            return f'"{value}"'
        if "'" not in value:
            return f"'{value}'"
        return "concat('" + value.replace("'", "',\"'\",'") + "')"

    def _within_locator(self, target: str):
        """Resolve ``within=<anchor>|<selector>`` to the control in that row.

        A list row repeats one button id on every row, and uiautomator2's
        selector kwargs always take the first match, so the row has to be
        part of the query.  Find the node showing the anchor, climb to the
        nearest ancestor that also contains the control, and select the
        control beneath it.  Anchoring on an ancestor rather than a fixed
        depth keeps this independent of the app's layout nesting.
        """
        scope, _, inner = target[len("within=") :].partition("|")
        anchor_key, _, anchor_value = scope.partition("=")
        target_key, _, target_value = inner.partition("=")
        anchor_attr = self._XPATH_ATTRS.get(anchor_key.strip())
        target_attr = self._XPATH_ATTRS.get(target_key.strip())
        if not (anchor_attr and target_attr and anchor_value and target_value):
            return None
        anchor = f"@{anchor_attr}={self._xpath_literal(anchor_value)}"
        control = f"@{target_attr}={self._xpath_literal(target_value)}"
        return self._d().xpath(
            f"//*[{anchor}]"
            f"/ancestor::*[.//*[{control}]][1]"
            f"//*[{control}]"
        )

    def _combined_locator(self, target: str):
        """Resolve ``<selector>|<label>`` to the node that carries both.

        Android puts a control's id on its container and the label the user
        reads on a child ``TextView`` (``LinearLayout id=...:id/menu_new_file``
        holding ``text='文件'``).  Asking for both attributes on one node
        matches nothing, so the label selects *inside* the node the id
        scopes.  When the id is not on any node -- some controls are addressed
        by a label alone -- the plain attribute filter is the fallback.
        """
        parts = [part for part in target.split("|") if part]
        kwargs: dict[str, str] = {}
        for part in parts:
            key, separator, value = part.partition("=")
            mapped = self._SELECTOR_KEYS.get(key.strip())
            if separator and mapped:
                kwargs[mapped] = value
        if not kwargs:
            return None
        scope_key, _, scope_value = parts[0].partition("=")
        label_key, _, label_value = parts[-1].partition("=")
        scope_attr = self._XPATH_ATTRS.get(scope_key.strip())
        label_attr = self._XPATH_ATTRS.get(label_key.strip())
        if not (
            len(parts) >= 2
            and scope_attr
            and label_attr
            and scope_value
            and label_value
            and scope_attr != label_attr
        ):
            return self._d()(**kwargs)
        scope = f"@{scope_attr}={self._xpath_literal(scope_value)}"
        label = f"@{label_attr}={self._xpath_literal(label_value)}"
        # Parenthesized: ``//*[p][1]`` is the first match *per parent*, which
        # is several nodes; the probe needs the single first match.
        return self._d().xpath(
            f"(//*[{scope}][{label} or .//*[{label}]])[1]"
        )

    def _locator(self, target: str):
        if target.startswith("within="):
            return self._within_locator(target)
        if "|" in target:
            return self._combined_locator(target)
        if target.startswith("text="):
            return self._d()(text=target[len("text=") :])
        if target.startswith("textContains="):
            return self._d()(textContains=target[len("textContains=") :])
        if target.startswith("resourceId="):
            return self._d()(resourceId=target[len("resourceId=") :])
        if target.startswith("descContains="):
            return self._d()(descriptionContains=target[len("descContains=") :])
        if target.startswith(("desc=", "description=")):
            return self._d()(description=target.split("=", 1)[1])
        if target.startswith("content-desc="):
            return self._d()(description=target[len("content-desc=") :])
        return self._d()(resourceId=target)

    @staticmethod
    def _label_as_description(target: str) -> str:
        """The same label addressed by content description, or ''.

        A visible label is the ``text`` of some controls and the
        ``content-desc`` of others (an ImageButton overflow menu has no
        text).  A card knows the label, not which attribute carries it, so
        an explicit ``desc=`` or ``resourceId=`` target is left alone.
        """
        if not target.startswith("text="):
            return ""
        label = target[len("text=") :]
        return f"desc={label}" if label else ""

    # A list longer than the screen hides its later rows, and a hidden row
    # is not a missing row: the user scrolls to it.  Scrolling is part of
    # reaching a named control, not a separate plan step.  A swipe that
    # cannot move the list is a signal to stop, not to keep swiping: a
    # control that is absent (a menu item that is not on this screen) must
    # still fail, or the plan would scroll a dialog it cannot move.
    _SCROLL_SWIPES = 6

    def _scroll_to(self, target: str) -> None:
        """Scroll the current list until ``target`` is on screen."""
        width, height = self._d().window_size()
        previous = ""
        for _ in range(self._SCROLL_SWIPES):
            if self._locator(target).exists:
                return
            self._d().swipe(
                width // 2,
                int(height * 0.75),
                width // 2,
                int(height * 0.35),
            )
            if self.settle_s > 0:
                time.sleep(self.settle_s)
            # Compare the raw hierarchy: the compact view drops container
            # nodes, so two different scroll positions can compact to the
            # same text and look like a list that cannot move.
            current = self._d().dump_hierarchy()
            if current == previous:
                return
            previous = current

    def _perform(self, action: str, target: str, args: str) -> None:
        """Run one action, scrolling once when its target is off-screen."""
        if not target or target.startswith("xy="):
            self._invoke(action, target, args)
            return
        try:
            self._invoke(action, target, args)
        except Exception:
            self._scroll_to(target)
            self._invoke(action, target, args)

    def _invoke(self, action: str, target: str, args: str) -> None:
        if action == "click" and target.startswith("xy="):
            x, y = target[len("xy=") :].split(",")
            self._d().click(int(x), int(y))
        elif action == "click":
            try:
                self._locator(target).click()
            except Exception:
                fallback = self._label_as_description(target)
                if not fallback:
                    raise
                self._locator(fallback).click()
        elif action == "long_click":
            self._locator(target).long_click()
        elif action == "input":
            self._locator(target).set_text(args)
        elif action == "back":
            self._d().press("back")
        elif action == "press":
            key = (args or target).strip()
            if not key:
                raise ValueError("press needs a key name or keycode")
            # pressKey resolves key *names* only; a numeric keycode has to
            # go through the shell (``input keyevent 111`` = ESCAPE).
            if key.isdigit():
                self._d().shell(f"input keyevent {key}")
            else:
                self._d().press(key)
        elif action == "swipe":
            coordinates = [int(part) for part in args.split(",")]
            if len(coordinates) != 4:
                raise ValueError(f"swipe needs 4 coordinates, got {args!r}")
            self._d().swipe(*coordinates)
        elif action == "wait":
            time.sleep(float(args or "1"))
        else:
            raise ValueError(f"unknown action: {action}")

    def execute(self, action: str, target: str, args: str = "") -> bool:
        try:
            self._perform(action, target, args)
        except Exception as exc:  # device failures must not kill a run
            logger.warning("action %s failed: %s", action, exc)
            return False
        if self.settle_s > 0:
            time.sleep(self.settle_s)
        return True

    def screenshot(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._d().screenshot(str(path))
