"""Discovery of Steam's install layout: library folders, installed apps,
and available Proton builds (official + custom, e.g. Proton-GE via
ProtonUp-Qt, common on CachyOS)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import vdf

DEFAULT_STEAM_ROOTS = [
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",  # flatpak
]


@dataclass
class SteamApp:
    appid: int
    name: str
    install_dir: Path
    library_path: Path

    @property
    def compatdata_path(self) -> Path:
        return self.library_path / "steamapps" / "compatdata" / str(self.appid)

    @property
    def prefix_path(self) -> Path:
        return self.compatdata_path / "pfx"


@dataclass
class ProtonBuild:
    name: str
    path: Path


def find_steam_root() -> Path | None:
    for candidate in DEFAULT_STEAM_ROOTS:
        p = Path(candidate).expanduser()
        if (p / "steamapps").is_dir():
            return p
    return None


def find_library_folders(steam_root: Path | None = None) -> list[Path]:
    """Every Steam library folder (main install + any added drives)."""
    steam_root = steam_root or find_steam_root()
    if steam_root is None:
        return []
    libraries = [steam_root]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf_path.is_file():
        try:
            data = vdf.loads(vdf_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        entries = data.get("libraryfolders", {})
        for key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if path:
                lib = Path(path)
                if lib not in libraries and (lib / "steamapps").is_dir():
                    libraries.append(lib)
    return libraries


def find_installed_apps(steam_root: Path | None = None) -> list[SteamApp]:
    """Parses every appmanifest_*.acf across all libraries."""
    apps: list[SteamApp] = []
    for library in find_library_folders(steam_root):
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            try:
                data = vdf.loads(manifest.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            state = data.get("AppState", {})
            appid = state.get("appid")
            install_dir = state.get("installdir")
            name = state.get("name", install_dir or "")
            if not appid or not install_dir:
                continue
            apps.append(
                SteamApp(
                    appid=int(appid),
                    name=name,
                    install_dir=steamapps / "common" / install_dir,
                    library_path=library,
                )
            )
    return apps


def find_proton_builds(steam_root: Path | None = None) -> list[ProtonBuild]:
    """Official Proton installs (steamapps/common/Proton*) plus custom
    builds like Proton-GE under compatibilitytools.d."""
    steam_root = steam_root or find_steam_root()
    builds: list[ProtonBuild] = []
    if steam_root is None:
        return builds

    for library in find_library_folders(steam_root):
        common = library / "steamapps" / "common"
        if common.is_dir():
            for entry in sorted(common.glob("Proton*")):
                if entry.is_dir() and (entry / "proton").is_file():
                    builds.append(ProtonBuild(name=entry.name, path=entry))

    for tools_dir_name in ("compatibilitytools.d",):
        tools_dir = steam_root / tools_dir_name
        if tools_dir.is_dir():
            for entry in sorted(tools_dir.iterdir()):
                if entry.is_dir() and (entry / "proton").is_file():
                    builds.append(ProtonBuild(name=entry.name, path=entry))

    return builds
