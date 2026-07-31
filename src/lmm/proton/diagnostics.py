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
import re
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


# Log categories, most diagnostic first. A crash log names the module that
# actually faulted; the script extender's own log says which plugins loaded
# and which failed. Everything else is a plugin chattering about itself -
# useful occasionally, but never the thing to read first.
CATEGORY_CRASH = "crash"
CATEGORY_EXTENDER = "extender"
CATEGORY_LOADER = "loader"
CATEGORY_PLUGIN = "plugin"

_CATEGORY_ORDER = (CATEGORY_CRASH, CATEGORY_EXTENDER, CATEGORY_LOADER, CATEGORY_PLUGIN)

# Script extenders across the Bethesda titles.
_EXTENDER_LOG_NAMES = {
    "f4se.log", "f4sevr.log", "skse.log", "skse64.log", "sksevr.log",
    "nvse.log", "obse.log", "fose.log",
}
# The crash loggers worth having installed. Their mere presence in this
# folder means a crash *will* produce a report next time.
_CRASH_LOGGER_LOG_NAMES = {
    "buffout4.log", "crashlogger.log", "crashloggerSSE.log".lower(),
    "netscriptframework.log", ".net script framework.log",
}


def classify_log(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("crash-") or lowered.startswith("crash_") or "crashlog-" in lowered:
        return CATEGORY_CRASH
    if lowered in _EXTENDER_LOG_NAMES:
        return CATEGORY_EXTENDER
    if "_loader" in lowered:
        return CATEGORY_LOADER
    return CATEGORY_PLUGIN


@dataclass
class LogFile:
    path: Path
    modified: float
    size: int
    category: str = CATEGORY_PLUGIN

    @property
    def name(self) -> str:
        return self.path.name


def pick_primary_log(logs: list[LogFile]) -> LogFile | None:
    """The log worth reading first.

    Deliberately *not* simply the newest: every plugin rewrites its log on
    each launch, so "newest" is a coin toss between a crash report and some
    plugin's routine startup chatter. Ranked by category instead, newest
    within a category.
    """
    for category in _CATEGORY_ORDER:
        candidates = [log for log in logs if log.category == category]
        if candidates:
            return max(candidates, key=lambda log: log.modified)
    return None


def crash_logger_present(logs: list[LogFile]) -> bool:
    """Whether a crash logger is installed and running. Without one, a
    crash leaves nothing behind to diagnose - which is itself the finding
    when a game is crashing and no report ever appears."""
    for log in logs:
        if log.category == CATEGORY_CRASH:
            return True
        if log.name.lower() in _CRASH_LOGGER_LOG_NAMES:
            return True
    return False


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
        found.append(
            LogFile(
                path=candidate,
                modified=stat.st_mtime,
                size=stat.st_size,
                category=classify_log(candidate.name),
            )
        )

    found.sort(key=lambda f: f.modified, reverse=True)
    return found[:limit]


# "plugin Foo.dll (00000001 Foo 01000000) disabled, address library needs
# to be updated 0 (handle 0)" - the trailing handle is noise.
_PLUGIN_LINE = re.compile(
    r"^plugin\s+(?P<file>\S+\.dll)\s*\((?P<meta>[^)]*)\)\s*(?P<status>.+?)"
    r"(?:\s*\(handle\s+\d+\))?\s*$",
    re.IGNORECASE,
)
# "F4SE runtime: initialize (version = 0.7.8 010B0DD0 01DD1FD1AD5C8CB3, os = ...)"
_RUNTIME_LINE = re.compile(
    r"runtime:\s*initialize\s*\(version\s*=\s*(?P<extender>[\d.]+)\s+(?P<runtime>[0-9A-Fa-f]{8})",
    re.IGNORECASE,
)

_ADDRESS_LIBRARY_HINT = "address library"


@dataclass
class PluginStatus:
    file: str
    loaded: bool
    status: str

    @property
    def is_address_library_problem(self) -> bool:
        return _ADDRESS_LIBRARY_HINT in self.status.lower()


@dataclass
class ExtenderSummary:
    extender_version: str = ""
    runtime_raw: str = ""
    runtime_version: str = ""
    loaded: list[PluginStatus] = field(default_factory=list)
    failed: list[PluginStatus] = field(default_factory=list)

    @property
    def address_library_failures(self) -> list[PluginStatus]:
        return [p for p in self.failed if p.is_address_library_problem]

    @property
    def total(self) -> int:
        return len(self.loaded) + len(self.failed)


def decode_runtime_version(raw: str) -> str:
    """Turns the script extender's packed runtime version into the dotted
    form the mod pages use. ``010A00A3`` -> ``1.10.163``, which is the
    number to compare against what a mod says it supports."""
    try:
        value = int(raw, 16)
    except ValueError:
        return ""
    return f"{(value >> 24) & 0xFF}.{(value >> 16) & 0xFF}.{value & 0xFFFF}"


def summarise_extender_log(text: str) -> ExtenderSummary:
    """Reads a script extender log into which plugins loaded and which
    didn't.

    Worth doing rather than showing the raw log, because the failures are
    scattered among the successes across dozens of lines, and the single
    most common failure - a plugin refusing to load because the Address
    Library doesn't match the game's version - looks like an unremarkable
    line rather than the showstopper it is.
    """
    summary = ExtenderSummary()
    for line in text.splitlines():
        line = line.strip()
        runtime_match = _RUNTIME_LINE.search(line)
        if runtime_match:
            summary.extender_version = runtime_match.group("extender")
            summary.runtime_raw = runtime_match.group("runtime").upper()
            summary.runtime_version = decode_runtime_version(summary.runtime_raw)
            continue
        plugin_match = _PLUGIN_LINE.match(line)
        if not plugin_match:
            continue
        status = plugin_match.group("status").strip()
        entry = PluginStatus(file=plugin_match.group("file"), loaded=False, status=status)
        if status.lower().startswith("loaded correctly"):
            entry.loaded = True
            summary.loaded.append(entry)
        else:
            summary.failed.append(entry)
    return summary


def render_extender_summary(summary: ExtenderSummary) -> list[str]:
    """Plain-language reading of an extender log, for the Diagnose report."""
    if not summary.total and not summary.runtime_raw:
        return []

    lines = ["SCRIPT EXTENDER PLUGINS", "-" * 60]
    if summary.runtime_version:
        lines.append(
            f"Game version {summary.runtime_version} (raw {summary.runtime_raw}), "
            f"script extender {summary.extender_version}"
        )
    if not summary.total:
        return lines + ["No plugin load results in the log."]

    lines.append(f"{len(summary.loaded)} of {summary.total} plugin(s) loaded.")

    address_failures = summary.address_library_failures
    if address_failures:
        lines += [
            "",
            f"PROBLEM - {len(address_failures)} plugin(s) refused to load because the",
            "Address Library doesn't match the game's version. That happens when the",
            "game updates to a version the mods weren't built for - the mods' .esp",
            "files still load, but everything depending on these plugins doesn't,",
            "which is a common cause of crashing at or just after the main menu.",
            "",
            "Fix it by making the three agree: the game's version, the script",
            f"extender build for it, and an Address Library for {summary.runtime_version or 'that version'}.",
            "If the modlist targets an older version, downgrading the game to it is",
            "usually easier than finding updated builds of every plugin.",
        ]

    other_failures = [p for p in summary.failed if not p.is_address_library_problem]
    if other_failures:
        lines += ["", "Other plugins that didn't load:"]
        for plugin in other_failures:
            lines.append(f"  {plugin.file} - {plugin.status}")

    if address_failures:
        lines += ["", "Blocked by the Address Library mismatch:"]
        for plugin in address_failures:
            lines.append(f"  {plugin.file}")

    return lines


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
