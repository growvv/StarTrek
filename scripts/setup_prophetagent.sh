#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${PROPHETAGENT_REPO_URL:-https://github.com/ProphetAgent/Home.git}"
TARGET_DIR="${1:-third_party/ProphetAgent}"
COMMIT="97667bfe109e71f57d84a2f7df9bcb03aba55b11"

if [ ! -d "$TARGET_DIR/.git" ]; then
  git clone "$REPO_URL" "$TARGET_DIR"
fi

git -C "$TARGET_DIR" fetch --all --tags
git -C "$TARGET_DIR" checkout "$COMMIT"
