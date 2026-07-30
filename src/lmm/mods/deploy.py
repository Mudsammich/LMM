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

from ..models import (
    DEPLOY_ROOT_AUTO,
    DEPLOY_ROOT_DATA,
    DEPLOY_ROOT_GAME,
    DeployMethod,
    InstalledMod,
)

# Files that can only work sitting next to the game executable: script
# extender loaders, ASI/DLL plugin loaders, and graphics injectors like ENB
# or ReShade. The game never looks for these inside its data folder.
_ROOT_ONLY_SUFFIXES = {".dll", ".exe", ".asi"}


def detect_deploy_root(mod_root: Path) -> str:
    """Whether a mod's staged files are laid out relative to the game's
    data folder (the normal case) or to the game's root directory.

    Two signals, both unambiguous for Bethesda games:

    - A top-level ``Data`` folder. The data folder *is* the normal deploy
      target, so a mod containing one must be describing paths from the
      game root - that's how script extender plugins ship (a loader .dll at
      the root plus ``Data/F4SE/Plugins/...``). Note archives that are
      *only* a ``Data`` wrapper have already had it stripped at install
      time, so one surviving here is meaningful.
    - A top-level ``.dll``/``.exe``/``.asi``. These do nothing from inside
      the data folder, so their presence at the top level means the mod is
      root-relative even when it ships no ``Data`` folder at all (ENB and
      ReShade are packaged exactly like this).
    """
    try:
        entries = list(mod_root.iterdir())
    except OSError:
        return DEPLOY_ROOT_DATA
    for entry in entries:
        if entry.is_dir():
            if entry.name.lower() == "data":
                return DEPLOY_ROOT_GAME
        elif entry.suffix.lower() in _ROOT_ONLY_SUFFIXES:
            return DEPLOY_ROOT_GAME
    return DEPLOY_ROOT_DATA


def resolve_deploy_root(mod: InstalledMod, mod_root: Path) -> str:
    """The mod's effective deploy root, honouring a manual override."""
    if mod.deploy_root in (DEPLOY_ROOT_DATA, DEPLOY_ROOT_GAME):
        return mod.deploy_root
    return detect_deploy_root(mod_root)


@dataclass
class DeployPlan:
    # game-root-relative posix path -> absolute source file that "wins" it
    links: dict[str, Path] = field(default_factory=dict)
    # game-root-relative posix path -> ordered mod ids providing it (len > 1)
    conflicts: dict[str, list[str]] = field(default_factory=dict)
    # mod id -> the deploy root it resolved to, for the UI to show
    deploy_roots: dict[str, str] = field(default_factory=dict)


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
    deploy_subpath: str = "",
    target_dir: Path | None = None,
) -> DeployPlan:
    """``ordered_mods`` must already be filtered to enabled mods and sorted
    by ascending priority (last one wins conflicts).

    Every path in the returned plan is relative to the **game root**, not
    the data folder: a data-relative mod's files get ``deploy_subpath``
    prefixed, and a root-relative mod's are used as-is. Keeping one
    namespace means conflicts and case-merging work across both kinds -
    a root mod's ``Data/F4SE/Plugins/x.dll`` correctly collides with a data
    mod's ``F4SE/Plugins/x.dll``, which two separate plans couldn't see.

    ``target_dir`` is the game's root directory. Passing it lets
    case-merging adopt the game's own folder capitalisation; it's only read
    from, never written to, so a caller that just wants a preview can pass
    it safely.
    """
    plan = DeployPlan()
    providers: dict[str, list[str]] = {}

    registry = CaseRegistry()
    if target_dir is not None:
        registry.seed_from_dir(Path(target_dir))

    data_prefix = deploy_subpath.strip("/")

    for mod in ordered_mods:
        mod_root = mods_dir / mod.staging_subdir
        root_mode = resolve_deploy_root(mod, mod_root)
        plan.deploy_roots[mod.id] = root_mode
        for rel_path in scan_mod_files(mod_root):
            if root_mode == DEPLOY_ROOT_DATA and data_prefix:
                dest_rel = Path(data_prefix) / rel_path
            else:
                dest_rel = rel_path
            # The canonical path doubles as the merge key: paths differing
            # only in case canonicalise to the same string, so they land on
            # one link and register as a conflict, exactly as they would
            # have on Windows.
            key = registry.canonical(dest_rel)
            plan.links[key] = mod_root / rel_path
            providers.setdefault(key, []).append(mod.id)

    plan.conflicts = {k: v for k, v in providers.items() if len(v) > 1}
    return plan


