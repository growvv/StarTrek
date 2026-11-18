"""Fetch the exact APK a buggy dataset version refers to.

Themis does not ship binaries.  Each version names a F-Droid app at a
specific version code, and every one of these apps is open source, so the
binary lives in its own release archive.  This module maps a dataset entry to
a download URL and verifies that the download is the version asked for.

It refuses rather than guesses: a version whose archive does not carry that
code is reported as unavailable, because installing a neighbouring version
would test a build the dataset says nothing about.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# app key -> GitHub repository whose releases carry the APKs.
REPOSITORIES = {
    "com.amaze.filemanager": "TeamAmaze/AmazeFileManager",
    "com.ichi2.anki": "ankidroid/Anki-Android",
    "de.blau.android": "debauchee/osmeditor4android",
    "de.danoeh.antennapod": "AntennaPod/AntennaPod",
    "de.k3b.android.androFotoFinder": "k3b/APhotoManager",
    "de.rampro.activitydiary": "ramack/ActivityDiary",
    "fr.free.nrw.commons": "commons-app/apps-android-commons",
    "it.feio.android.omninotes": "Frederick888/OmniNotes-Android",
    "net.bible.android.activity": "AndBible/and-bible",
    "net.gsantner.markor": "gsantner/markor",
    "org.odk.collect.android": "getodk/collect",
    "com.eventyay.attendee": "fossasia/open-event-attendee-android",
}

# An asset name usually carries the version code: markor's
# `net.gsantner.markor-v129-2.8.5-...apk`, AnkiDroid's `...-2.16alpha67.apk`
# does not, so the code is also read from the tag when the asset omits it.
_ASSET_CODE_RE = re.compile(r"-v(\d+)[-.]")
_TAG_CODE_RE = re.compile(r"#(\d+)$")


@dataclass
class ApkCandidate:
    app: str
    version: str
    url: str
    asset: str
    tag: str


class ApkUnavailable(RuntimeError):
    """The dataset version has no matching binary in its release archive."""


def _releases(repository: str) -> list[dict]:
    """Every release with its assets, from the gh CLI.

    The REST API is rate-limited per IP and this machine shares one; the CLI
    carries the user's own token, which is what makes a 22-version sweep
    possible in one go.
    """
    result = subprocess.run(
        [
            "gh", "api", f"repos/{repository}/releases", "--paginate",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ApkUnavailable(
            f"cannot list releases for {repository}: {result.stderr.strip()[:200]}"
        )
    # --paginate concatenates JSON arrays; parse each and flatten.
    decoder = json.JSONDecoder()
    text = result.stdout.strip()
    releases: list[dict] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " \n\r\t":
            index += 1
        if index >= len(text):
            break
        value, offset = decoder.raw_decode(text, index)
        releases.extend(value if isinstance(value, list) else [value])
        index = offset
    return releases


def find_apk(app: str, version_name: str) -> ApkCandidate:
    """The release asset that is exactly this version name.

    The dataset names a version (`3.3.2`), and a build's F-Droid code is not
    the same number as the release's own tag, so matching on a code finds
    nothing.  The version name appears in both the tag and the asset name of
    the release that shipped it.
    """
    repository = REPOSITORIES.get(app)
    if repository is None:
        raise ApkUnavailable(f"no known repository for {app}")
    wanted = version_name.strip().lower()
    if not wanted:
        raise ApkUnavailable(f"{app}: the dataset entry names no version")
    for release in _releases(repository):
        tag = str(release.get("tag_name") or "").lower()
        assets = [
            asset
            for asset in release.get("assets") or []
            if str(asset.get("name") or "").endswith(".apk")
        ]
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if _names_version(tag, wanted) or _names_version(name, wanted):
                return ApkCandidate(
                    app=app,
                    version=wanted,
                    url=str(asset.get("browser_download_url") or ""),
                    asset=str(asset.get("name") or ""),
                    tag=str(release.get("tag_name") or ""),
                )
    raise ApkUnavailable(
        f"{app} has no release asset for version {version_name}"
    )


def _names_version(text: str, version: str) -> bool:
    """Whether `text` names this version, without matching a longer one.

    `2.9` must not match `2.9.1` or `2.16alpha9`; the version has to end at a
    separator or the end of the string.
    """
    pattern = rf"(?<![\d.]){re.escape(version)}(?![\d])(?!\.\d)"
    return re.search(pattern, text) is not None


def download(candidate: ApkCandidate, out_dir: Path) -> Path:
    """Download the APK, named by app and version code."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The file name carries the version: keying on a code that the release
    # archive does not expose made every version of one app write the same
    # file, and the last download silently replaced the others.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate.version)
    target = out_dir / f"{candidate.app}_{safe}.apk"
    if target.exists() and target.stat().st_size > 0:
        return target
    # GitHub release assets are reachable only through the host's proxy on
    # this machine; inheriting a proxy-less environment yields an empty
    # download, which is why the failure is reported with the reason rather
    # than as a silent zero.
    result = subprocess.run(
        [
            "curl", "-sL", "--max-time", "600",
            "--retry", "3", "--retry-delay", "2",
            "-o", str(target), candidate.url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        detail = (result.stderr or "").strip()[:200] or f"exit {result.returncode}"
        raise ApkUnavailable(f"download failed for {candidate.url}: {detail}")
    return target


def main(argv: list[str] | None = None) -> int:
    """Fetch every APK a manifest asks for, and report what is missing.

    A missing binary is reported, never substituted: the run that follows
    must know which dataset entries it can actually exercise.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="fetch-themis-apks")
    parser.add_argument(
        "--manifest", default="benchmark/themis/manifest.json"
    )
    parser.add_argument("--out", default="/home/farong/hdd/android/themis")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    out_dir = Path(args.out)
    fetched: list[str] = []
    missing: list[str] = []
    for version in manifest.get("versions") or []:
        if wanted and version["id"] not in wanted:
            continue
        if not version.get("version_name"):
            missing.append(f"{version['id']}: the dataset names no version")
            continue
        try:
            candidate = find_apk(version["app"], version.get("version_name") or "")
            path = download(candidate, out_dir)
        except ApkUnavailable as exc:
            missing.append(f"{version['id']}: {exc}")
            print(f"MISSING {version['id']}: {exc}", flush=True)
            continue
        fetched.append(str(path))
        print(f"ok {version['id']} -> {path.name}", flush=True)

    print(f"\nfetched {len(fetched)}, missing {len(missing)}")
    if missing:
        print("entries this run cannot exercise:")
        for item in missing:
            print("  " + item)
    return 0 if fetched else 1


if __name__ == "__main__":
    raise SystemExit(main())
