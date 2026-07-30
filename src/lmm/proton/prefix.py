"""Linking a Game to a Proton prefix, and running tools (xEdit, LOOT, FNIS,
...) inside that prefix - the piece that ties mod management to Proton."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import sandbox
from .steam import find_steam_root


def default_wine_user_dir(prefix_path: str | Path) -> Path:
    """The prefix's fake Windows user profile, where AppData/My Games live."""
    return Path(prefix_path) / "drive_c" / "users" / "steamuser"


def app_data_local(prefix_path: str | Path) -> Path:
    return default_wine_user_dir(prefix_path) / "AppData" / "Local"


def documents_dir(prefix_path: str | Path) -> Path:
    return default_wine_user_dir(prefix_path) / "My Documents"


def is_valid_prefix(prefix_path: str | Path) -> bool:
    p = Path(prefix_path)
    return (p / "drive_c").is_dir() and (p / "user.reg").is_file()


# Folders that show up under AppData/Local in most Wine/Proton prefixes
# regardless of which game runs there - never a game's own profile folder.
_NON_GAME_LOCAL_APPDATA_FOLDERS = {
    "microsoft", "temp", "packages", "nvidia", "nvidia corporation", "amd",
    "d3dscache", "publishers", "steam", "virtualstore",
    "connecteddevicesplatform", "google", "mozilla", "comms",
    "elevateddiagnostics", "clientdcinstall", "assembly", "history",
}


def find_local_appdata_candidates(prefix_path: str | Path) -> list[Path]:
    """Subfolders of the prefix's AppData/Local that could plausibly be a
    game's own profile folder (where Plugins.txt/loadorder.txt live) -
    i.e. everything except the common Windows/Wine system folders that
    appear in every prefix. Returns [] if the prefix has never had
    anything write local app data yet (e.g. the game has never launched)."""
    local = app_data_local(prefix_path)
    if not local.is_dir():
        return []
    return sorted(
        (p for p in local.iterdir() if p.is_dir() and p.name.lower() not in _NON_GAME_LOCAL_APPDATA_FOLDERS),
        key=lambda p: p.name.lower(),
    )


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def guess_plugins_txt_path(prefix_path: str | Path, game_name: str) -> Path | None:
    """Best-effort ``Plugins.txt`` path for a game, found by matching
    ``game_name`` against the prefix's actual local-appdata folders
    (case/space/punctuation-insensitive - "Fallout 4" matches "Fallout4")
    rather than guessing a hardcoded per-game folder name. Returns None
    if there's no exact-enough match and more than one candidate exists,
    so the caller can ask the user to pick.
    """
    candidates = find_local_appdata_candidates(prefix_path)
    if not candidates:
        return None
    target = _normalize_name(game_name)
    for candidate in candidates:
        if _normalize_name(candidate.name) == target:
            return candidate / "Plugins.txt"
    if len(candidates) == 1:
        return candidates[0] / "Plugins.txt"
    return None


def run_in_prefix(
    exe_path: str | Path,
    prefix_path: str | Path,
    proton_path: str | Path,
    args: list[str] | None = None,
    steam_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
    network_isolated: bool = False,
) -> subprocess.Popen:
    """Launches ``exe_path`` inside ``prefix_path`` via the given Proton
    build, exactly as Steam would set it up. Useful both for running the
    game itself and for modding tools (LOOT, xEdit, BodySlide, FNIS)
    against a modded game's prefix. Never goes through the Steam client
    itself - only Steam launching something through its own machinery
    makes it visible there, and this doesn't do that.

    ``network_isolated=True`` runs the whole thing inside a network
    namespace with no interfaces at all (see ``lmm.proton.sandbox``) -
    nothing spawned by Proton, wine, or the game can make any outbound
    connection. Raises NetworkIsolationUnavailable rather than silently
    launching without isolation if bubblewrap isn't installed.

    Returns the Popen handle so the caller can decide whether to wait,
    stream output, or fire-and-forget.
    """
    proton_path = Path(proton_path)
    proton_script = proton_path / "proton"
    if not proton_script.is_file():
        raise FileNotFoundError(f"No 'proton' launcher script found in {proton_path}")

    compatdata = Path(prefix_path)
    if compatdata.name == "pfx":
        compatdata = compatdata.parent  # STEAM_COMPAT_DATA_PATH is the compatdata/<appid> dir

    steam_root = steam_root or find_steam_root()
    if steam_root is None:
        raise RuntimeError("Could not locate a Steam installation for STEAM_COMPAT_CLIENT_INSTALL_PATH.")

    env = os.environ.copy()
    env["STEAM_COMPAT_DATA_PATH"] = str(compatdata)
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(steam_root)
    if extra_env:
        env.update(extra_env)

    cmd = [str(proton_script), "run", str(exe_path), *(args or [])]
    if network_isolated:
        cmd = sandbox.wrap_command(cmd)
    return subprocess.Popen(cmd, env=env)
