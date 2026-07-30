"""Mods tab: per-game install list, load order, and deployment."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .context import AppContext
from .fomod_dialog import FomodDialog
from ..models import (
    DEPLOY_ROOT_AUTO,
    DEPLOY_ROOT_DATA,
    DEPLOY_ROOT_GAME,
    InstalledMod,
)
from ..mods.archive import SUPPORTED_EXTENSIONS
from ..mods.fomod import FomodConfig
from ..mods.fomod_install import InstallState
from ..mods.manager import InstallCancelled, ModManagerError

COLUMNS = ["On", "Priority", "Name", "Deploys to", "Source"]
PLUGIN_COLUMNS = ["On", "Plugin"]


def _deploy_root_label(mod: InstalledMod, resolved: str) -> str:
    """Shows where a mod's files land, and whether that was detected or set
    by hand - "forced" matters because it's the thing to re-check if a mod
    isn't loading."""
    label = "Game root" if resolved == DEPLOY_ROOT_GAME else "Data"
    return label if mod.deploy_root == DEPLOY_ROOT_AUTO else f"{label} (forced)"


class ModsTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        self.game_combo = QComboBox()
        self.game_combo.currentIndexChanged.connect(self._refresh_mods)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # ctrl/shift-click multi-select
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

        install_btn = QPushButton("Install from archive…")
        select_all_btn = QPushButton("Select All")
        remove_btn = QPushButton("Remove Selected")
        remove_all_btn = QPushButton("Remove All…")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        deploy_btn = QPushButton("Deploy")
        deploy_btn.setProperty("role", "primary")
        undeploy_btn = QPushButton("Undeploy")
        conflicts_btn = QPushButton("Show Conflicts")
        suggest_order_btn = QPushButton("Suggest Order (beta)")
        deploy_root_btn = QPushButton("Deploy Target…")

        install_btn.clicked.connect(self._install_from_archive)
        select_all_btn.clicked.connect(self.table.selectAll)
        remove_btn.clicked.connect(self._remove_selected)
        remove_all_btn.clicked.connect(self._remove_all)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        deploy_btn.clicked.connect(self._deploy)
        undeploy_btn.clicked.connect(self._undeploy)
        conflicts_btn.clicked.connect(self._show_conflicts)
        suggest_order_btn.clicked.connect(self._suggest_order)
        deploy_root_btn.clicked.connect(self._set_deploy_root)

        button_row = QHBoxLayout()
        for b in (
            install_btn, select_all_btn, remove_btn, remove_all_btn,
            up_btn, down_btn, deploy_btn, undeploy_btn, conflicts_btn,
            suggest_order_btn, deploy_root_btn,
        ):
            button_row.addWidget(b)
        button_row.addStretch(1)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Game:"))
        top_row.addWidget(self.game_combo, 1)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "status")

        self.plugins_section = self._build_plugins_section()

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.status_label)
        layout.addWidget(self.plugins_section)

        self.table.itemChanged.connect(self._on_item_changed)

        self.ctx.games_changed.connect(self._refresh_games)
        self.ctx.mods_changed.connect(self._on_mods_changed)
        self._refresh_games()

    # -- helpers -----------------------------------------------------

    def _current_game_id(self) -> str | None:
        return self.game_combo.currentData()

    def _on_mods_changed(self, game_id: str) -> None:
        if game_id == self._current_game_id():
            self._refresh_mods()

    def _refresh_games(self) -> None:
        current = self._current_game_id()
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        for game in self.ctx.games():
            self.game_combo.addItem(game.name, game.id)
        if current:
            idx = self.game_combo.findData(current)
            if idx >= 0:
                self.game_combo.setCurrentIndex(idx)
        self.game_combo.blockSignals(False)
        self._refresh_mods()

    def _refresh_mods(self) -> None:
        game_id = self._current_game_id()
        self.table.setRowCount(0)
        if not game_id:
            self._refresh_plugins()
            return
        manager = self.ctx.mod_manager(game_id)
        mods = manager.list_mods()
        roots = manager.deploy_roots()
        self.table.blockSignals(True)
        self.table.setRowCount(len(mods))
        for row, mod in enumerate(mods):
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            enabled_item.setCheckState(Qt.Checked if mod.enabled else Qt.Unchecked)
            enabled_item.setData(1000, mod.id)
            self.table.setItem(row, 0, enabled_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(mod.priority)))
            self.table.setItem(row, 2, QTableWidgetItem(mod.name))
            self.table.setItem(row, 3, QTableWidgetItem(_deploy_root_label(mod, roots.get(mod.id, ""))))
            source = mod.source.kind
            if mod.source.mod_id:
                source = f"nexus #{mod.source.mod_id}"
            self.table.setItem(row, 4, QTableWidgetItem(source))
        self.table.blockSignals(False)
        self._refresh_plugins()

    def _on_item_changed(self, item) -> None:
        if item.column() != 0:
            return
        game_id = self._current_game_id()
        if not game_id:
            return
        mod_id = item.data(1000)
        manager = self.ctx.mod_manager(game_id)
        manager.set_enabled(mod_id, item.checkState() == Qt.Checked)

    def _selected_mod_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(1000)

    def _selected_mod_ids(self) -> list[str]:
        rows = self.table.selectionModel().selectedRows()
        return [self.table.item(r.row(), 0).data(1000) for r in rows]

    # -- actions -----------------------------------------------------

    def _install_from_archive(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            QMessageBox.information(self, "Install mod", "Add a game first.")
            return
        game = self.ctx.config.games[game_id]
        if not game.mods_dir:
            QMessageBox.warning(self, "Install mod", "Set a mod staging directory for this game first (Games tab).")
            return

        filters = "Mod archives (*" + " *".join(sorted(SUPPORTED_EXTENSIONS)) + ")"
        path, _ = QFileDialog.getOpenFileName(self, "Select mod archive", "", filters)
        if not path:
            return
        default_name = Path(path).stem
        name, ok = QInputDialog.getText(self, "Mod name", "Display name:", text=default_name)
        if not ok or not name:
            return

        manager = self.ctx.mod_manager(game_id)
        try:
            manager.install_from_archive(path, name, fomod_chooser=self._run_fomod_wizard)
        except InstallCancelled:
            self.status_label.setText("Install cancelled.")
            return
        except ModManagerError as exc:
            QMessageBox.critical(self, "Install failed", str(exc))
            return
        self.ctx.notify_mods_changed(game_id)

    def _run_fomod_wizard(self, config: FomodConfig) -> InstallState | None:
        """Shown when an archive carries a FOMOD installer script. Returns
        the user's choices, or None if they cancelled."""
        dialog = FomodDialog(config, self)
        if dialog.needs_no_input:
            return dialog.state
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.state

    def _remove_selected(self) -> None:
        game_id = self._current_game_id()
        mod_ids = self._selected_mod_ids()
        if not game_id or not mod_ids:
            QMessageBox.information(self, "Remove mods", "Select one or more mods first (ctrl/shift-click for multiple).")
            return
        manager = self.ctx.mod_manager(game_id)
        reply = QMessageBox.question(
            self, "Remove mods", f"Delete the staged files for these {len(mod_ids)} mod(s) too?"
        )
        manager.remove_many(mod_ids, delete_files=reply == QMessageBox.Yes)
        self.ctx.notify_mods_changed(game_id)
        self.status_label.setText(f"Removed {len(mod_ids)} mod(s).")

    def _remove_all(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        mod_ids = [m.id for m in manager.list_mods()]
        if not mod_ids:
            QMessageBox.information(self, "Remove All", "No mods installed for this game.")
            return
        reply = QMessageBox.warning(
            self,
            "Remove All",
            f"Remove all {len(mod_ids)} mods for this game? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        delete_files_reply = QMessageBox.question(self, "Remove All", "Delete their staged files too?")
        manager.remove_many(mod_ids, delete_files=delete_files_reply == QMessageBox.Yes)
        self.ctx.notify_mods_changed(game_id)
        self.status_label.setText(
            f"Removed all {len(mod_ids)} mod(s). Deploy again to clean up any now-stale links."
        )

    def _move_selected(self, delta: int) -> None:
        game_id = self._current_game_id()
        mod_id = self._selected_mod_id()
        if not game_id or not mod_id:
            return
        manager = self.ctx.mod_manager(game_id)
        ordered = [m.id for m in manager.list_mods()]
        idx = ordered.index(mod_id)
        new_idx = max(0, min(len(ordered) - 1, idx + delta))
        if new_idx == idx:
            return
        ordered.insert(new_idx, ordered.pop(idx))
        manager.reorder(ordered)
        self.ctx.notify_mods_changed(game_id)
        self._select_mod_row(mod_id)

    def _select_mod_row(self, mod_id: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(1000) == mod_id:
                self.table.selectRow(row)
                return

    def _deploy(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        try:
            result = manager.deploy()
        except OSError as exc:
            QMessageBox.critical(self, "Deploy failed", str(exc))
            return
        msg = f"Linked {result.linked} files, removed {result.removed} stale links."
        if result.conflicts:
            msg += f"\n{len(result.conflicts)} file(s) had conflicts (last-priority mod won)."
        self.status_label.setText(msg)

    def _undeploy(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        removed = manager.undeploy()
        self.status_label.setText(f"Removed {removed} deployed files.")

    def _show_conflicts(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        conflicts = manager.preview_conflicts()
        if not conflicts:
            QMessageBox.information(self, "Conflicts", "No file conflicts among enabled mods.")
            return
        lines = []
        for path, mod_ids in sorted(conflicts.items()):
            lines.append(f"{path}\n    provided by: {', '.join(mod_ids)} (winner: {mod_ids[-1]})")
        QMessageBox.information(self, "Conflicts", "\n\n".join(lines))

    def _suggest_order(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        suggestion = manager.suggest_reorder()
        if not suggestion.changed:
            QMessageBox.information(
                self,
                "Suggest Order",
                "No conflicts found where a naming or file-count signal suggests a "
                "different winner than the current order already has. This isn't a "
                "guarantee there are no conflicts left - see Show Conflicts.",
            )
            return

        lines = [f"- {h.reason}" for h in suggestion.hints]
        shown = "\n".join(lines[:20])
        more = f"\n… and {len(lines) - 20} more" if len(lines) > 20 else ""
        reply = QMessageBox.question(
            self,
            "Suggest Order",
            f"Found {len(lines)} conflict(s) where a patch/fix name or a file-count "
            "difference suggests a specific winner. This is a heuristic based on "
            "modding conventions, not a guarantee every conflict is resolved "
            "correctly - review Show Conflicts after applying.\n\n"
            f"{shown}{more}\n\nApply this reorder?",
        )
        if reply != QMessageBox.Yes:
            return
        manager.reorder(suggestion.new_order)
        self.ctx.notify_mods_changed(game_id)
        self.status_label.setText(f"Reordered based on {len(lines)} conflict-resolution hint(s).")

    def _set_deploy_root(self) -> None:
        game_id = self._current_game_id()
        mod_ids = self._selected_mod_ids()
        if not game_id or not mod_ids:
            QMessageBox.information(
                self,
                "Deploy Target",
                "Select one or more mods first (ctrl/shift-click for multiple).",
            )
            return

        game = self.ctx.config.games[game_id]
        data_name = game.deploy_subpath or "game folder"
        choices = [
            f"Detect automatically (recommended)",
            f"{data_name} folder - normal mods (textures, meshes, plugins)",
            "Game root - script extenders, crash loggers, ENB/ReShade",
        ]
        values = [DEPLOY_ROOT_AUTO, DEPLOY_ROOT_DATA, DEPLOY_ROOT_GAME]
        choice, ok = QInputDialog.getItem(
            self,
            "Deploy Target",
            f"Where should these {len(mod_ids)} mod(s) install to?\n\n"
            "Most mods go in the data folder. Script extenders (F4SE/SKSE),\n"
            "crash loggers (Buffout) and graphics injectors (ENB, ReShade)\n"
            "only work from the game root, next to the game's .exe.",
            choices,
            0,
            False,
        )
        if not ok:
            return

        manager = self.ctx.mod_manager(game_id)
        target = values[choices.index(choice)]
        try:
            for mod_id in mod_ids:
                manager.set_deploy_root(mod_id, target)
        except ModManagerError as exc:
            QMessageBox.critical(self, "Deploy Target", str(exc))
            return
        self.ctx.notify_mods_changed(game_id)
        self.status_label.setText(
            f"Set deploy target for {len(mod_ids)} mod(s). Deploy again to apply it."
        )

    # -- plugin load order (Bethesda-style games) -----------------------------------------------------

    def _build_plugins_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 12, 0, 0)

        header = QLabel("Plugin Load Order (Bethesda-style games)")
        header.setProperty("role", "section")

        sync_btn = QPushButton("Sync from Mods")
        select_all_btn = QPushButton("Select All")
        remove_btn = QPushButton("Remove Selected")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        write_btn = QPushButton("Write Plugins.txt")
        write_btn.setProperty("role", "primary")
        import_btn = QPushButton("Import from Plugins.txt")

        sync_btn.clicked.connect(self._sync_plugins)
        select_all_btn.clicked.connect(lambda: self.plugins_table.selectAll())
        remove_btn.clicked.connect(self._remove_selected_plugins)
        up_btn.clicked.connect(lambda: self._move_plugin(-1))
        down_btn.clicked.connect(lambda: self._move_plugin(1))
        write_btn.clicked.connect(self._write_plugins_txt)
        import_btn.clicked.connect(self._import_plugins_txt)

        plugin_button_row = QHBoxLayout()
        for b in (sync_btn, select_all_btn, remove_btn, up_btn, down_btn, write_btn, import_btn):
            plugin_button_row.addWidget(b)
        plugin_button_row.addStretch(1)

        self.plugins_table = QTableWidget(0, len(PLUGIN_COLUMNS))
        self.plugins_table.setHorizontalHeaderLabels(PLUGIN_COLUMNS)
        self.plugins_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.plugins_table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # ctrl/shift-click multi-select
        plugins_header = self.plugins_table.horizontalHeader()
        plugins_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        plugins_header.setStretchLastSection(False)
        self.plugins_table.itemChanged.connect(self._on_plugin_item_changed)

        self.plugins_status_label = QLabel("")
        self.plugins_status_label.setProperty("role", "status")

        layout.addWidget(header)
        layout.addLayout(plugin_button_row)
        layout.addWidget(self.plugins_table)
        layout.addWidget(self.plugins_status_label)
        return section

    def _refresh_plugins(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            self.plugins_section.setVisible(False)
            return
        game = self.ctx.config.games[game_id]
        self.plugins_section.setVisible(game.manages_plugins)
        if not game.manages_plugins:
            return

        manager = self.ctx.mod_manager(game_id)
        plugins = manager.list_plugins()
        self.plugins_table.blockSignals(True)
        self.plugins_table.setRowCount(len(plugins))
        for row, plugin in enumerate(plugins):
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            enabled_item.setCheckState(Qt.Checked if plugin.enabled else Qt.Unchecked)
            enabled_item.setData(1000, plugin.name)
            self.plugins_table.setItem(row, 0, enabled_item)
            self.plugins_table.setItem(row, 1, QTableWidgetItem(plugin.name))
        self.plugins_table.blockSignals(False)

    def _on_plugin_item_changed(self, item) -> None:
        if item.column() != 0:
            return
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        manager.set_plugin_enabled(item.data(1000), item.checkState() == Qt.Checked)

    def _selected_plugin_name(self) -> str | None:
        rows = self.plugins_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.plugins_table.item(rows[0].row(), 0).data(1000)

    def _selected_plugin_names(self) -> list[str]:
        rows = self.plugins_table.selectionModel().selectedRows()
        return [self.plugins_table.item(r.row(), 0).data(1000) for r in rows]

    def _remove_selected_plugins(self) -> None:
        game_id = self._current_game_id()
        names = self._selected_plugin_names()
        if not game_id or not names:
            QMessageBox.information(
                self, "Remove plugins", "Select one or more plugins first (ctrl/shift-click for multiple)."
            )
            return
        manager = self.ctx.mod_manager(game_id)
        try:
            manager.remove_plugins(names)
        except ModManagerError as exc:
            QMessageBox.critical(self, "Remove plugins", str(exc))
            return
        self._refresh_plugins()
        self.plugins_status_label.setText(
            f"Removed {len(names)} plugin(s) from the tracked list. Note: they'll "
            "reappear on the next Sync from Mods if their mod is still enabled."
        )

    def _sync_plugins(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            return
        manager = self.ctx.mod_manager(game_id)
        plugins = manager.sync_plugins_from_mods()
        self._refresh_plugins()
        self.plugins_status_label.setText(f"Synced {len(plugins)} plugin(s) from enabled mods.")

    def _move_plugin(self, delta: int) -> None:
        game_id = self._current_game_id()
        name = self._selected_plugin_name()
        if not game_id or not name:
            return
        manager = self.ctx.mod_manager(game_id)
        ordered = [p.name for p in manager.list_plugins()]
        idx = ordered.index(name)
        new_idx = max(0, min(len(ordered) - 1, idx + delta))
        if new_idx == idx:
            return
        ordered.insert(new_idx, ordered.pop(idx))
        manager.reorder_plugins(ordered)
        self._refresh_plugins()
        self._select_plugin_row(name)

    def _select_plugin_row(self, name: str) -> None:
        for row in range(self.plugins_table.rowCount()):
            if self.plugins_table.item(row, 0).data(1000) == name:
                self.plugins_table.selectRow(row)
                return

    def _write_plugins_txt(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            QMessageBox.information(self, "Write Plugins.txt", "Select a game first.")
            return
        manager = self.ctx.mod_manager(game_id)
        try:
            path = manager.write_plugins_txt()
        except (ModManagerError, OSError) as exc:
            QMessageBox.critical(self, "Write Plugins.txt", f"{type(exc).__name__}: {exc}")
            return
        self.plugins_status_label.setText(f"Wrote {path}")

    def _import_plugins_txt(self) -> None:
        game_id = self._current_game_id()
        if not game_id:
            QMessageBox.information(self, "Import from Plugins.txt", "Select a game first.")
            return
        manager = self.ctx.mod_manager(game_id)
        try:
            plugins = manager.import_plugins_from_txt()
        except (ModManagerError, OSError) as exc:
            QMessageBox.critical(self, "Import from Plugins.txt", f"{type(exc).__name__}: {exc}")
            return
        self._refresh_plugins()
        self.plugins_status_label.setText(f"Imported {len(plugins)} plugin(s) from Plugins.txt.")
