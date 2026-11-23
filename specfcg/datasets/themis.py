"""The Themis crash-bug benchmark, as FuncDroid evaluated it.

FuncDroid's effectiveness evaluation runs on Themis: open-source F-Droid apps,
each pinned to a version that crashes on a known user-level flow.  The dataset
ships as a directory per version holding the crash logcat, the tool's
functional graph and its run log — but not the APKs, which come from each
app's own release archive.

This module reads that dataset and answers the two questions an experiment
needs: which app versions exist, and which crash a run is expected to reach.
It never invents a bug: every entry comes from a logcat line naming the
target package.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# FuncDroid's acceptance rule, copied from its own detector: a crash counts
# when the logcat has a FATAL EXCEPTION naming the target process.  A bare
# "FATAL EXCEPTION" from another process is the system dying around us.
_FATAL_RE = re.compile(r"FATAL EXCEPTION")
_PROCESS_RE = re.compile(r"Process:\s*([A-Za-z0-9_.]+)")
_EXCEPTION_RE = re.compile(
    r"AndroidRuntime:\s*((?:java|android|kotlin)\.[\w.$]+(?:Error|Exception))"
)
# The directory's `#N` is Themis's bug number, not a version code: the
# version is the name before it (`AmazeFileManager-3.3.2-#1796` is Amaze
# 3.3.2).  Treating `#N` as a version code sent the APK lookup after builds
# that do not exist.
_VERSION_RE = re.compile(r"#(\d+)")
# Split the directory on separators and take the token that looks like a
# version: `AmazeFileManager-3.3.2-#1796` -> `3.3.2`, `AnkiDroid-debug-2.9-#4977`
# -> `2.9`, `collect-1.23.0-beta.2-#3222` -> `1.23.0-beta.2`.
_VERSION_NAME_RE = re.compile(
    r"^\d+(?:\.\d+)*(?:[.-]?(?:alpha|beta|rc)[\w.]*)?$"
)
# The logcat's own timestamps identify the run, not the bug; stripping them
# lets two captures of the same crash compare equal.
_TIMESTAMP_RE = re.compile(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\d+\s+\d+\s+")
_FRAME_RE = re.compile(r"at ([\w.$]+)\(([\w.]+:\d+)\)")


@dataclass
class CrashSignature:
    """What the known bug looks like in a logcat.

    ``frames`` is the top of the stack, which is what distinguishes two
    crashes of the same exception type in the same app.
    """

    exception: str = ""
    frames: list[str] = field(default_factory=list)
    message: str = ""
    process: str = ""

    @property
    def identity(self) -> str:
        """A stable key: exception type plus the first frame that is ours.

        A crash with no application frame is a platform-level failure —
        `FileUriExposedException` from `StrictMode` is thrown by Android for
        any app that passes a `file://` URI.  Two versions of one app can
        share such a crash, so its identity is not enough to tell them apart
        and the caller has to add the version.
        """
        app_frame = next(
            (
                frame
                for frame in self.frames
                if not frame.startswith(("java.", "android.", "androidx.", "kotlin."))
            ),
            "",
        )
        if app_frame:
            return f"{self.exception}@{app_frame}"
        return f"{self.exception}@platform"


@dataclass
class BuggyVersion:
    """One app version with a known crash."""

    app: str
    directory: str
    package: str = ""
    version_code: int | None = None
    version_name: str = ""
    crashes: list[CrashSignature] = field(default_factory=list)
    log_path: str = ""

    @property
    def id(self) -> str:
        return self.directory


def _parse_crashes(text: str) -> list[CrashSignature]:
    """Every FATAL EXCEPTION block that names a process."""
    crashes: list[CrashSignature] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _FATAL_RE.search(line):
            continue
        block = lines[index : index + 80]
        process = ""
        exception = ""
        message = ""
        frames: list[str] = []
        for entry in block:
            if not process:
                match = _PROCESS_RE.search(entry)
                if match:
                    process = match.group(1)
                    continue
            if not exception:
                match = _EXCEPTION_RE.search(entry)
                if match:
                    exception = match.group(1)
                    rest = entry.split(match.group(1), 1)[-1].lstrip(": ")
                    message = rest[:200]
                    continue
            match = _FRAME_RE.search(entry)
            if match:
                frames.append(f"{match.group(1)}({match.group(2)})")
                if len(frames) >= 8:
                    break
            elif frames and entry.strip() and "AndroidRuntime" not in entry:
                break
        if process:
            crashes.append(
                CrashSignature(
                    exception=exception,
                    frames=frames,
                    message=message,
                    process=process,
                )
            )
    return crashes


def _app_key(package: str) -> str:
    """The app a package belongs to, with its build flavour removed.

    ``com.amaze.filemanager.debug`` and ``com.amaze.filemanager`` are the
    same app; AnkiDroid ships debug, alpha and beta flavours of one package
    family.  Grouping by flavour would report one app as five.
    """
    for suffix in (".debug", ".alpha", ".beta", ".ting"):
        if package.endswith(suffix):
            return package[: -len(suffix)]
    return package


def load_dataset(root: Path) -> list[BuggyVersion]:
    """Read every version directory that ships a crash log.

    A directory without a ``*.txt`` log carries a graph but no recorded bug
    (FuncDroid's own runs produced no crash there), so it is not part of the
    bug-detection dataset and is skipped rather than counted as a zero.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"no dataset at {root}")
    versions: list[BuggyVersion] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # Only a top-level log beside the graph counts: a nested
        # `coverage_output/coverage.txt` is a tool artefact, not a crash log.
        logs = sorted(entry.glob("*.txt"))
        if not logs:
            continue
        text = logs[0].read_text(encoding="utf-8", errors="replace")
        crashes = _parse_crashes(text)
        package = ""
        match = _PROCESS_RE.search(text)
        if match:
            package = match.group(1)
        if not crashes or not package:
            # The directory ships a graph but no recorded crash: FuncDroid's
            # own run found none there.  It is not a bug entry, so it is not
            # counted — counting it as a miss would punish a tool for a
            # dataset entry that has no bug to find.
            continue
        code = _VERSION_RE.search(entry.name)
        # The bug number (`#N`) is not a version, and `build-N` is a build
        # counter.  Remove both before looking for the version token, so
        # `AnkiDroid-2.16alpha67-debug-#11586` keeps `2.16alpha67`.
        stem = re.sub(r"#\d+", "", entry.name)
        stem = re.sub(r"\bbuild[-_]\d+", "", stem)
        name_match = next(
            (
                token
                for token in re.split(r"[-_ ]", stem)
                if _VERSION_NAME_RE.match(token) and not token.isdigit()
            ),
            None,
        )
        versions.append(
            BuggyVersion(
                app=_app_key(package) or entry.name.split("-")[0].lower(),
                directory=entry.name,
                package=package,
                version_code=int(code.group(1)) if code else None,
                version_name=name_match or "",
                crashes=crashes,
                log_path=str(logs[0]),
            )
        )
    return versions


