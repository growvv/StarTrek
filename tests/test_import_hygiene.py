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


def test_the_agent_does_not_import_the_pipeline_package():
    """`mobile_agent` and `specfcg` must not import each other.

    They did: `mobile_agent.device` imported `specfcg.executor.ui` while
    `specfcg.executor.mobile_agent_backend` imported `mobile_agent`.  That is
    a package-level cycle which happens to work while every name resolves, and
    breaks the moment import order changes.  Device-independent helpers live
    in `specfcg.android`, which both sides may import.
    """
    offenders = []
    for path in (ROOT / "mobile_agent").glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("from specfcg") or stripped.startswith("import specfcg")):
                continue
            # The Android helpers are the shared floor, not the pipeline.
            if stripped.startswith(("from specfcg.android", "import specfcg.android")):
                continue
            offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], offenders


def test_the_shared_android_helpers_import_neither_side():
    """The floor must stay a floor, or the cycle comes back through it."""
    for path in (ROOT / "specfcg" / "android").glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith(("from specfcg", "import specfcg", "from mobile_agent", "import mobile_agent")):
                continue
            assert "mobile_agent" not in stripped, f"{path.name}: {stripped}"
            assert "specfcg.executor" not in stripped, f"{path.name}: {stripped}"


def test_launch_settling_has_one_implementation():
    """Two copies of "clear the first-run screens" drifted apart.

    `mobile_agent.start_app` had its own loop with its own control list; it
    could not tell a blank dump from an empty screen and kept clicking at
    controls that were gone.  The shared settler is the only one now.
    """
    text = (ROOT / "mobile_agent" / "device.py").read_text(encoding="utf-8")
    assert "settle_first_run" in text
    # The old copy is recognisable by its own control list.
    assert "permission_allow_button" not in text


def test_the_dataset_and_scoring_packages_stay_off_the_device():
    """They parse files and compute numbers; neither should need a device.

    Keeping them device-free is what lets the offline suite check the
    dataset parsing and the scoring rules without an emulator.
    """
    for package in ("datasets", "scoring"):
        for path in (ROOT / "specfcg" / package).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in ("uiautomator2", "AdbOps", "MobileAgentBackend"):
                assert name not in text, f"{package}/{path.name} uses {name}"
