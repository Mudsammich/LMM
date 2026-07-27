"""Bethesda-style plugin (.esp/.esm/.esl) load order management.

This deliberately does not attempt to replicate LOOT's master-dependency
sorting. That requires parsing Bethesda's binary plugin file format
precisely - which differs subtly across game versions in ways not worth
guessing at - plus LOOT's own community-curated masterlist rules, neither
of which can be done reliably here. Real sorting is LOOT's job: run it
(via ``lmm.proton.prefix.run_in_prefix`` against the same prefix, or a
native Linux LOOT build) against ``Plugins.txt``, then call
``import_from_plugins_txt`` to pull whatever order it left behind back
into LMM's own state.

What LMM does own reliably: detecting which plugins your enabled mods
actually provide, keeping a persisted order across mod list changes,
enabling/disabling entries, and writing a correctly-formatted
``Plugins.txt``. The ``*`` (active) prefix convention below is the
modern one used since Skyrim Special Edition / Fallout 4 - older titles
(original Skyrim, Fallout 3/NV, Oblivion) list every line as always
active and don't support this convention.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

PLUGIN_EXTENSIONS = {".esp", ".esm", ".esl"}


@dataclass
class Plugin:
    name: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Plugin":
        return cls(name=d["name"], enabled=d.get("enabled", True))


def detect_plugins(deploy_links: dict[str, Path]) -> list[str]:
    """Plugin filenames among a deploy plan's winning files.

    ``deploy_links`` is a deploy.DeployPlan.links dict (relative posix
    path -> source file). Bethesda plugins must sit directly in the Data
    folder root, not a subfolder, so nested paths are ignored.
    """
    names = [
        rel
        for rel in deploy_links
        if "/" not in rel and Path(rel).suffix.lower() in PLUGIN_EXTENSIONS
    ]
    return sorted(names, key=str.lower)


def sync_plugins(existing: list[Plugin], detected_names: list[str]) -> list[Plugin]:
    """Keeps existing order and enabled state for plugins still provided
    by an enabled mod, appends newly-detected ones at the end, and drops
    ones no longer provided by anything (e.g. their mod got disabled or
    removed)."""
    detected_set = set(detected_names)
    kept = [p for p in existing if p.name in detected_set]
    kept_names = {p.name for p in kept}
    new = [Plugin(name=n, enabled=True) for n in detected_names if n not in kept_names]
    return kept + new


def _plugins_state_file(state_dir: Path) -> Path:
    return state_dir / "plugins.json"


def load_plugins(state_dir: Path) -> list[Plugin]:
    path = _plugins_state_file(state_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Plugin.from_dict(d) for d in data]


def save_plugins(state_dir: Path, plugins: list[Plugin]) -> None:
    path = _plugins_state_file(state_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([p.to_dict() for p in plugins], indent=2), encoding="utf-8")
    tmp.replace(path)


def write_plugins_txt(path: str | Path, plugins: list[Plugin]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{'*' if p.enabled else ''}{p.name}" for p in plugins]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def import_from_plugins_txt(path: str | Path) -> list[Plugin]:
    """Re-syncs LMM's state from an existing Plugins.txt - e.g. after
    running LOOT, which sorts and rewrites this file directly."""
    path = Path(path)
    if not path.exists():
        return []
    plugins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        enabled = line.startswith("*")
        name = line[1:] if enabled else line
        plugins.append(Plugin(name=name, enabled=enabled))
    return plugins
