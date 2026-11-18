#!/usr/bin/env python3
"""Publish one release: tag, GitHub release, and the site's release page.

The release process is deliberately one command, because a version that exists
as a tag but not on the site (or the reverse) is worse than either alone.

    python scripts/release.py --version 0.1.0 --date 2026-11-18 \
        --title "Stage 1 MVP 与实验环境" --notes-file /tmp/notes.md

``notes.md`` holds the body for the GitHub release.  The structured fields the
site needs (summary, highlights, evidence) are read from the entry that
``--write-yaml`` appends to ``docs/releases.yaml``; this script does not invent
them.

Steps, in order, each of which must succeed:

1. refuse to run with a dirty worktree, an existing tag, or an untagged
   ``docs/releases.yaml`` entry;
2. run the offline test suite;
3. rebuild the site and commit the generated pages with the tag;
4. push ``main``, create and push the tag, create the GitHub release;
5. print the Pages URL so the published page can be checked.

Use ``--dry-run`` to see the commands without running them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "docs" / "releases.yaml"


def run(cmd: list[str], *, dry_run: bool, capture: bool = False) -> str:
    if dry_run:
        print("+", " ".join(cmd))
        return ""
    result = subprocess.run(cmd, cwd=ROOT, capture_output=capture, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(cmd)}\n{detail}")
    return result.stdout if capture else ""


def releases() -> list[dict]:
    raw = yaml.safe_load(RELEASES.read_text(encoding="utf-8")) or {}
    return list(raw.get("releases") or [])


def tag_exists(tag: str, dry_run: bool) -> bool:
    if dry_run:
        return False
    local = subprocess.run(
        ["git", "tag", "-l", tag], cwd=ROOT, capture_output=True, text=True
    )
    if local.stdout.strip():
        return True
    remote = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", tag],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return bool(remote.stdout.strip())


def has_staged_changes() -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=ROOT, capture_output=True
    )
    return result.returncode != 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="e.g. 0.1.0")
    parser.add_argument("--date", required=True, help="ISO date, e.g. 2026-11-18")
    parser.add_argument("--title", required=True)
    parser.add_argument("--notes-file", help="body for the GitHub release")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    tag = f"v{args.version}"

    entries = releases()
    versions = [str(entry.get("version")) for entry in entries]
    if args.version not in versions:
        raise SystemExit(
            f"docs/releases.yaml has no entry for {args.version}; "
            f"add one before releasing (found: {versions})"
        )
    if tag_exists(tag, args.dry_run):
        raise SystemExit(f"tag {tag} already exists")

    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty and not args.dry_run:
        raise SystemExit(
            "worktree is dirty; commit or stash first:\n" + dirty
        )

    run([sys.executable, "-m", "pytest", "-q"], dry_run=args.dry_run)
    run([sys.executable, "scripts/build_site.py"], dry_run=args.dry_run)
    run([sys.executable, "scripts/build_graph_page.py"], dry_run=args.dry_run)

    generated = ["docs/index.html", "docs/demo/index.html", "docs/releases.html",
                 "docs/roadmap.html", "docs/graph/index.html"]
    run(["git", "add", *generated], dry_run=args.dry_run)
    # The site is usually already committed with the source change; only commit
    # when the rebuild actually changed something.
    if args.dry_run or has_staged_changes():
        run(
            ["git", "commit", "-m", f"docs(site): publish {tag} — {args.title}"],
            dry_run=args.dry_run,
        )
    run(["git", "push", "origin", "main"], dry_run=args.dry_run)
    run(["git", "tag", "-a", tag, "-m", f"{tag} — {args.title}"], dry_run=args.dry_run)
    run(["git", "push", "origin", tag], dry_run=args.dry_run)

    if args.notes_file is None:
        raise SystemExit("--notes-file is required to create the GitHub release")
    release_cmd = [
        "gh", "release", "create", tag,
        "--title", f"{tag} — {args.title}",
        "--notes-file", args.notes_file,
    ]
    run(release_cmd, dry_run=args.dry_run)

    print(f"\nsite: https://growvv.github.io/StarTrek/releases.html#{tag}")
    print(f"release: https://github.com/growvv/StarTrek/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