def crash_hit(logcat: str, version: BuggyVersion) -> bool:
    """Whether a run's logcat contains this version's known crash.

    Matching is on the exception type plus the top application frame, not on
    the message: messages carry run-specific values (a file name, a count),
    and requiring them would make a real crash look like a miss.

    Every crash the dataset recorded for the version has to appear.  A
    version whose log carries two failures is a different entry from one
    carrying only the first, and accepting either alone would let one run
    count as a detection of both — AnkiDroid 2.7beta1 and 2.9alpha4 share a
    `FileUriExposedException` and differ only by the second crash.
    """
    if not version.crashes:
        return False
    wanted = {crash.identity for crash in version.crashes}
    seen = {
        crash.identity
        for crash in _parse_crashes(logcat)
        if crash.process == version.package
    }
    if not wanted.issubset(seen):
        return False
    return True
    if not version.crashes or not version.package:
        return False
    # The crash has to be the app's own: a system process dying around it is
    # not the recorded bug, and FuncDroid's detector makes the same check.
    for crash in _parse_crashes(logcat):
        if crash.process != version.package:
            continue
        if crash.identity in {c.identity for c in version.crashes}:
            return True
        # An app can crash at the same place with a different message; the
        # exception type and top frame are the identity, so compare those.
        for expected in version.crashes:
            if (
                crash.exception == expected.exception
                and crash.frames[:1] == expected.frames[:1]
            ):
                return True
    return False


def summarise(versions: list[BuggyVersion]) -> dict:
    """The dataset's shape: how many apps, versions and distinct bugs."""
    apps: dict[str, dict] = {}
    for version in versions:
        entry = apps.setdefault(
            version.app, {"versions": 0, "bugs": set(), "crashes": 0}
        )
        entry["versions"] += 1
        entry["crashes"] += len(version.crashes)
        for crash in version.crashes:
            entry["bugs"].add(crash.identity)
    return {
        "apps": len(apps),
        "versions": len(versions),
        "distinct_bugs": sum(len(v["bugs"]) for v in apps.values()),
        "per_app": {
            app: {
                "versions": data["versions"],
                "distinct_bugs": len(data["bugs"]),
                "crashes": data["crashes"],
            }
            for app, data in sorted(apps.items())
        },
    }


def write_manifest(versions: list[BuggyVersion], path: Path) -> None:
    """Write the dataset in a form another tool can read without this code."""
    payload = {
        "source": "Themis, as evaluated by FuncDroid",
        "versions": [
            {
                "id": version.id,
                "app": version.app,
                "package": version.package,
                "version_code": version.version_code,
                "version_name": version.version_name,
                "crashes": [
                    {
                        "exception": crash.exception,
                        "identity": crash.identity,
                        "frames": crash.frames,
                    }
                    for crash in version.crashes
                ],
            }
            for version in versions
        ],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
