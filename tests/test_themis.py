"""The crash-bug dataset is read as the paper's own logs describe it."""
from __future__ import annotations

import json
from pathlib import Path

from specfcg.datasets.themis import (
    BuggyVersion,
    crash_hit,
    load_dataset,
    summarise,
    write_manifest,
)

CRASH = """--------- beginning of crash
01-08 10:16:01.640 23018 23018 E AndroidRuntime: FATAL EXCEPTION: main
01-08 10:16:01.640 23018 23018 E AndroidRuntime: Process: it.feio.android.omninotes.alpha, PID: 23018
01-08 10:16:01.640 23018 23018 E AndroidRuntime: java.lang.NoSuchMethodError: No virtual method fitCenter()
01-08 10:16:01.640 23018 23018 E AndroidRuntime: \tat it.feio.android.simplegallery.GalleryPagerFragment.onCreateView(GalleryPagerFragment.java:86)
01-08 10:16:01.640 23018 23018 E AndroidRuntime: \tat androidx.fragment.app.Fragment.performCreateView(Fragment.java:2600)
01-08 10:16:01.640 23018 23018 E AndroidRuntime: \tat android.os.Handler.handleCallback(Handler.java:751)
"""


def _version(tmp_path: Path, name: str, text: str) -> Path:
    root = tmp_path / "dataset"
    (root / name).mkdir(parents=True)
    (root / name / f"{name}.txt").write_text(text, encoding="utf-8")
    return root


def test_a_crash_is_read_with_its_exception_and_top_frame(tmp_path):
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    versions = load_dataset(root)

    assert len(versions) == 1
    crash = versions[0].crashes[0]
    assert crash.exception == "java.lang.NoSuchMethodError"
    assert crash.frames[0].startswith("it.feio.android.simplegallery")


def test_the_app_key_strips_the_build_flavour(tmp_path):
    """AnkiDroid ships debug and alpha builds of one app.

    Grouping by package would report one app as several and inflate the
    "how many apps" count.
    """
    root = _version(tmp_path, "AnkiDroid-debug-2.9-#4977", CRASH.replace(
        "it.feio.android.omninotes.alpha", "com.ichi2.anki"
    ))
    _version(tmp_path, "AnkiDroid-2.16alpha33-#9914", CRASH.replace(
        "it.feio.android.omninotes.alpha", "com.ichi2.anki.debug"
    ))
    versions = load_dataset(root)

    assert {version.app for version in versions} == {"com.ichi2.anki"}


def test_a_directory_without_a_log_is_not_a_zero(tmp_path):
    """FuncDroid's own runs found no crash in some versions.

    Those directories carry a graph but no recorded bug; counting them as
    "bug not found" would punish a tool for a dataset entry that has no bug.
    """
    root = _version(tmp_path, "AmazeFileManager-3.3.2-#1796", CRASH)
    (root / "AmazeFileManager-3.6.7-#3207").mkdir()

    assert len(load_dataset(root)) == 1


def test_a_run_hits_the_bug_when_the_same_crash_appears(tmp_path):
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    version = load_dataset(root)[0]

    hit = CRASH.replace("10:16:01.640", "11:20:00.001")
    assert crash_hit(hit, version) is True


def test_a_different_crash_is_not_a_hit(tmp_path):
    """Another crash in the same app is not the recorded bug.

    A tool that crashes an app somewhere else has not found the bug the
    dataset is about, and counting it would overstate detection.
    """
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    version = load_dataset(root)[0]

    other = CRASH.replace(
        "it.feio.android.simplegallery.GalleryPagerFragment.onCreateView"
        "(GalleryPagerFragment.java:86)",
        "it.feio.android.omninotes.MainActivity.onResume(MainActivity.java:42)",
    )
    assert crash_hit(other, version) is False


def test_a_crash_from_another_process_is_not_a_hit(tmp_path):
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    version = load_dataset(root)[0]

    other_process = CRASH.replace(
        "Process: it.feio.android.omninotes.alpha", "Process: com.android.systemui"
    )
    assert crash_hit(other_process, version) is False


def test_the_summary_counts_apps_versions_and_distinct_bugs(tmp_path):
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    versions = load_dataset(root)

    summary = summarise(versions)

    assert summary["apps"] == 1
    assert summary["versions"] == 1
    assert summary["distinct_bugs"] == 1


def test_the_manifest_is_written_for_other_tools(tmp_path):
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", CRASH)
    versions = load_dataset(root)
    out = tmp_path / "manifest.json"

    write_manifest(versions, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["versions"][0]["package"] == "it.feio.android.omninotes.alpha"
    assert data["versions"][0]["crashes"][0]["exception"] == "java.lang.NoSuchMethodError"


def test_a_missing_dataset_directory_is_an_error_not_an_empty_result(tmp_path):
    """An empty result would read as "no bugs to find"."""
    import pytest

    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "does-not-exist")


def test_every_recorded_crash_has_to_appear(tmp_path):
    """A version with two failures is a different entry from one with the first.

    AnkiDroid 2.7beta1 records a FileUriExposedException *and* a
    ClassCastException; 2.9alpha4 records only the first.  Accepting either
    crash alone let one log count as a detection of both versions.
    """
    both = CRASH + """
01-08 10:17:00.000 23018 23018 E AndroidRuntime: FATAL EXCEPTION: main
01-08 10:17:00.000 23018 23018 E AndroidRuntime: Process: it.feio.android.omninotes.alpha, PID: 23018
01-08 10:17:00.000 23018 23018 E AndroidRuntime: java.lang.ClassCastException: x
01-08 10:17:00.000 23018 23018 E AndroidRuntime: \tat it.feio.android.omninotes.Other.run(Other.java:7)
"""
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", both)
    version = load_dataset(root)[0]

    assert crash_hit(CRASH, version) is False
    assert crash_hit(both, version) is True


def test_a_platform_crash_is_marked_as_such(tmp_path):
    """A crash with no application frame is Android's, not the app's.

    `FileUriExposedException` is thrown by StrictMode for any app passing a
    `file://` URI, so the identity cannot tell two versions apart on its own.
    """
    platform = """01-08 10:16:01.640 23018 23018 E AndroidRuntime: FATAL EXCEPTION: main
01-08 10:16:01.640 23018 23018 E AndroidRuntime: Process: it.feio.android.omninotes.alpha, PID: 23018
01-08 10:16:01.640 23018 23018 E AndroidRuntime: android.os.FileUriExposedException: exposed
01-08 10:16:01.640 23018 23018 E AndroidRuntime: \tat android.os.StrictMode.onFileUriExposed(StrictMode.java:1)
"""
    root = _version(tmp_path, "Omni-Notes-6.1.0-#745", platform)
    crash = load_dataset(root)[0].crashes[0]

    assert crash.identity.endswith("@platform")
