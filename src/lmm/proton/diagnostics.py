"""Finding out why a modded Bethesda game won't start.

Two things are worth automating here, because both are easy to get wrong
silently and neither is discoverable from inside the game:

**Archive invalidation.** Fallout 4 and Skyrim ship their assets in ``.ba2``
/ ``.bsa`` archives, and by default a loose file on disk does *not* override
what's inside them. LMM deploys everything as loose files (symlinks), so
without archive invalidation a perfectly-deployed modlist has no visible
effect at all - the game quietly keeps using its packed vanilla assets. The
fix is two lines in the game's ``<Game>Custom.ini``, inside the Proton
prefix where the game actually looks for it.

**Crash logs.** A script extender writes a log saying whether it injected at
all, and Buffout 4 (Fallout 4) / Crash Logger (Skyrim) write a crash log
naming the module that actually crashed. Those files live several folders
deep inside the Proton prefix, which is exactly the sort of path nobody
finds by accident.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from . import prefix as prefix_module

# The two settings that make loose files win over the game's own archives.
# sResourceDataDirsFinal must be present *and* empty - a missing key is not
# equivalent, which is the usual way this gets half-applied.
_ARCHIVE_SECTION = "Archive"
_ARCHIVE_SETTINGS = {
    "bInvalidateOlderFiles": "1",
    "sResourceDataDirsFinal": "",
}


@dataclass
class ArchiveInvalidationStatus:
    ini_path: Path | None
    exists: bool = False
    enabled: bool = False
    missing: list[str] = field(default_factory=list)
    detail: str = ""


def guess_game_folder(game_name: str, plugins_txt_path: str = "") -> str:
    """The folder name the game uses under ``My Games`` (``Fallout4``,
    ``Skyrim Special Edition``, ...).

    Derived from the configured Plugins.txt path when there is one, since
    that already points at the game's own profile folder and so is the
    game's real spelling rather than a guess. Falls back to the game's
    display name with spaces removed, which is right for the Fallout titles.
    """
    if plugins_txt_path:
        parent = Path(plugins_txt_path).parent.name
        if parent:
            return parent
    return game_name.replace(" ", "") or "Game"


def custom_ini_path(prefix_path: str | Path, game_folder: str) -> Path:
    """``<prefix>/.../My Documents/My Games/<game_folder>/<game_folder>Custom.ini``
    - the per-user ini the game reads last, so it's the right place to put
    overrides rather than editing the game's own ini."""
    return (
        prefix_module.documents_dir(prefix_path)
        / "My Games"
        / game_folder
        / f"{game_folder}Custom.ini"
    )


def _read_ini(path: Path) -> configparser.ConfigParser:
    # Bethesda inis have no interpolation and mixed case keys we must keep.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if path.is_file():
        try:
            parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
        except configparser.Error:
            pass  # a malformed ini is treated as "needs fixing", not fatal
    return parser


def check_archive_invalidation(
    prefix_path: str | Path, game_folder: str
) -> ArchiveInvalidationStatus:
    """Whether loose files will actually override the game's archives."""
    path = custom_ini_path(prefix_path, game_folder)
    if not path.is_file():
        return ArchiveInvalidationStatus(
            ini_path=path,
            exists=False,
            enabled=False,
            missing=sorted(_ARCHIVE_SETTINGS),
            detail=(
                f"{path.name} doesn't exist yet. Without it the game ignores every "
                "loose file LMM deploys and keeps using its packed vanilla assets."
            ),
        )

    parser = _read_ini(path)
    missing: list[str] = []
    for key, wanted in _ARCHIVE_SETTINGS.items():
        actual = None
        if parser.has_section(_ARCHIVE_SECTION):
            for existing_key in parser[_ARCHIVE_SECTION]:
                if existing_key.lower() == key.lower():
                    actual = parser[_ARCHIVE_SECTION][existing_key].strip()
                    break
        if actual is None or actual != wanted:
            missing.append(key)

    enabled = not missing
    return ArchiveInvalidationStatus(
        ini_path=path,
        exists=True,
        enabled=enabled,
        missing=sorted(missing),
        detail=(
            "Archive invalidation is set up correctly - loose files override the "
            "game's own archives."
            if enabled
            else f"{path.name} exists but these settings are missing or wrong: "
            f"{', '.join(sorted(missing))}. Until they're right, the game ignores "
            "loose files."
        ),
    )


def enable_archive_invalidation(prefix_path: str | Path, game_folder: str) -> Path:
    """Writes the two archive-invalidation settings, preserving everything
    else already in the ini. Returns the path written."""
    path = custom_ini_path(prefix_path, game_folder)
    path.parent.mkdir(parents=True, exist_ok=True)

    parser = _read_ini(path)
    if not parser.has_section(_ARCHIVE_SECTION):
        parser.add_section(_ARCHIVE_SECTION)
    # Drop any case variant first, so we don't end up with both
    # bInvalidateOlderFiles and binvalidateolderfiles fighting each other.
    for key in list(parser[_ARCHIVE_SECTION]):
        if key.lower() in {k.lower() for k in _ARCHIVE_SETTINGS}:
            del parser[_ARCHIVE_SECTION][key]
    for key, value in _ARCHIVE_SETTINGS.items():
        parser[_ARCHIVE_SECTION][key] = value

    lines: list[str] = []
    for section in parser.sections():
        lines.append(f"[{section}]")
        for key, value in parser[section].items():
            lines.append(f"{key}={value}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -- log discovery -----------------------------------------------------


@dataclass
class LogFile:
    path: Path
    modified: float
    size: int


def find_game_logs(
    prefix_path: str | Path, game_folder: str, limit: int = 12
) -> list[LogFile]:
    """Script extender and crash logs for a game, newest first.

    These live under ``My Games/<game>/F4SE`` (or ``SKSE``), which is where
    both the extender's own log and any crash logger's output land - the
    crash log is the thing that actually names what crashed, so it's worth
    surfacing rather than leaving buried in the prefix.
    """
    base = prefix_module.documents_dir(prefix_path) / "My Games" / game_folder
    if not base.is_dir():
        return []

    found: list[LogFile] = []
    for candidate in base.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in (".log", ".txt"):
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        found.append(LogFile(path=candidate, modified=stat.st_mtime, size=stat.st_size))

    found.sort(key=lambda f: f.modified, reverse=True)
    return found[:limit]


def read_log_tail(path: str | Path, max_bytes: int = 64 * 1024) -> str:
    """The end of a log file - crash logs put the useful part (the faulting
    module and the call stack) near the top, but extender logs grow, so a
    bounded read keeps a huge file from being loaded whole."""
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                body = fh.read().decode("utf-8", errors="replace")
                return f"[… truncated, showing the last {max_bytes // 1024} KB …]\n\n{body}"
            return fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"Couldn't read {path}: {exc}"
