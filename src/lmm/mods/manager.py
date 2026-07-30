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

from typing import Callable

from .. import paths
from ..models import (
    DEPLOY_ROOT_AUTO,
    DEPLOY_ROOT_DATA,
    DEPLOY_ROOT_GAME,
    DeployMethod,
    Game,
    InstalledMod,
    ModSource,
)
from . import (
    archive,
    conflicts as conflicts_module,
    deploy,
    fomod as fomod_module,
    fomod_install,
    plugins as plugins_module,
    sorter,
)

# Called with the parsed installer script; returns the user's choices, or
# None if they cancelled.
FomodChooser = Callable[[fomod_module.FomodConfig], "fomod_install.InstallState | None"]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "mod"


class ModManagerError(RuntimeError):
    pass


class InstallCancelled(ModManagerError):
    """The user backed out of a FOMOD installer wizard. Not really a
    failure - callers should stay quiet rather than report an error."""


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
        priority: int | None = None,
        fomod_chooser: FomodChooser | None = None,
    ) -> InstalledMod:
        """``priority``, if given, is used as-is instead of appending at
        the end of the current list - lets a caller installing many mods
        at once (e.g. a whole Collection, downloaded concurrently and so
        completing out of order) preserve a specific intended order rather
        than whichever order downloads happened to finish in.

        ``fomod_chooser`` is called when the archive turns out to carry a
        FOMOD installer script, and should return the user's choices (or
        None if they cancelled, which raises ``InstallCancelled``). Omit it
        - as bulk installs must, since they run off the GUI thread and
        can't prompt hundreds of times - and the installer's own
        Required/Recommended defaults are used instead.
        """
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

        # Extract to a scratch dir rather than straight into staging: a
        # FOMOD needs its whole payload available to copy a *selection*
        # out of, and only the selection should end up staged.
        scratch = mods_dir / f".{staging_subdir}.extract"
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            archive.extract(archive_path, scratch)  # slow - deliberately outside the lock
            # Archives often wrap their payload in an extra Data/ or
            # "My Mod v1.2" folder; without this the whole mod deploys one
            # level too deep and the game never sees it.
            archive.flatten_payload_root(scratch)
            self._stage_payload(scratch, dest, fomod_chooser)
        except BaseException:
            # Never leave a half-populated staging dir behind for the
            # deploy engine to trip over - including on cancellation.
            shutil.rmtree(dest, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        mod_id = staging_subdir
        with self._lock:
            if priority is not None:
                next_priority = priority
            else:
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

    def _stage_payload(
        self,
        extracted: Path,
        dest: Path,
        fomod_chooser: FomodChooser | None,
    ) -> None:
        """Puts the files that should actually be installed into ``dest``.
        For an ordinary archive that's everything; for a FOMOD it's only
        what the chosen options resolve to."""
        config_path = fomod_module.find_module_config(extracted)
        if config_path is None:
            archive.move_children(extracted, dest)
            return

        try:
            config = fomod_module.parse_module_config(config_path)
        except fomod_module.FomodError:
            # A mod with a broken installer script is still a mod - fall
            # back to installing it whole rather than failing outright.
            archive.move_children(extracted, dest)
            return

        if fomod_chooser is not None and config.has_choices:
            state = fomod_chooser(config)
            if state is None:
                raise InstallCancelled(f"Installation of {config.module_name or 'mod'} cancelled.")
        else:
            state = fomod_install.default_state(config)

        resolved = fomod_install.resolve_files(config, state)
        staged = fomod_install.stage_resolved_files(extracted, resolved, dest)
        if staged == 0:
            # The script resolved to nothing usable (sources that don't
            # match the archive, say). Better a whole mod than an empty one.
            archive.move_children(extracted, dest)

    def remove(self, mod_id: str, delete_files: bool = True) -> None:
        self.remove_many([mod_id], delete_files=delete_files)

    def remove_many(self, mod_ids: list[str], delete_files: bool = True) -> list[InstalledMod]:
        """Removes several mods in one locked section (a single JSON save
        instead of one per mod, so bulk deletes of a large modlist don't
        hammer disk I/O). All-or-nothing: an unknown id raises without
        removing anything, so a bulk removal can't partially apply."""
        with self._lock:
            missing = [mid for mid in mod_ids if mid not in self._mods]
            if missing:
                raise ModManagerError(f"No such mod(s): {missing}")
            removed = [self._mods.pop(mod_id) for mod_id in mod_ids]
            self._save()
        if delete_files:
            for mod in removed:
                staging_path = Path(self.game.mods_dir) / mod.staging_subdir
                shutil.rmtree(staging_path, ignore_errors=True)
        return removed

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

    def _game_root(self) -> Path:
        return Path(self.game.install_path)

    def _build_plan(self) -> deploy.DeployPlan:
        """The deploy plan for the currently enabled mods. Always built
        against the real game directory so case-merging matches the game's
        own folder capitalisation - a preview that canonicalised differently
        from the real deploy would be misleading."""
        return deploy.build_plan(
            Path(self.game.mods_dir),
            self._enabled_mods_sorted(),
            deploy_subpath=self.game.deploy_subpath,
            target_dir=self._game_root(),
        )

    def deploy(self) -> deploy.DeployResult:
        plan = self._build_plan()
        return deploy.apply_plan(
            plan,
            self._game_root(),
            self.state_dir,
            self.game.deploy_method,
            legacy_base=Path(self.game.deploy_target()),
        )

    def undeploy(self) -> int:
        return deploy.undeploy_all(
            self._game_root(), self.state_dir, legacy_base=Path(self.game.deploy_target())
        )

    def deploy_roots(self) -> dict[str, str]:
        """mod id -> where each enabled mod's files will actually go, for
        the UI to surface. Resolves "auto" to what detection decided."""
        mods_dir = Path(self.game.mods_dir)
        with self._lock:
            mods = list(self._mods.values())
        return {m.id: deploy.resolve_deploy_root(m, mods_dir / m.staging_subdir) for m in mods}

    def set_deploy_root(self, mod_id: str, deploy_root: str) -> None:
        """Overrides where a mod deploys. Detection covers the mods that
        follow the usual packaging conventions, but an override matters for
        the ones that don't - guessing wrong on a script extender means the
        game silently loads none of it."""
        if deploy_root not in (DEPLOY_ROOT_AUTO, DEPLOY_ROOT_DATA, DEPLOY_ROOT_GAME):
            raise ModManagerError(f"Unknown deploy root: {deploy_root!r}")
        with self._lock:
            self._require(mod_id).deploy_root = deploy_root
            self._save()

    def preview_conflicts(self) -> dict[str, list[str]]:
        return self._build_plan().conflicts

    def conflict_report(self) -> tuple[conflicts_module.ConflictReport, dict[str, str], Path]:
        """The conflict summary, mod-id -> display-name map for rendering it,
        and the path of the full log written alongside. The exhaustive
        per-file listing goes to the log because a large modlist produces
        thousands of them - far past what's readable on screen."""
        report = conflicts_module.build_report(self.preview_conflicts())
        with self._lock:
            names = {m.id: m.name for m in self._mods.values()}
        log_path = conflicts_module.write_log(self.state_dir, report, names, self.game.name)
        return report, names, log_path

    def suggest_reorder(self) -> sorter.SortSuggestion:
        """Heuristic reorder suggestion for resolving file conflicts - see
        ``mods/sorter.py`` for exactly what it does and doesn't claim to
        do. Doesn't mutate anything; pass ``suggestion.new_order`` to
        ``reorder()`` to actually apply it."""
        with self._lock:
            all_mods = sorted(self._mods.values(), key=lambda m: m.priority)
        mods_dir = Path(self.game.mods_dir)
        enabled = [m for m in all_mods if m.enabled]
        plan = deploy.build_plan(
            mods_dir,
            enabled,
            deploy_subpath=self.game.deploy_subpath,
            target_dir=self._game_root(),
        )
        file_counts = {m.id: len(deploy.scan_mod_files(mods_dir / m.staging_subdir)) for m in enabled}
        return sorter.suggest_order(all_mods, plan.conflicts, file_counts)

    # -- plugin load order (Bethesda-style games) -----------------------------------------------------

    def list_plugins(self) -> list[plugins_module.Plugin]:
        return plugins_module.load_plugins(self.state_dir)

    def sync_plugins_from_mods(self) -> list[plugins_module.Plugin]:
        """Re-detects plugins from the currently enabled mods' files (via
        the same deploy plan used for real deployment) and merges them
        into the persisted plugin order, keeping existing order/enabled
        state and dropping plugins no longer provided by anything."""
        plan = self._build_plan()
        detected = plugins_module.detect_plugins(plan.links, data_prefix=self.game.deploy_subpath)
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

    def remove_plugins(self, names: list[str]) -> None:
        """Drops plugins from LMM's tracked list. Note this doesn't stop
        them reappearing on the next Sync from Mods if the mod providing
        them is still enabled - it's for cleaning up stale entries (e.g.
        left over from a mod removed a while ago), not for permanently
        excluding a plugin a still-enabled mod ships."""
        current = plugins_module.load_plugins(self.state_dir)
        known_names = {p.name for p in current}
        missing = [n for n in names if n not in known_names]
        if missing:
            raise ModManagerError(f"No such plugin(s): {missing}")
        to_remove = set(names)
        remaining = [p for p in current if p.name not in to_remove]
        plugins_module.save_plugins(self.state_dir, remaining)

    def reorder_plugins(self, ordered_names: list[str]) -> None:
        current = {p.name: p for p in plugins_module.load_plugins(self.state_dir)}
        missing = [n for n in ordered_names if n not in current]
        if missing:
            raise ModManagerError(f"Unknown plugin(s) in reorder list: {missing}")
        plugins_module.save_plugins(self.state_dir, [current[n] for n in ordered_names])

    def _require_plugins_txt_path(self) -> Path:
        if not self.game.plugins_txt_path:
            raise ModManagerError("No Plugins.txt path set for this game (Edit Game).")
        path = Path(self.game.plugins_txt_path)
        if path.is_dir():
            raise ModManagerError(
                f"Plugins.txt path is a folder ({path}), not a file - it needs the "
                f"filename too, e.g. {path / 'Plugins.txt'}"
            )
        return path

    def write_plugins_txt(self) -> Path:
        path = self._require_plugins_txt_path()
        current = plugins_module.load_plugins(self.state_dir)
        plugins_module.write_plugins_txt(path, current)
        return path

    def import_plugins_from_txt(self) -> list[plugins_module.Plugin]:
        """Re-syncs LMM's plugin state from Plugins.txt - e.g. after
        running LOOT, which sorts and rewrites that file directly."""
        path = self._require_plugins_txt_path()
        imported = plugins_module.import_from_plugins_txt(path)
        plugins_module.save_plugins(self.state_dir, imported)
        return imported
