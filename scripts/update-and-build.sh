#!/usr/bin/env bash
# Sync this checkout to its remote branch and rebuild the Arch package.
#
# Exists because two things reliably trip up doing this by hand:
#
#   1. makepkg rewrites the pkgver= line in PKGBUILD after every build, so
#      the tree is always dirty afterwards and the next `git pull` refuses
#      to run. That edit is generated, never authored, so it's dropped.
#   2. The development branch gets restarted from main after each merge,
#      which rewrites history. `git pull` can't reconcile that and stops
#      with "divergent branches"; worse, it stops *before* the build, so
#      the build silently produces the old version and the package manager
#      reports it as already up to date.
#
# Resetting is the right move here rather than merging: this checkout only
# consumes the branch, it never adds commits to it.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

if ! command -v paru >/dev/null 2>&1; then
	echo "paru not found. It's needed because python-vdf is AUR-only." >&2
	echo "Install it, or run: cd packaging && makepkg -si  (after installing python-vdf)" >&2
	exit 1
fi

branch=$(git rev-parse --abbrev-ref HEAD)

git restore packaging/PKGBUILD 2>/dev/null || true

if [[ -n "$(git status --porcelain)" ]]; then
	echo "Working tree has local changes beyond the generated PKGBUILD version:" >&2
	git status --short >&2
	echo >&2
	echo "Commit, stash or discard them first - this script resets the branch." >&2
	exit 1
fi

echo "==> Fetching origin/$branch"
git fetch origin "$branch"

echo "==> Resetting to origin/$branch"
git reset --hard "origin/$branch"
git --no-pager log --oneline -1

echo "==> Building and installing"
paru -Bi packaging/

# Leave the tree clean so the next run doesn't have to re-do this.
git restore packaging/PKGBUILD 2>/dev/null || true
echo "==> Done."