def _deployed_manifest_path(state_dir: Path) -> Path:
    return state_dir / "deployed.json"


def apply_plan(
    plan: DeployPlan,
    game_root: Path,
    state_dir: Path,
    method: DeployMethod = DeployMethod.SYMLINK,
    legacy_base: Path | None = None,
) -> DeployResult:
    """Removes the previous deployment (tracked in state_dir/deployed.json)
    and links the new plan into ``game_root``.

    ``legacy_base`` is the data folder, used only to interpret manifests
    written before deployment moved to game-root-relative paths - without
    it, upgrading would orphan every link from the previous deploy.
    """
    game_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    protected = {game_root} | ({legacy_base} if legacy_base else set())
    removed = _remove_tracked_links(state_dir, protected, legacy_base)

    linked = 0
    deployed: dict[str, str] = {}
    for rel_path, source in plan.links.items():
        dest = game_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        if method == DeployMethod.HARDLINK:
            os.link(source, dest)
        else:
            dest.symlink_to(source)
        deployed[str(dest)] = str(source)
        linked += 1

    manifest_path = _deployed_manifest_path(state_dir)
    manifest_path.write_text(
        json.dumps({"version": 2, "links": deployed}, indent=2, sort_keys=True),
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


def _read_tracked(state_dir: Path, legacy_base: Path | None) -> list[tuple[Path, Path]]:
    """(destination, source) pairs from the deployed manifest.

    Version 2 records absolute destinations, so it needs no base directory
    and can't be misread if the deploy target changes. Version 1 (a flat
    ``{relative path: source}`` map) predates root-relative deployment and
    is resolved against the data folder it was written for.
    """
    manifest_path = _deployed_manifest_path(state_dir)
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, dict) and data.get("version") == 2:
        return [(Path(dest), Path(src)) for dest, src in (data.get("links") or {}).items()]
    if legacy_base is None:
        return []
    return [(Path(legacy_base) / rel, Path(src)) for rel, src in data.items()]


def _remove_tracked_links(
    state_dir: Path,
    protected_dirs: set[Path],
    legacy_base: Path | None = None,
) -> int:
    removed = 0
    dirs_touched: set[Path] = set()
    for dest, source in _read_tracked(state_dir, legacy_base):
        if not (dest.exists() or dest.is_symlink()):
            continue
        if not _is_ours(dest, source):
            continue
        try:
            dest.unlink()
            removed += 1
            dirs_touched.add(dest.parent)
        except FileNotFoundError:
            pass

    # Best-effort cleanup of directories we may have emptied out. Never the
    # game's own directories - those aren't ours to remove.
    for d in sorted(dirs_touched, key=lambda p: len(p.parts), reverse=True):
        if d in protected_dirs:
            continue
        try:
            d.rmdir()
        except OSError:
            pass  # not empty, or not ours to remove - leave it alone

    return removed


def undeploy_all(game_root: Path, state_dir: Path, legacy_base: Path | None = None) -> int:
    """Removes every symlink LMM created for this game, without deploying
    a replacement plan."""
    protected = {game_root} | ({legacy_base} if legacy_base else set())
    removed = _remove_tracked_links(state_dir, protected, legacy_base)
    manifest_path = _deployed_manifest_path(state_dir)
    manifest_path.unlink(missing_ok=True)
    return removed
