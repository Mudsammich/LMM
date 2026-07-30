"""Extraction of downloaded mod archives (zip / 7z / rar) into a mod's
staging directory.

Extraction alone isn't enough to get a usable mod: archives are packaged
for Windows mod managers, and two of their habits break a naive extract
on Linux.

The one handled here is *wrapper folders*. Plenty of mods wrap their real
payload in an extra directory - either the game's own ``Data`` (mirroring
where the files ultimately go) or a human-readable ``My Cool Mod v1.2``.
Deployed as-is, every file sits one level too deep and the game never
finds any of it. ``find_payload_root``/``flatten_payload_root`` detect
that and hoist the real payload up.

(The other habit - inconsistent capitalisation - is a deploy-time
concern, since it's about merging *across* mods rather than fixing one
archive. See ``deploy.CaseRegistry``.)
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import py7zr
import rarfile

SUPPORTED_EXTENSIONS = {".zip", ".7z", ".rar"}

# Directory names that mean "this is the real payload root" for a
# Bethesda-style game - i.e. the folders the game itself looks for inside
# Data. Compared case-insensitively.
_GAME_CONTENT_DIRS = {
    "textures", "meshes", "materials", "sound", "music", "interface",
    "scripts", "strings", "video", "shadersfx", "lodsettings", "vis",
    "seq", "grass", "programs", "f4se", "skse", "skseplugins", "mcm",
    "dists", "planetdata",
    # Installer metadata: its presence means the archive root *is* the
    # root the installer's paths are relative to, so never descend past it.
    "fomod",
}
# Likewise for loose files sitting at the payload root.
_GAME_CONTENT_SUFFIXES = {".esp", ".esm", ".esl", ".ba2", ".bsa", ".dll", ".ini"}

# Guard against pathologically nested archives (and against a symlink
# loop turning the descent into an infinite one).
_MAX_WRAPPER_DEPTH = 8


class UnsupportedArchiveError(ValueError):
    pass


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def extract(archive_path: str | Path, dest_dir: str | Path) -> Path:
    """Extracts ``archive_path`` into ``dest_dir`` (created if needed) and
    returns dest_dir. Raises UnsupportedArchiveError for unknown formats
    and OSError-derived exceptions on corrupt archives.
    """
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    elif suffix == ".7z":
        with py7zr.SevenZipFile(archive_path, mode="r") as zf:
            zf.extractall(path=dest_dir)
    elif suffix == ".rar":
        with rarfile.RarFile(archive_path) as rf:
            rf.extractall(path=dest_dir)
    else:
        raise UnsupportedArchiveError(f"Unsupported archive type: {archive_path}")

    return dest_dir


# -- wrapper-folder flattening -----------------------------------------------------


def _has_game_content(directory: Path) -> bool:
    """True if ``directory`` looks like the payload root itself, rather
    than a wrapper around it."""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.is_dir():
            if entry.name.lower() in _GAME_CONTENT_DIRS:
                return True
        elif entry.suffix.lower() in _GAME_CONTENT_SUFFIXES:
            return True
    return False


def _sole_child_dir(directory: Path) -> Path | None:
    """The single subdirectory of ``directory``, if that's all there is.
    A stray readme next to it is tolerated - only *directories* have to be
    unambiguous, since a lone subdir plus docs is a very common packaging
    shape."""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    subdirs = [e for e in entries if e.is_dir()]
    if len(subdirs) != 1:
        return None
    return subdirs[0]


def _child_dir_named(directory: Path, name: str) -> Path | None:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.is_dir() and entry.name.lower() == name:
            return entry
    return None


def find_payload_root(extracted_dir: str | Path) -> Path:
    """Walks down through redundant wrapper folders and returns the
    directory whose contents should actually be deployed.

    Three cases, checked in this order at each level:

    1. The level already looks like real game content (``textures/``, a
       loose ``.esp``, a ``fomod/`` folder) - stop, this is the payload.
    2. There's a child literally named ``Data`` - descend into it. This is
       unambiguous for Bethesda games because the deploy target *is* the
       game's Data folder, so a nested ``Data`` could only ever be a
       mirror of it.
    3. There's exactly one subdirectory (a ``My Cool Mod v1.2`` style
       wrapper) - descend into it.

    Anything else is ambiguous and left alone: returning the original
    directory just means LMM deploys what the archive literally contained,
    which is the current behaviour and never worse than guessing wrong.
    """
    current = Path(extracted_dir)
    for _ in range(_MAX_WRAPPER_DEPTH):
        if _has_game_content(current):
            return current
        data_child = _child_dir_named(current, "data")
        if data_child is not None:
            current = data_child
            continue
        sole = _sole_child_dir(current)
        if sole is not None:
            current = sole
            continue
        return current
    return current


def move_children(source_dir: Path, dest_dir: Path) -> None:
    """Moves everything inside ``source_dir`` into ``dest_dir``, replacing
    same-named entries. ``source_dir`` is left empty but not removed."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for child in list(source_dir.iterdir()):
        dest = dest_dir / child.name
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest, ignore_errors=True)
        elif dest.exists() or dest.is_symlink():
            dest.unlink()
        child.rename(dest)


def flatten_payload_root(staging_dir: str | Path) -> Path | None:
    """Hoists the real payload up so it sits directly in ``staging_dir``.

    Returns the wrapper path that was flattened away, or None if the
    archive was already laid out correctly. Payload entries win over
    same-named entries left at the old root (e.g. an outer ``readme.txt``
    shadowed by the payload's own).
    """
    staging_dir = Path(staging_dir)
    payload = find_payload_root(staging_dir)
    if payload == staging_dir:
        return None

    wrapper_top = staging_dir / payload.relative_to(staging_dir).parts[0]

    # Move the payload clear of the wrapper before deleting the husk, so
    # the two can't collide partway through (the payload may itself be
    # named the same as something at the old root).
    holding = staging_dir.parent / f".{staging_dir.name}.payload"
    if holding.exists():
        shutil.rmtree(holding, ignore_errors=True)
    payload.rename(holding)
    shutil.rmtree(wrapper_top, ignore_errors=True)

    move_children(holding, staging_dir)
    holding.rmdir()
    return payload
