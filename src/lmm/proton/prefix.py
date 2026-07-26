"""Linking a Game to a Proton prefix, and running tools (xEdit, LOOT, FNIS,
...) inside that prefix - the piece that ties mod management to Proton."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

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


def run_in_prefix(
    exe_path: str | Path,
    prefix_path: str | Path,
    proton_path: str | Path,
    args: list[str] | None = None,
    steam_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Launches ``exe_path`` inside ``prefix_path`` via the given Proton
    build, exactly as Steam would set it up. Useful for running modding
    tools (LOOT, xEdit, BodySlide, FNIS) against a modded game's prefix.

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
    return subprocess.Popen(cmd, env=env)
