"""Importing the package must not require a device-side dependency.

CI installs only ``.[dev]``: no Pillow, no uiautomator2.  That is deliberate —
the offline suite has to run on a bare machine — so a module-level import of a
device-only package breaks every build.  These tests pin the rule rather than
the CI configuration, because the failure looks like a packaging problem when
it is really a lazy-import one.
"""
from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEVICE_ONLY = ("PIL", "uiautomator2")


def test_importing_the_pipeline_does_not_load_device_only_packages():
    code = """
import builtins
real = builtins.__import__
blocked = []
def guard(name, *a, **k):
    root = name.split('.')[0]
    if root in {device_only!r}:
        blocked.append(name)
        raise AssertionError('imported ' + name + ' at import time')
    return real(name, *a, **k)
builtins.__import__ = guard
import specfcg.cli
import specfcg.executor.mobile_agent_backend
import mobile_agent.agent
import mobile_agent.device
print('ok' if not blocked else blocked)
""".format(device_only=list(DEVICE_ONLY))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok", result.stdout


def test_the_device_extra_declares_what_the_lazy_imports_need():
    """A lazy import still has to be declared, or the feature is missing.

    Making Pillow lazy fixes the CI import error; leaving it out of the extra
    would turn that into a screenshot crash on a real device instead.
    """
    # tomllib is 3.11+; the project supports 3.10, so the file is read as text.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    line = next(
        (
            raw
            for raw in text.splitlines()
            if raw.strip().startswith("device = [")
        ),
        "",
    )
    assert line, "no device extra in pyproject.toml"
    assert "pillow" in line.lower()
    assert "uiautomator2" in line
