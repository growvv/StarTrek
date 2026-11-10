#!/usr/bin/env python3
"""Reset OmniNotes to a clean notes-list screen on the test device."""

from __future__ import annotations

import argparse
import subprocess
import time

import uiautomator2 as u2

PACKAGE = "it.feio.android.omninotes.foss"


def _click_if(device, selector, wait: float = 1.0) -> bool:
    element = device(**selector)
    if not element.exists:
        return False
    element.click()
    time.sleep(wait)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reset-omninotes")
    parser.add_argument("--serial", default=None)
    args = parser.parse_args(argv)

    command = ["adb"]
    if args.serial:
        command += ["-s", args.serial]
    command += ["shell", "pm", "clear", PACKAGE]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        print(completed.stderr.strip())
        return completed.returncode

    device = u2.connect(args.serial) if args.serial else u2.connect()
    device.app_start(PACKAGE, stop=True)
    time.sleep(2)

    for _ in range(10):
        if _click_if(device, {"resourceId": f"{PACKAGE}:id/next"}):
            continue
        if _click_if(device, {"resourceId": f"{PACKAGE}:id/done"}, wait=2):
            continue
        if _click_if(
            device,
            {
                "resourceId": (
                    "com.android.permissioncontroller:id/"
                    "permission_allow_button"
                )
            },
            wait=2,
        ):
            continue
        if _click_if(device, {"text": "确定"}):
            continue
        break

    device.app_start(PACKAGE)
    time.sleep(2)
    home = device(resourceId=f"{PACKAGE}:id/fab_expand_menu_button").exists
    print(f"reset: package={PACKAGE} home={home}")
    return 0 if home else 1


if __name__ == "__main__":
    raise SystemExit(main())
