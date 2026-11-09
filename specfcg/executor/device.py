"""Device protocol plus fake and uiautomator2 implementations."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

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

    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial
        self._device = None

    def _d(self):
        if self._device is None:
            import uiautomator2 as u2

            if self.serial:
                self._device = u2.connect(self.serial)
            else:
                self._device = u2.connect()
        return self._device

    def start_app(self, app: str) -> None:
        self._d().app_start(app)

    def dump_ui(self) -> str:
        return self._d().dump_hierarchy()

    def _locator(self, target: str):
        if target.startswith("text="):
            return self._d()(text=target[len("text=") :])
        if target.startswith("resourceId="):
            return self._d()(resourceId=target[len("resourceId=") :])
        return self._d()(resourceId=target)

    def execute(self, action: str, target: str, args: str = "") -> bool:
        try:
            if action == "click":
                self._locator(target).click()
                return True
            if action == "input":
                self._locator(target).set_text(args)
                return True
            if action == "back":
                self._d().press("back")
                return True
            if action == "swipe":
                coordinates = [int(part) for part in args.split(",")]
                if len(coordinates) != 4:
                    return False
                self._d().swipe(*coordinates)
                return True
            if action == "wait":
                time.sleep(float(args or "1"))
                return True
            logger.warning("unknown action: %s", action)
            return False
        except Exception as exc:  # device failures must not kill a run
            logger.warning("action %s failed: %s", action, exc)
            return False

    def screenshot(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._d().screenshot(str(path))
