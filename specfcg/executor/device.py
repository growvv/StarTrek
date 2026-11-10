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

    def start_app(self, app: str) -> None:
        self.set_app(app)
        self._d().app_start(app)

    def dump_ui(self) -> str:
        return compact_ui(
            self._d().dump_hierarchy(),
            self._package,
            extra_packages=self.overlay_packages,
        )

    _SELECTOR_KEYS = {
        "text": "text",
        "resourceId": "resourceId",
        "desc": "description",
        "description": "description",
        "content-desc": "description",
    }

    def _locator(self, target: str):
        if "|" in target:
            kwargs: dict[str, str] = {}
            for part in target.split("|"):
                key, separator, value = part.partition("=")
                mapped = self._SELECTOR_KEYS.get(key.strip())
                if separator and mapped:
                    kwargs[mapped] = value
            if kwargs:
                return self._d()(**kwargs)
        if target.startswith("text="):
            return self._d()(text=target[len("text=") :])
        if target.startswith("resourceId="):
            return self._d()(resourceId=target[len("resourceId=") :])
        if target.startswith(("desc=", "description=")):
            return self._d()(description=target.split("=", 1)[1])
        if target.startswith("content-desc="):
            return self._d()(description=target[len("content-desc=") :])
        return self._d()(resourceId=target)

    def execute(self, action: str, target: str, args: str = "") -> bool:
        try:
            if action == "click":
                self._locator(target).click()
            elif action == "input":
                self._locator(target).set_text(args)
            elif action == "back":
                self._d().press("back")
            elif action == "press":
                key = (args or target).strip()
                if not key:
                    return False
                self._d().press(key)
            elif action == "swipe":
                coordinates = [int(part) for part in args.split(",")]
                if len(coordinates) != 4:
                    return False
                self._d().swipe(*coordinates)
            elif action == "wait":
                time.sleep(float(args or "1"))
                return True
            else:
                logger.warning("unknown action: %s", action)
                return False
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
