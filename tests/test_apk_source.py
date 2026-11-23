"""An APK is matched to the exact version code the dataset names."""
from __future__ import annotations

from pathlib import Path

import pytest

from specfcg.datasets import apk_source


def _release(tag: str, assets: list[tuple[str, str]]) -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {"name": name, "browser_download_url": url} for name, url in assets
        ],
    }


@pytest.fixture
def fake_releases(monkeypatch):
    def install(releases):
        monkeypatch.setattr(apk_source, "_releases", lambda repo: releases)

    return install


def test_the_asset_version_name_selects_the_exact_build(fake_releases):
    fake_releases(
        [
            _release(
                "v2.8.5",
                [
                    (
                        "net.gsantner.markor-v129-2.8.5-flavorDefault-release.apk",
                        "https://example/129.apk",
                    )
                ],
            )
        ]
    )

    candidate = apk_source.find_apk("net.gsantner.markor", "2.8.5")

    assert candidate.url == "https://example/129.apk"
    assert candidate.asset.endswith("2.8.5-flavorDefault-release.apk")


def test_a_neighbouring_version_is_not_substituted(fake_releases):
    """Installing a nearby build would test something the dataset never saw."""
    fake_releases(
        [
            _release(
                "v2.8.5",
                [
                    (
                        "net.gsantner.markor-v129-2.8.5-release.apk",
                        "https://example/129.apk",
                    )
                ],
            )
        ]
    )

    with pytest.raises(apk_source.ApkUnavailable):
        apk_source.find_apk("net.gsantner.markor", "2.9")


def test_the_tag_can_name_the_version_when_the_asset_does_not(fake_releases):
    fake_releases(
        [
            _release(
                "release-2.16alpha67#11586",
                [("AnkiDroid.apk", "https://example/anki.apk")],
            )
        ]
    )

    candidate = apk_source.find_apk("com.ichi2.anki", "2.16alpha67")

    assert candidate.tag == "release-2.16alpha67#11586"


def test_a_shorter_version_does_not_match_a_longer_one(fake_releases):
    """`2.9` must not pick up `2.9.1`: they are different builds."""
    fake_releases(
        [
            _release("v2.9.1", [("app-2.9.1.apk", "https://example/291.apk")]),
            _release("v2.9", [("app-2.9.apk", "https://example/29.apk")]),
        ]
    )

    assert apk_source.find_apk("net.gsantner.markor", "2.9").url.endswith("29.apk")


def test_an_unknown_app_is_reported_not_guessed():
    with pytest.raises(apk_source.ApkUnavailable, match="no known repository"):
        apk_source.find_apk("com.example.unknown", "1.0")


def test_a_failed_release_listing_is_an_error_not_an_empty_answer(monkeypatch):
    class _Result:
        returncode = 1
        stdout = ""
        stderr = "gh: Not Found"

    monkeypatch.setattr(apk_source.subprocess, "run", lambda *a, **k: _Result())

    with pytest.raises(apk_source.ApkUnavailable, match="cannot list releases"):
        apk_source.find_apk("net.gsantner.markor", "2.8.5")


def test_paginated_output_is_flattened(monkeypatch):
    """`gh api --paginate` concatenates arrays; all of them have to be read."""
    class _Result:
        returncode = 0
        stderr = ""
        stdout = (
            '[{"tag_name":"v1","assets":[]}]'
            '[{"tag_name":"v2","assets":[{"name":"a-v7-x.apk",'
            '"browser_download_url":"https://example/7.apk"}]}]'
        )

    monkeypatch.setattr(apk_source.subprocess, "run", lambda *a, **k: _Result())

    candidate = apk_source.find_apk("net.gsantner.markor", "7")

    assert candidate.tag == "v2"


def test_two_versions_of_one_app_do_not_share_a_file(tmp_path, fake_releases):
    """Keying the file on a code the archive lacks overwrote real downloads.

    Every AnkiDroid version was written to `com.ichi2.anki_0.apk`, so a
    22-version sweep silently kept one binary and reported ten successes.
    """
    fake_releases(
        [
            _release("v2.9", [("a-2.9.apk", "https://example/29.apk")]),
            _release("v2.9.1", [("a-2.9.1.apk", "https://example/291.apk")]),
        ]
    )
    calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        target = Path(args[args.index("-o") + 1])
        target.write_bytes(b"apk")
        return _Result()

    import specfcg.datasets.apk_source as source

    original = source.subprocess.run
    source.subprocess.run = fake_run
    try:
        first = source.download(source.find_apk("com.ichi2.anki", "2.9"), tmp_path)
        second = source.download(source.find_apk("com.ichi2.anki", "2.9.1"), tmp_path)
    finally:
        source.subprocess.run = original

    assert first != second
    assert first.exists() and second.exists()


def test_the_archive_supplies_a_build_github_no_longer_has(monkeypatch):
    """Several dataset builds predate the projects' own release uploads."""
    index = {
        "packages": {
            "net.gsantner.markor": [
                {"versionName": "0.3.9", "apkName": "net.gsantner.markor_23.apk"},
                {"versionName": "0.3.10", "apkName": "net.gsantner.markor_24.apk"},
            ]
        }
    }
    monkeypatch.setattr(apk_source, "_archive_index", lambda *a, **k: index)

    candidate = apk_source.find_in_archive("net.gsantner.markor", "0.3.9")

    assert candidate.url.endswith("net.gsantner.markor_23.apk")
    assert candidate.tag == "f-droid-archive"


def test_the_archive_does_not_substitute_either(monkeypatch):
    index = {
        "packages": {
            "net.gsantner.markor": [
                {"versionName": "0.3.10", "apkName": "net.gsantner.markor_24.apk"}
            ]
        }
    }
    monkeypatch.setattr(apk_source, "_archive_index", lambda *a, **k: index)

    with pytest.raises(apk_source.ApkUnavailable):
        apk_source.find_in_archive("net.gsantner.markor", "0.3.9")
