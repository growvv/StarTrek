#!/usr/bin/env python3
"""Manage the StarTrek emulator pool.

Every instance this project owns is named ``startrek_*`` and listens in the
5600–5699 range.  Nothing outside those two markers is touched, so a
``start --count`` can never stop or adopt a colleague's emulator, and ``stop``
cannot reach one either.

    python scripts/emulator_pool.py status
    python scripts/emulator_pool.py start --count 4
    python scripts/emulator_pool.py stop
    python scripts/emulator_pool.py install --serial emulator-5600

Ports are allocated in pairs: console on the even port, adb on the next one.
The range starts at 5600 because 5554–5569 belongs to AndroidWorld/MobileWorld
containers and 5560 in particular is mapped by ``mobile_world_env_0``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("ANDROID_HOME", Path.home() / "hdd/android/sdk"))
ADB = SDK / "platform-tools" / "adb"
EMULATOR = SDK / "emulator" / "emulator"
AVDMANAGER = SDK / "cmdline-tools" / "latest" / "bin" / "avdmanager"
AVD_HOME = Path(os.environ.get("ANDROID_AVD_HOME", Path.home() / "hdd/android/avd"))
APPS = Path(os.environ.get("STARTREK_APPS", Path.home() / "hdd/android/apps"))

AVD_PREFIX = "startrek_"
PORT_BASE = 5600
PORT_LIMIT = 5700
SYSTEM_IMAGE = "system-images;android-33;google_apis;x86_64"
DEVICE_PROFILE = "pixel_6"

# Apps the benchmark suite drives.  Installed on every instance so a task can
# start on any of them without a separate provisioning step.
BENCHMARK_APPS = (
    "it.feio.android.omninotes.foss",
    "net.gsantner.markor",
    "com.amaze.filemanager",
    "de.rampro.activitydiary",
)

# Permissions a benchmark app needs before its tasks can run.  These are
# granted once per device rather than per episode: `pm clear` keeps appops
# grants, but an onboarding script cannot reach the all-files screen at all —
# it opens a Settings page outside the app.
APP_OPS = (
    ("net.gsantner.markor", "MANAGE_EXTERNAL_STORAGE"),
    ("com.amaze.filemanager", "MANAGE_EXTERNAL_STORAGE"),
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("ANDROID_HOME", str(SDK))
    env.setdefault("ANDROID_SDK_ROOT", str(SDK))
    env.setdefault("ANDROID_AVD_HOME", str(AVD_HOME))
    env.setdefault("ANDROID_USER_HOME", str(AVD_HOME.parent))
    return env


def owned_avds() -> list[str]:
    """AVD names this project owns."""
    if not AVD_HOME.exists():
        return []
    return sorted(
        p.stem for p in AVD_HOME.glob(f"{AVD_PREFIX}*.ini")
    )


def ports_for(index: int) -> tuple[int, int]:
    console = PORT_BASE + index * 2
    if console >= PORT_LIMIT:
        raise SystemExit(f"port budget exhausted at index {index}")
    return console, console + 1


def _qemu_pids() -> dict[int, str]:
    """Map pid -> AVD name for every emulator process on the machine."""
    found: dict[int, str] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError):
            continue
        args = [a.decode("utf-8", "replace") for a in argv if a]
        if not any("qemu-system" in a for a in args):
            continue
        for i, arg in enumerate(args):
            if arg == "-avd" and i + 1 < len(args):
                found[int(proc.name)] = args[i + 1]
                break
    return found


def owned_instances() -> list[tuple[int, str]]:
    """(pid, avd) for the emulators this project owns."""
    return sorted(
        (pid, avd)
        for pid, avd in _qemu_pids().items()
        if avd.startswith(AVD_PREFIX)
    )


def running_serials() -> list[str]:
    out = subprocess.run(
        [str(ADB), "devices"], capture_output=True, text=True, env=_env()
    ).stdout
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("emulator-"):
            serials.append(parts[0])
    return serials


def our_serials() -> list[str]:
    """Serials inside our port range, whatever their state."""
    result = []
    for serial in running_serials():
        try:
            port = int(serial.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if PORT_BASE <= port < PORT_LIMIT:
            result.append(serial)
    return sorted(result)


def ensure_avds(count: int) -> list[str]:
    """Create ``startrek_1..count`` if they do not exist yet."""
    names = []
    for index in range(1, count + 1):
        name = f"{AVD_PREFIX}{index}"
        ini = AVD_HOME / f"{name}.ini"
        if not ini.exists():
            print(f"creating AVD {name}")
            subprocess.run(
                [
                    str(AVDMANAGER), "create", "avd", "-n", name,
                    "-k", SYSTEM_IMAGE, "-d", DEVICE_PROFILE, "--force",
                ],
                input="no\n",
                text=True,
                check=True,
                env=_env(),
            )
            config = AVD_HOME / f"{name}.avd" / "config.ini"
            if config.exists():
                _tune_config(config)
        names.append(name)
    return names


def _tune_config(config: Path) -> None:
    """Raise RAM and data partition so a benchmark app fits comfortably."""
    wanted = {"hw.ramSize": "3072", "disk.dataPartition.size": "4G"}
    lines = config.read_text(encoding="utf-8").splitlines()
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in wanted:
            lines[i] = f"{key}={wanted[key]}"
            seen.add(key)
    for key, value in wanted.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def start(count: int, wait: bool) -> int:
    names = ensure_avds(count)
    existing = {avd for _, avd in owned_instances()}
    started = []
    for index, name in enumerate(names, start=1):
        if name in existing:
            print(f"{name}: already running")
            continue
        console, _ = ports_for(index - 1)
        log = AVD_HOME / f"{name}.log"
        with log.open("ab") as handle:
            proc = subprocess.Popen(
                [
                    str(EMULATOR), "-avd", name,
                    "-port", str(console),
                    "-no-window", "-no-snapshot", "-no-audio", "-no-boot-anim",
                    "-gpu", "swiftshader_indirect",
                    "-camera-back", "none", "-camera-front", "none",
                ],
                stdout=handle, stderr=subprocess.STDOUT, env=_env(),
            )
        started.append((name, console, proc.pid))
        print(f"{name}: started on port {console} (pid {proc.pid})")
    if wait and started:
        wait_for_boot(started)
    return 0


def wait_for_boot(started: list[tuple[str, int, int]], timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    pending = {f"emulator-{port}": name for name, port, _ in started}
    while pending and time.time() < deadline:
        for serial, name in list(pending.items()):
            out = subprocess.run(
                [str(ADB), "-s", serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, env=_env(),
            ).stdout.strip()
            if out == "1":
                print(f"{name}: booted ({serial})")
                pending.pop(serial)
        if pending:
            time.sleep(3)
    for serial, name in pending.items():
        print(f"{name}: NOT booted after {timeout_s}s ({serial})")


def stop() -> int:
    stopped = 0
    for pid, avd in owned_instances():
        print(f"stopping {avd} (pid {pid})")
        try:
            os.kill(pid, 15)
            stopped += 1
        except ProcessLookupError:
            pass
    deadline = time.time() + 30
    while owned_instances() and time.time() < deadline:
        time.sleep(1)
    for pid, avd in owned_instances():
        print(f"killing {avd} (pid {pid})")
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
    return 0 if stopped or not owned_instances() else 1


def status() -> int:
    instances = owned_instances()
    if not instances:
        print("no startrek_ emulators running")
    for pid, avd in instances:
        print(f"{avd}: pid {pid}")
    for serial in our_serials():
        state = subprocess.run(
            [str(ADB), "-s", serial, "get-state"],
            capture_output=True, text=True, env=_env(),
        ).stdout.strip()
        print(f"  {serial}: {state or 'unknown'}")
    others = [avd for avd in _qemu_pids().values() if not avd.startswith(AVD_PREFIX)]
    if others:
        print(f"\nnot ours ({len(others)}), left alone: {', '.join(sorted(set(others)))}")
    return 0


def install(serials: list[str]) -> int:
    apks = sorted(APPS.glob("*.apk"))
    if not apks:
        raise SystemExit(f"no APKs in {APPS}")
    for serial in serials:
        if serial not in our_serials():
            raise SystemExit(f"{serial} is outside the startrek_ port range")
        for apk in apks:
            print(f"{serial}: installing {apk.name}")
            result = subprocess.run(
                [str(ADB), "-s", serial, "install", "-r", str(apk)],
                capture_output=True, text=True, env=_env(),
            )
            if result.returncode != 0:
                print(f"  failed: {result.stderr.strip()[:200]}")
        for package, op in APP_OPS:
            subprocess.run(
                [str(ADB), "-s", serial, "shell", "appops", "set", package, op, "allow"],
                capture_output=True, text=True, env=_env(),
            )
            print(f"{serial}: appops {package} {op}=allow")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--count", type=int, default=2)
    p_start.add_argument("--no-wait", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("status")
    p_install = sub.add_parser("install")
    p_install.add_argument("--serial", action="append", default=[])
    args = parser.parse_args(argv)

    if args.command == "start":
        return start(args.count, wait=not args.no_wait)
    if args.command == "stop":
        return stop()
    if args.command == "status":
        return status()
    if args.command == "install":
        serials = args.serial or our_serials()
        return install(serials)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
