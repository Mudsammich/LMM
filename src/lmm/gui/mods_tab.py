"""Mods tab: per-game install list, load order, and deployment."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
from ..mods.archive import SUPPORTED_EXTENSIONS
from ..mods.manager import ModManagerError

COLUMNS = ["On", "Priority", "Name", "Source"]


class ModsTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        self.game_combo = QComboBox()
        self.game_combo.currentIndexChanged.connect(self._refresh_mods)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Name

        install_btn = QPushButton("Install from archive…")
        remove_btn = QPushButton("Remove")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        deploy_btn = QPushButton("Deploy")
        deploy_btn.setProperty("role", "primary")
        undeploy_btn = QPushButton("Undeploy")
        conflicts_btn = QPushButton("Show Conflicts")

        install_btn.clicked.connect(self._install_from_archive)
        remove_btn.clicked.connect(self._remove_selected)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        deploy_btn.clicked.connect(self._deploy)
        undeploy_btn.clicked.connect(self._undeploy)
        conflicts_btn.clicked.connect(self._show_conflicts)

        button_row = QHBoxLayout()
        for b in (install_btn, remove_btn, up_btn, down_btn, deploy_btn, undeploy_btn, conflicts_btn):
            button_row.addWidget(b)
        button_row.addStretch(1)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Game:"))
        top_row.addWidget(self.game_combo, 1)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "status")

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(button_row)
        layout.addWidget(self.table)
        layout.addWidget(self.status_label)

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
            return
        manager = self.ctx.mod_manager(game_id)
        mods = manager.list_mods()
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
            source = mod.source.kind
            if mod.source.mod_id:
                source = f"nexus #{mod.source.mod_id}"
            self.table.setItem(row, 3, QTableWidgetItem(source))
        self.table.blockSignals(False)

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
            manager.install_from_archive(path, name)
        except ModManagerError as exc:
            QMessageBox.critical(self, "Install failed", str(exc))
            return
        self.ctx.notify_mods_changed(game_id)

    def _remove_selected(self) -> None:
        game_id = self._current_game_id()
        mod_id = self._selected_mod_id()
        if not game_id or not mod_id:
            return
        manager = self.ctx.mod_manager(game_id)
        reply = QMessageBox.question(self, "Remove mod", "Delete this mod's staged files too?")
        manager.remove(mod_id, delete_files=reply == QMessageBox.Yes)
        self.ctx.notify_mods_changed(game_id)

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
