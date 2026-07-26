# LMM - Linux Mod Manager

![LMM banner](docs/screenshots/banner.png)

A mod manager for Linux (built and tested with CachyOS in mind) that ties
together three things Linux modding usually leaves you to glue by hand:

- **Nexus Mods downloads** - a `nxm://` link handler, a REST API client, and
  Collection manifest import, so clicking "Mod Manager Download" on the
  website flows straight into LMM.
- **Proton prefix linking** - each game you manage points at the Steam
  library, install path, and Proton prefix it actually runs in, so LMM
  (and any tool you launch through it) knows exactly which prefix to use.
- **Mod deployment** - mods are extracted into a staging directory and
  deployed into the game's real folder as symlinks, in a load order you
  control, with conflicts surfaced instead of silently overwritten.

## How it works

Mods are never extracted directly into your game folder. Each installed
mod lives in its own subfolder under a per-game staging directory
(`mods_dir`). "Deploy" walks your enabled mods in priority order and
symlinks their files into the game's real directory (`install_path` +
`deploy_subpath`, e.g. `.../Skyrim Special Edition/Data`); a later mod's
file silently wins over an earlier one at the same path, and every such
collision is reported as a conflict. "Undeploy" removes exactly the links
LMM created - it verifies each link still points at the mod file it came
from before removing it, so it never touches a real game file or a link
you've since replaced by hand.

This mirrors the "simple" deployment mode of MO2/Vortex, minus the
Windows-only virtual filesystem trick - on Linux, symlinks into the real
game directory are the reliable option under Proton.

## Screenshots

| Games | Mods |
| --- | --- |
| ![Games tab](docs/screenshots/games-tab.png) | ![Mods tab](docs/screenshots/mods-tab.png) |

| Downloads | Settings |
| --- | --- |
| ![Downloads tab](docs/screenshots/downloads-tab.png) | ![Settings tab](docs/screenshots/settings-tab.png) |

## Installing

### CachyOS / Arch

```sh
cd packaging
makepkg -si
```

`python-vdf` is AUR-only - install it with an AUR helper first (`paru -S
python-vdf`), or build the whole package with an AUR helper pointed at
`packaging/` so it resolves it for you. Everything else (`pyside6`,
`python-py7zr`, `python-rarfile`) is in the official `extra` repo, so
plain `pacman`/`makepkg` handles them. `unrar` is an optional dependency
needed only if you install `.rar` mod archives.

### From source (any distro)

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
lmm
```

## Getting started

1. **Settings tab** - paste your [Nexus Mods API
   key](https://next.nexusmods.com/settings/api-keys), click Validate, and
   click "Register LMM as the nxm:// download handler" so download buttons
   on the site open LMM instead of your browser trying (and failing) to
   handle them.
2. **Games tab** - Add Game, then "Detect from Steam" to pick an installed
   Steam app; this fills in the install path, AppID, and Proton prefix
   automatically. Set the Nexus Mods game domain (e.g.
   `skyrimspecialedition`) and the deploy subfolder (`Data` for Bethesda
   games, blank for games that mod directly into their root).
3. **Mods tab** - install a mod from a downloaded archive, or just click a
   "Mod Manager Download" button on Nexus Mods once the handler is
   registered. Reorder mods (later = higher priority = wins conflicts),
   then **Deploy**.
4. **Collections tab** - paste a collection's URL (e.g.
   `https://www.nexusmods.com/fallout4/collections/5atq9t`) and click
   **Fetch from Nexus** to pull its mod list directly from Nexus's own
   GraphQL API - the same data the collection's page itself renders with,
   so it needs no Vortex, no login flow, and works for any account tier.
   Then **Queue downloads for selected game**, which *is* gated to
   **premium** API keys - that's the same restriction Nexus's own tools
   apply to bulk downloads, not something LMM adds; see the note in
   `src/lmm/nexus/collections.py`. On a free key, open the collection's
   **Mods** tab on the website instead and download each mod individually
   - those are ordinary `nxm://` links LMM already handles.

   If the GraphQL fetch ever breaks (it's an undocumented, best-effort
   query), **Import collection.json…** still works as a fallback - get
   that file by running Vortex/the Nexus Mods App once to fetch the
   collection and copying `collection.json` out of its profile directory.

## Project layout

```
src/lmm/
  config.py, models.py, paths.py   application config & data model
  nexus/                           Nexus Mods API client, nxm:// links, collections
  proton/                          Steam library/app/Proton discovery, prefix linking
  mods/                            archive extraction, downloader, deploy engine, ModManager
  gui/                             PySide6 main window and tabs
tests/                             pytest suite for everything above the GUI layer
packaging/                         PKGBUILD + .desktop file for Arch/CachyOS
```

The GUI is a thin layer over `mods/manager.py`, `mods/deploy.py`,
`nexus/api.py`, and `proton/`. All of the actual logic is framework-free
and unit tested; the tabs mostly wire widgets to those calls.

## Running the tests

```sh
pip install -e ".[dev]"
pytest
```
