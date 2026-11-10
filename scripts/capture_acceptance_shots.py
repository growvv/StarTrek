#!/usr/bin/env python3
"""Capture the OmniNotes user flow for the acceptance report.

Drives the app directly (no LLM) so the report can show what each mined
card's steps do on the real device.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import uiautomator2 as u2
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "it.feio.android.omninotes.foss"
ASSETS = ROOT / "docs" / "reports" / "assets"


def _shot(d, name: str, width: int = 540) -> None:
    image = d.screenshot()
    if not isinstance(image, Image.Image):
        image = Image.open(image)
    ratio = width / image.width
    image = image.resize(
        (width, round(image.height * ratio)), Image.LANCZOS
    )
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / f"{name}.jpg"
    image.convert("RGB").save(path, quality=88)
    print(f"shot: {path}")


def _click(d, selector: dict, wait: float = 1.0) -> bool:
    element = d(**selector)
    if not element.exists:
        print(f"missing: {selector}")
        return False
    element.click()
    time.sleep(wait)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capture-shots")
    parser.add_argument("--serial", default="47261FDAS00DTQ")
    args = parser.parse_args(argv)

    reset = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reset_omninotes.py"),
            "--serial",
            args.serial,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(reset.stdout.strip())
    if reset.returncode != 0:
        print(reset.stderr.strip())
        return reset.returncode

    d = u2.connect(args.serial)
    time.sleep(1)
    _shot(d, "01_notes_list")

    _click(d, {"resourceId": f"{PACKAGE}:id/fab_expand_menu_button"})
    _shot(d, "02_fab_menu")

    _click(d, {"resourceId": f"{PACKAGE}:id/fab_note"}, wait=1.5)
    _shot(d, "03_empty_editor")

    title = d(resourceId=f"{PACKAGE}:id/detail_title")
    title.click()
    title.set_text("Groceries")
    time.sleep(0.5)
    content = d(resourceId=f"{PACKAGE}:id/detail_content")
    content.click()
    content.set_text("Buy milk")
    time.sleep(0.5)
    _shot(d, "04_filled_editor")

    d.press("back")
    time.sleep(1)
    d.press("back")
    time.sleep(1.5)
    _shot(d, "05_saved_note")

    _click(d, {"resourceId": f"{PACKAGE}:id/menu_search"})
    search = d(resourceId=f"{PACKAGE}:id/search_src_text")
    search.set_text("Groceries")
    time.sleep(0.5)
    d.press("enter")
    time.sleep(1.5)
    _shot(d, "06_search_results")

    _click(
        d,
        {
            "resourceId": f"{PACKAGE}:id/note_title",
            "text": "Groceries",
        },
        wait=1.5,
    )
    _shot(d, "07_note_detail")

    _click(d, {"resourceId": f"{PACKAGE}:id/menu_share"}, wait=2)
    _shot(d, "08_share_chooser")

    d.press("back")
    time.sleep(1.5)
    _click(d, {"description": "更多选项"}, wait=1.0)
    _shot(d, "09_archive_menu")
    _click(d, {"text": "归档"}, wait=1.5)
    _shot(d, "10_archived_empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
