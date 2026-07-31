"""Central place for all filesystem locations LMM reads or writes.

Everything is XDG-compliant (via platformdirs) so the app behaves on any
Linux distro, CachyOS included, without needing root or touching the game
install itself.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_cache_dir

APP_NAME = "lmm"


def icon_path() -> Path:
    """The bundled app icon (ships inside the lmm package itself via
    package-data, so it's available whether LMM was pip-installed or
    installed as a system package - independent of whether the icon
    theme cache on the system has picked up the separately-installed
    hicolor icons yet)."""
    return importlib.resources.files("lmm") / "assets" / "icon.svg"


def config_dir() -> Path:
    p = Path(user_config_dir(APP_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = Path(user_data_dir(APP_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = Path(user_cache_dir(APP_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    return config_dir() / "config.json"


def games_state_dir() -> Path:
    """Per-game state (installed mods, load order, deployed-file manifests)."""
    p = data_dir() / "games"
    p.mkdir(parents=True, exist_ok=True)
    return p


def game_state_dir(game_id: str) -> Path:
    p = games_state_dir() / game_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def download_cache_dir() -> Path:
    p = cache_dir() / "downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p
