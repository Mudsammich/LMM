"""Application configuration: Nexus API key, global defaults, and the list
of configured games. Persisted as a single JSON file under the user's
XDG config directory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from . import paths
from .models import Game

CONFIG_VERSION = 1


@dataclass
class AppConfig:
    nexus_api_key: str = ""
    default_mods_root: str = ""  # parent directory new games' mods_dir defaults under
    games: dict[str, Game] = field(default_factory=dict)
    version: int = CONFIG_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nexus_api_key": self.nexus_api_key,
            "default_mods_root": self.default_mods_root,
            "games": {gid: g.to_dict() for gid, g in self.games.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        games = {
            gid: Game.from_dict(gd) for gid, gd in (d.get("games") or {}).items()
        }
        return cls(
            nexus_api_key=d.get("nexus_api_key", ""),
            default_mods_root=d.get("default_mods_root", ""),
            games=games,
            version=d.get("version", CONFIG_VERSION),
        )


def load() -> AppConfig:
    path = paths.config_file()
    if not path.exists():
        return AppConfig()
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return AppConfig.from_dict(data)


def save(config: AppConfig) -> None:
    path = paths.config_file()
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(config.to_dict(), fh, indent=2, sort_keys=True)
    tmp_path.replace(path)
