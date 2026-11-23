"""adb-backed device operations for the benchmark harness.

Only the shell/file/window primitives the harness needs live here; UI actions
go through the existing ``Uiautomator2Device`` so no action code is duplicated.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Callable

Run = Callable[[list[str], bytes | None], tuple[int, bytes]]
Act = Callable[[str, str, str], bool]


def _default_run(
    argv: list[str], stdin: bytes | None = None
) -> tuple[int, bytes]:
    result = subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        timeout=120,
    )
    return result.returncode, result.stdout


def _quote(path: str) -> str:
    return shlex.quote(path)


def _live_ui_dump(serial: str) -> str:
    """Compact UI dump from the real device (only used when not injected)."""
    import uiautomator2 as u2

    from specfcg.android.ui import compact_ui

    return compact_ui(u2.connect(serial).dump_hierarchy())


class AdbOps:
    def __init__(
        self,
        serial: str,
        run: Run | None = None,
        ui_dump: Callable[[], str] | None = None,
        act_fn: Act | None = None,
    ) -> None:
        self.serial = serial
        self.run = run or _default_run
        self.ui_dump = ui_dump
        self.act_fn = act_fn
        self._device = None

    def _exec(
        self, *args: str, stdin: bytes | None = None
    ) -> tuple[int, bytes]:
        return self.run(["adb", "-s", self.serial, *args], stdin)

    def shell(self, command: str) -> str:
        code, out = self._exec("shell", *shlex.split(command))
        return out.decode("utf-8", "replace")

    def write_file(self, path: str, content: str) -> None:
        self._exec(
            "shell",
            "cat",
            ">",
            _quote(path),
            stdin=content.encode("utf-8"),
        )

    def remove(self, path: str) -> None:
        self._exec("shell", f"rm -rf {_quote(path)}")

    def read_file(self, path: str) -> str | None:
        code, out = self._exec("shell", "cat", _quote(path))
        text = out.decode("utf-8", "replace")
        if code != 0 or "No such file" in text or "Permission denied" in text:
            return None
        return text

    def is_dir(self, path: str) -> bool:
        code, out = self._exec("shell", f"stat -c %F {_quote(path)}")
        if code != 0:
            return False
        return "directory" in out.decode("utf-8", "replace").lower()

    def dump_ui(self) -> str:
        if self.ui_dump is not None:
            return self.ui_dump()
        return _live_ui_dump(self.serial)

    def act(self, action: str, target: str, args: str = "") -> bool:
        """One UI action through the shared device bridge."""
        if self.act_fn is not None:
            return self.act_fn(action, target, args)
        from specfcg.executor.device import Uiautomator2Device

        if self._device is None:
            self._device = Uiautomator2Device(self.serial, settle_s=0.8)
        return self._device.execute(action, target, args)

    def install(self, apk) -> bool:
        """Install an APK, replacing whatever is there.

        The package manager refuses a downgrade, so the caller uninstalls
        first; `-r` only makes a same-or-newer reinstall cheap.
        """
        code, out = self._exec("install", "-r", str(apk))
        text = out.decode("utf-8", "replace")
        return code == 0 and "Success" in text

    def uninstall(self, package: str) -> None:
        self._exec("uninstall", package)

    def focused_package(self) -> str:
        code, out = self._exec("shell", "dumpsys", "window")
        text = out.decode("utf-8", "replace")
        match = re.search(
            r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)/", text
        )
        return match.group(1) if match else ""

    def clear_app(self, package: str) -> None:
        self._exec("shell", "pm", "clear", package)

    def launch(self, package: str) -> None:
        self._exec(
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
