"""Plain dataclasses shared across the app. No behaviour lives here beyond
simple (de)serialisation - business logic belongs in the owning module.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class DeployMethod(str, Enum):
    SYMLINK = "symlink"
    HARDLINK = "hardlink"


@dataclass
class Game:
    """A modding target: a game install plus the Proton prefix it runs in."""

    id: str  # short slug used as the on-disk key, e.g. "skyrimse"
    name: str  # display name
    nexus_domain: str  # Nexus Mods game domain, e.g. "skyrimspecialedition"
    install_path: str  # path to the game's install directory
    deploy_subpath: str = ""  # subfolder under install_path mods deploy into (e.g. "Data")
    mods_dir: str = ""  # staging directory holding extracted mod files
    steam_appid: int | None = None
    proton_prefix: str = ""  # path to the *pfx* directory, if linked
    proton_version_path: str = ""  # path to the Proton build used to run tools
    deploy_method: DeployMethod = DeployMethod.SYMLINK
    manages_plugins: bool = False  # Bethesda-style plugins.txt / load order

    def deploy_target(self) -> str:
        if self.deploy_subpath:
            return str(Path(self.install_path) / self.deploy_subpath)
        return self.install_path

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["deploy_method"] = self.deploy_method.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Game":
        d = dict(d)
        d["deploy_method"] = DeployMethod(d.get("deploy_method", "symlink"))
        return cls(**d)


@dataclass
class ModSource:
    """Where a mod file came from, if known - lets us re-fetch / update it."""

    kind: str = "manual"  # "nexus" | "manual"
    mod_id: int | None = None
    file_id: int | None = None
    version: str = ""
    md5: str = ""


@dataclass
class InstalledMod:
    """A mod extracted into a game's staging directory."""

    id: str  # slug, unique within the game (e.g. "12345-unofficial-patch")
    name: str
    game_id: str
    staging_subdir: str  # folder name under the game's mods_dir
    enabled: bool = True
    priority: int = 0  # load order; higher wins conflicts on deploy
    source: ModSource = field(default_factory=ModSource)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InstalledMod":
        d = dict(d)
        src = d.get("source") or {}
        d["source"] = ModSource(**src)
        return cls(**d)


@dataclass
class DownloadTask:
    """A single file download, queued and tracked by the DownloadManager."""

    id: str
    display_name: str
    url: str
    dest_path: str
    game_id: str = ""
    mod_source: ModSource = field(default_factory=ModSource)
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = "queued"  # queued | downloading | done | error | canceled
    error: str = ""
