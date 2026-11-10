"""Thin Android device wrapper for the screenshot-first agent."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from PIL import Image

from specfcg.executor.ui import compact_ui

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
        d = self._d()
        d.app_start(self.package, stop=True)
        time.sleep(2.0)
        for _ in range(14):
            acted = False
            for resource_id in (
                f"{self.package}:id/next",
                f"{self.package}:id/done",
                "com.android.permissioncontroller:id/permission_allow_button",
                "com.google.android.permissioncontroller:id/permission_allow_button",
            ):
                try:
                    element = d(resourceId=resource_id)
                    if element.exists:
                        element.click()
                        time.sleep(0.8)
                        acted = True
                        break
                except Exception:
                    continue
            if acted:
                continue
            for label in ("确定", "OK", "允许", "Allow", "Got it"):
                try:
                    element = d(text=label)
                    if element.exists:
                        element.click()
                        time.sleep(0.8)
                        acted = True
                        break
                except Exception:
                    continue
            if not acted:
                break
        time.sleep(self.settle_s)

    def _scale(self) -> float:
        width, _ = self.size()
        return self.shot_width / width if width else 1.0

    def ui_text(self, max_chars: int = 5000) -> str:
        raw = compact_ui(
            self._d().dump_hierarchy(),
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

    def screenshot(self, path: Path | None = None) -> Image.Image:
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
    ) -> tuple[bool, str]:
        d = self._d()
        try:
            if text and resource_id:
                element = d(text=text, resourceId=resource_id)
            elif text:
                element = d(text=text)
                if not element.exists:
                    element = d(textContains=text)
            elif resource_id:
                element = d(resourceId=resource_id)
            else:
                return False, "FAIL tap needs text or id"
            if not element.exists:
                return False, f"FAIL not found: {text or resource_id}"
            element.click()
            time.sleep(self.settle_s)
            return True, f"OK tapped {text or resource_id}"
        except Exception as exc:
            return False, f"FAIL tap error: {exc}"

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
