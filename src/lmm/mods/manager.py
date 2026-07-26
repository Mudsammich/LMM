"""ModManager: the orchestration layer that ties together archive
extraction, the InstalledMod records for a game, and the deploy engine.
This is the main entry point the GUI (and any future CLI) talks to.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .. import paths
from ..models import DeployMethod, Game, InstalledMod, ModSource
from . import archive, deploy


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
        return sorted(self._mods.values(), key=lambda m: m.priority)

    def get(self, mod_id: str) -> InstalledMod | None:
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

        base_slug = slugify(display_name)
        staging_subdir = base_slug
        n = 2
        while (mods_dir / staging_subdir).exists() or staging_subdir in {
            m.staging_subdir for m in self._mods.values()
        }:
            staging_subdir = f"{base_slug}-{n}"
            n += 1

        dest = mods_dir / staging_subdir
        archive.extract(archive_path, dest)

        mod_id = staging_subdir
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
        mod = self._mods.pop(mod_id, None)
        if mod is None:
            raise ModManagerError(f"No such mod: {mod_id}")
        self._save()
        if delete_files:
            staging_path = Path(self.game.mods_dir) / mod.staging_subdir
            shutil.rmtree(staging_path, ignore_errors=True)

    # -- enable / ordering -----------------------------------------------------

    def set_enabled(self, mod_id: str, enabled: bool) -> None:
        mod = self._require(mod_id)
        mod.enabled = enabled
        self._save()

    def reorder(self, ordered_mod_ids: list[str]) -> None:
        """Sets priority to match the given order (index 0 = lowest priority)."""
        for priority, mod_id in enumerate(ordered_mod_ids):
            self._require(mod_id).priority = priority
        self._save()

    def _require(self, mod_id: str) -> InstalledMod:
        mod = self._mods.get(mod_id)
        if mod is None:
            raise ModManagerError(f"No such mod: {mod_id}")
        return mod

    # -- deployment -----------------------------------------------------

    def deploy(self) -> deploy.DeployResult:
        enabled = sorted(
            (m for m in self._mods.values() if m.enabled), key=lambda m: m.priority
        )
        plan = deploy.build_plan(Path(self.game.mods_dir), enabled)
        target_dir = Path(self.game.deploy_target())
        return deploy.apply_plan(plan, target_dir, self.state_dir, self.game.deploy_method)

    def undeploy(self) -> int:
        target_dir = Path(self.game.deploy_target())
        return deploy.undeploy_all(target_dir, self.state_dir)

    def preview_conflicts(self) -> dict[str, list[str]]:
        enabled = sorted(
            (m for m in self._mods.values() if m.enabled), key=lambda m: m.priority
        )
        plan = deploy.build_plan(Path(self.game.mods_dir), enabled)
        return plan.conflicts
