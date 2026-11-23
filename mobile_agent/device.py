"""Thin Android device wrapper for the screenshot-first agent."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from specfcg.android.ui import compact_ui

_BOUNDS_RE = re.compile(r"bounds='\[(\d+),(\d+)\]\[(\d+),(\d+)\]'")

OVERLAY_PACKAGES = (
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.intentresolver",
    "com.google.android.intentresolver",
)


class AndroidDevice:
    def __init__(
        self,
        serial: str,
        package: str,
        shot_width: int = 720,
        settle_s: float = 0.8,
    ) -> None:
        self.serial = serial
        self.package = package
        self.shot_width = shot_width
        self.settle_s = settle_s
        self._device = None
        self._size: tuple[int, int] | None = None

    def _d(self):
        if self._device is None:
            import uiautomator2 as u2

            self._device = u2.connect(self.serial)
        return self._device

    def size(self) -> tuple[int, int]:
        if self._size is None:
            self._size = tuple(self._d().window_size())
        return self._size

    def start_app(self) -> None:
        """Launch the app and clear the screens it shows before its own UI.

        The clearing used to be a second copy of this logic with its own
        control list, which drifted from `first_run`'s and could not tell a
        blank dump from an empty screen.  There is one implementation now.
        """
        from specfcg.android.first_run import settle_first_run

        self._d().app_start(self.package, stop=True)
        time.sleep(2.0)
        settle_first_run(self, self.package, settle_s=self.settle_s)

    def shell(self, command: str) -> str:
        """Run a device shell command, for the shared Android helpers."""
        result = self._d().shell(command)
        return str(getattr(result, "output", result) or "")

    def act(self, action: str, target: str, args: str = "") -> bool:
        """One UI action, for the shared Android helpers."""
        if action == "click":
            if target.startswith("xy="):
                x, y = target[len("xy=") :].split(",")
                return self.tap_xy(int(x), int(y))[0]
            key, _, value = target.partition("=")
            if key == "text":
                return self.tap(text=value)[0]
            if key == "resourceId":
                return self.tap(resource_id=value)[0]
            if key in ("desc", "description"):
                return self.tap(description=value)[0]
            return False
        if action == "long_click":
            key, _, value = target.partition("=")
            if key == "text":
                return self.long_press(text=value)[0]
            if key == "resourceId":
                return self.long_press(resource_id=value)[0]
            if key in ("desc", "description"):
                return self.long_press(description=value)[0]
            return False
        if action == "back":
            return self.press("back")[0]
        return False

    def _scale(self) -> float:
        width, _ = self.size()
        return self.shot_width / width if width else 1.0

    def activity(self) -> str:
        """The activity on screen, for naming the screen the agent is on.

        Two screens of one app can share every control name; the activity is
        what tells them apart.
        """
        try:
            current = self._d().app_current() or {}
        except Exception:
            return ""
        return str(current.get("activity") or "")

    def ui_text(self, max_chars: int = 5000) -> str:
        # uiautomator returns an empty or failing dump while a window is
        # animating or a keyboard is settling; one retry turns a spurious
        # "the screen is blank" into the screen the agent needs.
        raw_ui = ""
        for attempt in range(4):
            try:
                raw_ui = self._d().dump_hierarchy()
            except Exception as exc:  # noqa: BLE001 -- any dump failure retries
                raw_ui = ""
                # "UiAutomationService ... already registered" means this
                # session's accessibility service outlived the dump that
                # registered it.  Retrying on the same session repeats the
                # failure, so the session is dropped and the next attempt
                # connects again.
                if "already registered" in str(exc):
                    self._device = None
            if raw_ui and "<hierarchy" in raw_ui:
                break
            time.sleep(0.8 * (attempt + 1))
        raw = compact_ui(
            raw_ui,
            self.package,
            extra_packages=OVERLAY_PACKAGES,
        )
        factor = self._scale()

        def repl(match: re.Match[str]) -> str:
            left, top, right, bottom = (int(v) for v in match.groups())
            return (
                f"bounds='[{round(left * factor)},{round(top * factor)}]"
                f"[{round(right * factor)},{round(bottom * factor)}]'"
            )

        return _BOUNDS_RE.sub(repl, raw)[:max_chars]

    def screenshot(self, path: Path | None = None):
        """Capture a screenshot, scaled to the agent's working width.

        Pillow is imported here rather than at module scope: the package is
        part of the offline test suite, and importing it must not require a
        device-side dependency.  A run that never takes a screenshot -- every
        offline test -- never loads it.
        """
        from PIL import Image

        image = self._d().screenshot(format="pillow")
        if not isinstance(image, Image.Image):
            image = Image.open(image)
        image = image.convert("RGB")
        if image.width > self.shot_width:
            height = round(image.height * self.shot_width / image.width)
            image = image.resize((self.shot_width, height), Image.LANCZOS)
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, quality=82)
        return image

    def ui_hash(self) -> str:
        return hashlib.sha1(self.ui_text().encode("utf-8")).hexdigest()[:16]

    def tap(
        self,
        text: str | None = None,
        resource_id: str | None = None,
        description: str | None = None,
    ) -> tuple[bool, str]:
        """Tap a control by its text, resource id, or content description.

        The description is not a fallback for text: an overflow button has no
        text at all, and an icon-only search control has none either.  Leaving
        it out made every such control visible to the agent and untappable.
        """
        d = self._d()
        try:
            if text and resource_id:
                element = d(text=text, resourceId=resource_id)
            elif text:
                element = d(text=text)
                if not element.exists:
                    element = d(textContains=text)
            elif description:
                element = d(description=description)
                if not element.exists:
                    element = d(descriptionContains=description)
            elif resource_id:
                element = d(resourceId=resource_id)
            else:
                return False, "FAIL tap needs text, id, or description"
            if not element.exists:
                return False, f"FAIL not found: {text or resource_id or description}"
            element.click()
            time.sleep(self.settle_s)
            return True, f"OK tapped {text or resource_id or description}"
        except Exception as exc:
            return False, f"FAIL tap error: {exc}"

    def long_press(
        self,
        text: str | None = None,
        resource_id: str | None = None,
        description: str | None = None,
    ) -> tuple[bool, str]:
        """Hold a control to open its selection menu.

        Markor's file operations (rename, details, delete) live behind a long
        press on the row.  Without this action the agent could see a row and
        never reach any of them, and the trace specs' `long_click` had no
        counterpart in the agent's vocabulary.
        """
        d = self._d()
        try:
            if description:
                element = d(description=description)
                if not element.exists:
                    element = d(descriptionContains=description)
            elif text and resource_id:
                element = d(text=text, resourceId=resource_id)
            elif text:
                element = d(text=text)
            elif resource_id:
                element = d(resourceId=resource_id)
            else:
                return False, "FAIL long_press needs text, id, or description"
            if not element.exists:
                return False, f"FAIL not found: {text or resource_id or description}"
            element.long_click()
            time.sleep(self.settle_s)
            return True, f"OK long-pressed {text or resource_id or description}"
        except Exception as exc:
            return False, f"FAIL long_press error: {exc}"

    def tap_xy(self, x: int, y: int) -> tuple[bool, str]:
        factor = self._scale()
        try:
            self._d().click(round(x / factor), round(y / factor))
            time.sleep(self.settle_s)
            return True, f"OK tapped ({x},{y})"
        except Exception as exc:
            return False, f"FAIL tap_xy error: {exc}"

    def type_text(self, text: str) -> tuple[bool, str]:
        d = self._d()
        try:
            focused = d(focused=True)
            if focused.exists:
                focused.set_text(text)
            else:
                d.send_keys(text)
            time.sleep(self.settle_s)
            return True, f"OK typed {text!r}"
        except Exception as exc:
            return False, f"FAIL type error: {exc}"

    def press(self, key: str) -> tuple[bool, str]:
        try:
            self._d().press(key)
            time.sleep(self.settle_s)
            return True, f"OK pressed {key}"
        except Exception as exc:
            return False, f"FAIL press error: {exc}"

    def swipe(self, direction: str) -> tuple[bool, str]:
        try:
            self._d().swipe_ext(direction, scale=0.6)
            time.sleep(self.settle_s)
            return True, f"OK swiped {direction}"
        except Exception as exc:
            return False, f"FAIL swipe error: {exc}"

    def wait(self, seconds: float) -> tuple[bool, str]:
        time.sleep(max(0.2, min(float(seconds), 5.0)))
        return True, f"OK waited {seconds}s"
