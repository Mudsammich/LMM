"""The deployment engine: turns an ordered list of enabled mods into
symlinks (or hardlinks) inside the game's real Data directory, and can
cleanly undo exactly what it created.

Design mirrors the "simple" conflict model used by MO2/Vortex: mods are
applied in priority order and a later mod's file silently overwrites an
earlier mod's link at the same relative path. Every overwritten path is
reported as a conflict so the UI can surface it.

Nothing here ever touches a file it didn't create itself - undeploy only
removes symlinks it finds recorded in the deployed-files manifest, and
only if they still point back into the managed mods directory.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..models import DeployMethod, InstalledMod


@dataclass
class DeployPlan:
    # relative posix path -> absolute source file that will "win" that path
    links: dict[str, Path] = field(default_factory=dict)
    # relative posix path -> ordered list of mod ids that provide it (len > 1)
    conflicts: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DeployResult:
    linked: int
    removed: int
    conflicts: dict[str, list[str]]


# Installer metadata, not game content - never deployed. Kept in staging
# though, since that's where the FOMOD installer reads it from.
_NON_CONTENT_TOP_LEVEL = {"fomod"}


def scan_mod_files(mod_root: Path) -> list[Path]:
    """All regular files under mod_root, as paths relative to mod_root."""
    if not mod_root.is_dir():
        return []
    found = []
    for p in mod_root.rglob("*"):
        if not (p.is_file() or p.is_symlink()):
            continue
        rel = p.relative_to(mod_root)
        if rel.parts and rel.parts[0].lower() in _NON_CONTENT_TOP_LEVEL:
            continue
        found.append(rel)
    return found


class CaseRegistry:
    """Picks one canonical spelling per case-insensitively-equal path, so
    mods that disagree about capitalisation merge into a single folder
    instead of landing as siblings.

    Windows and NTFS are case-insensitive, so mod authors capitalise
    however they like and the game never notices. On Linux those are
    genuinely different directories, which is why an unmerged deploy leaves
    ``Textures`` sitting next to ``textures`` (and ``Meshes``/``meshes``,
    ``Scripts``/``SCRIPTS``) in the game's Data folder, with the game
    reliably finding only one of them.

    First spelling registered wins, so seeding from the game's own Data
    directory before the mods makes LMM adopt the *game's* capitalisation
    rather than whichever mod happened to deploy first.
    """

    def __init__(self) -> None:
        # case-folded relative path -> canonical spelling of its last part
        self._canonical: dict[str, str] = {}

    def seed_from_dir(self, root: Path) -> None:
        """Registers the directory names already present under ``root``.
        Directories only - files are the things mods replace, and walking
        every file in a modded Data folder would be needlessly slow."""
        if not root.is_dir():
            return
        for dirpath, dirnames, _files in os.walk(root, followlinks=False):
            base = Path(dirpath).relative_to(root)
            for name in dirnames:
                self.canonical(base / name)

    def canonical(self, rel_path: Path) -> str:
        """The canonical spelling of ``rel_path``, registering any part not
        seen before. Two paths differing only in case always come back
        identical, which is what makes them merge."""
        out: list[str] = []
        folded: list[str] = []
        for part in rel_path.parts:
            folded.append(part.lower())
            key = "/".join(folded)
            existing = self._canonical.get(key)
            if existing is None:
                self._canonical[key] = part
                out.append(part)
            else:
                out.append(existing)
        return "/".join(out)


def build_plan(
    mods_dir: Path,
    ordered_mods: list[InstalledMod],
    target_dir: Path | None = None,
) -> DeployPlan:
    """``ordered_mods`` must already be filtered to enabled mods and sorted
    by ascending priority (last one wins conflicts).

    ``target_dir`` is the game's real deploy directory. Passing it lets
    case-merging adopt the game's own folder capitalisation; it's only
    read from, never written to, so callers that just want a preview can
    pass it safely.
    """
    plan = DeployPlan()
    providers: dict[str, list[str]] = {}

    registry = CaseRegistry()
    if target_dir is not None:
        registry.seed_from_dir(Path(target_dir))

    for mod in ordered_mods:
        mod_root = mods_dir / mod.staging_subdir
        for rel_path in scan_mod_files(mod_root):
            # The canonical path doubles as the merge key: paths differing
            # only in case canonicalise to the same string, so they land on
            # one link and register as a conflict, exactly as they would
            # have on Windows.
            key = registry.canonical(rel_path)
            plan.links[key] = mod_root / rel_path
            providers.setdefault(key, []).append(mod.id)

    plan.conflicts = {k: v for k, v in providers.items() if len(v) > 1}
    return plan


def _deployed_manifest_path(state_dir: Path) -> Path:
    return state_dir / "deployed.json"


def apply_plan(
    plan: DeployPlan,
    target_dir: Path,
    state_dir: Path,
    method: DeployMethod = DeployMethod.SYMLINK,
) -> DeployResult:
    """Removes the previous deployment (tracked in state_dir/deployed.json)
    and links the new plan into target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    removed = _remove_tracked_links(target_dir, state_dir)

    linked = 0
    for rel_path, source in plan.links.items():
        dest = target_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        if method == DeployMethod.HARDLINK:
            os.link(source, dest)
        else:
            dest.symlink_to(source)
        linked += 1

    manifest_path = _deployed_manifest_path(state_dir)
    manifest_path.write_text(
        json.dumps({k: str(v) for k, v in plan.links.items()}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return DeployResult(linked=linked, removed=removed, conflicts=plan.conflicts)


def _is_ours(dest: Path, source: Path) -> bool:
    """True if ``dest`` is still the link/hardlink LMM created for
    ``source`` - i.e. safe to remove. A symlink that now points somewhere
    else, or a regular file the user dropped in its place, is left alone.
    """
    if dest.is_symlink():
        try:
            return dest.resolve() == source.resolve()
        except OSError:
            return False
    if dest.is_file() and source.is_file():
        try:
            return dest.stat().st_ino == source.stat().st_ino and dest.stat().st_dev == source.stat().st_dev
        except OSError:
            return False
    return False


def _remove_tracked_links(target_dir: Path, state_dir: Path) -> int:
    manifest_path = _deployed_manifest_path(state_dir)
    if not manifest_path.exists():
        return 0
    tracked: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = 0
    dirs_touched: set[Path] = set()
    for rel, source_str in tracked.items():
        dest = target_dir / rel
        if not (dest.exists() or dest.is_symlink()):
            continue
        if not _is_ours(dest, Path(source_str)):
            continue
        try:
            dest.unlink()
            removed += 1
            dirs_touched.add(dest.parent)
        except FileNotFoundError:
            pass

    # Best-effort cleanup of directories we may have emptied out. Never the
    # deploy target itself - that's the game's real directory, not ours.
    for d in sorted(dirs_touched, key=lambda p: len(p.parts), reverse=True):
        if d == target_dir:
            continue
        try:
            d.rmdir()
        except OSError:
            pass  # not empty, or not ours to remove - leave it alone

    return removed


def undeploy_all(target_dir: Path, state_dir: Path) -> int:
    """Removes every symlink LMM created for this game, without deploying
    a replacement plan."""
    removed = _remove_tracked_links(target_dir, state_dir)
    manifest_path = _deployed_manifest_path(state_dir)
    manifest_path.unlink(missing_ok=True)
    return removed
