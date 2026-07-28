"""ModManager: the orchestration layer that ties together archive
extraction, the InstalledMod records for a game, and the deploy engine.
This is the main entry point the GUI (and any future CLI) talks to.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

from .. import paths
from ..models import DeployMethod, Game, InstalledMod, ModSource
from . import archive, deploy, plugins as plugins_module


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "mod"


class ModManagerError(RuntimeError):
    pass


class ModManager:
    """Owns one game's installed-mod list and staging directory."""

    def __init__(self, game: Game):
        self.game = game
        self.state_dir = paths.game_state_dir(game.id)
        self._mods: dict[str, InstalledMod] = {}
        # Guards self._mods + its on-disk save. Installs can now run on a
        # background thread (extraction is slow); this keeps that safe
        # against the GUI thread concurrently removing/enabling/reordering
        # mods on the same ModManager. Deliberately not held during
        # archive.extract() itself - only around the in-memory/JSON update -
        # so a slow extraction can't block a quick GUI-thread action.
        self._lock = threading.Lock()
        self._load()

    # -- persistence -----------------------------------------------------

    def _mods_file(self) -> Path:
        return self.state_dir / "mods.json"

    def _load(self) -> None:
        path = self._mods_file()
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._mods = {m["id"]: InstalledMod.from_dict(m) for m in data}

    def _save(self) -> None:
        path = self._mods_file()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([m.to_dict() for m in self._mods.values()], indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    # -- queries -----------------------------------------------------

    def list_mods(self) -> list[InstalledMod]:
        with self._lock:
            return sorted(self._mods.values(), key=lambda m: m.priority)

    def get(self, mod_id: str) -> InstalledMod | None:
        with self._lock:
            return self._mods.get(mod_id)

    # -- install / remove -----------------------------------------------------

    def install_from_archive(
        self,
        archive_path: str | Path,
        display_name: str,
        source: ModSource | None = None,
    ) -> InstalledMod:
        archive_path = Path(archive_path)
        if not archive.is_supported(archive_path):
            raise ModManagerError(f"Unsupported archive format: {archive_path.suffix}")

        mods_dir = Path(self.game.mods_dir)
        mods_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            base_slug = slugify(display_name)
            staging_subdir = base_slug
            n = 2
            while (mods_dir / staging_subdir).exists() or staging_subdir in {
                m.staging_subdir for m in self._mods.values()
            }:
                staging_subdir = f"{base_slug}-{n}"
                n += 1
            dest = mods_dir / staging_subdir
            dest.mkdir(parents=True)  # reserve the slot so concurrent installs can't collide

        archive.extract(archive_path, dest)  # slow - deliberately outside the lock

        mod_id = staging_subdir
        with self._lock:
            next_priority = max((m.priority for m in self._mods.values()), default=-1) + 1
            mod = InstalledMod(
                id=mod_id,
                name=display_name,
                game_id=self.game.id,
                staging_subdir=staging_subdir,
                enabled=True,
                priority=next_priority,
                source=source or ModSource(),
            )
            self._mods[mod.id] = mod
            self._save()
        return mod

    def remove(self, mod_id: str, delete_files: bool = True) -> None:
        with self._lock:
            mod = self._mods.pop(mod_id, None)
            if mod is None:
                raise ModManagerError(f"No such mod: {mod_id}")
            self._save()
        if delete_files:
            staging_path = Path(self.game.mods_dir) / mod.staging_subdir
            shutil.rmtree(staging_path, ignore_errors=True)

    # -- enable / ordering -----------------------------------------------------

    def set_enabled(self, mod_id: str, enabled: bool) -> None:
        with self._lock:
            mod = self._require(mod_id)
            mod.enabled = enabled
            self._save()

    def reorder(self, ordered_mod_ids: list[str]) -> None:
        """Sets priority to match the given order (index 0 = lowest priority)."""
        with self._lock:
            for priority, mod_id in enumerate(ordered_mod_ids):
                self._require(mod_id).priority = priority
            self._save()

    def _require(self, mod_id: str) -> InstalledMod:
        mod = self._mods.get(mod_id)
        if mod is None:
            raise ModManagerError(f"No such mod: {mod_id}")
        return mod

    # -- deployment -----------------------------------------------------

    def _enabled_mods_sorted(self) -> list[InstalledMod]:
        with self._lock:
            return sorted((m for m in self._mods.values() if m.enabled), key=lambda m: m.priority)

    def deploy(self) -> deploy.DeployResult:
        plan = deploy.build_plan(Path(self.game.mods_dir), self._enabled_mods_sorted())
        target_dir = Path(self.game.deploy_target())
        return deploy.apply_plan(plan, target_dir, self.state_dir, self.game.deploy_method)

    def undeploy(self) -> int:
        target_dir = Path(self.game.deploy_target())
        return deploy.undeploy_all(target_dir, self.state_dir)

    def preview_conflicts(self) -> dict[str, list[str]]:
        plan = deploy.build_plan(Path(self.game.mods_dir), self._enabled_mods_sorted())
        return plan.conflicts

    # -- plugin load order (Bethesda-style games) -----------------------------------------------------

    def list_plugins(self) -> list[plugins_module.Plugin]:
        return plugins_module.load_plugins(self.state_dir)

    def sync_plugins_from_mods(self) -> list[plugins_module.Plugin]:
        """Re-detects plugins from the currently enabled mods' files (via
        the same deploy plan used for real deployment) and merges them
        into the persisted plugin order, keeping existing order/enabled
        state and dropping plugins no longer provided by anything."""
        plan = deploy.build_plan(Path(self.game.mods_dir), self._enabled_mods_sorted())
        detected = plugins_module.detect_plugins(plan.links)
        current = plugins_module.load_plugins(self.state_dir)
        updated = plugins_module.sync_plugins(current, detected)
        plugins_module.save_plugins(self.state_dir, updated)
        return updated

    def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        current = plugins_module.load_plugins(self.state_dir)
        for p in current:
            if p.name == name:
                p.enabled = enabled
                break
        else:
            raise ModManagerError(f"No such plugin: {name}")
        plugins_module.save_plugins(self.state_dir, current)

    def reorder_plugins(self, ordered_names: list[str]) -> None:
        current = {p.name: p for p in plugins_module.load_plugins(self.state_dir)}
        missing = [n for n in ordered_names if n not in current]
        if missing:
            raise ModManagerError(f"Unknown plugin(s) in reorder list: {missing}")
        plugins_module.save_plugins(self.state_dir, [current[n] for n in ordered_names])

    def write_plugins_txt(self) -> Path:
        if not self.game.plugins_txt_path:
            raise ModManagerError("No Plugins.txt path set for this game (Edit Game).")
        current = plugins_module.load_plugins(self.state_dir)
        path = Path(self.game.plugins_txt_path)
        plugins_module.write_plugins_txt(path, current)
        return path

    def import_plugins_from_txt(self) -> list[plugins_module.Plugin]:
        """Re-syncs LMM's plugin state from Plugins.txt - e.g. after
        running LOOT, which sorts and rewrites that file directly."""
        if not self.game.plugins_txt_path:
            raise ModManagerError("No Plugins.txt path set for this game (Edit Game).")
        imported = plugins_module.import_from_plugins_txt(self.game.plugins_txt_path)
        plugins_module.save_plugins(self.state_dir, imported)
        return imported
