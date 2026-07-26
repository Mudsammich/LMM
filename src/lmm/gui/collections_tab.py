"""Collections tab: import a collection.json (or the .zip Vortex/the site
hand out) and queue downloads for every Nexus-sourced mod into a chosen
game. Bulk collection downloads need a premium Nexus API key - see
lmm.nexus.collections for why."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import context as context_module
from .downloads_tab import DownloadsTab
from ..nexus.collections import CollectionManifest, import_manifest

COLUMNS = ["Mod", "Version", "Optional", "Source"]


class CollectionsTab(QWidget):
    def __init__(self, ctx: context_module.AppContext, downloads_tab: DownloadsTab, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.downloads_tab = downloads_tab
        self._manifest: CollectionManifest | None = None

        import_btn = QPushButton("Import collection.json…")
        import_btn.clicked.connect(self._import)
        self.install_btn = QPushButton("Queue downloads for selected game")
        self.install_btn.setProperty("role", "primary")
        self.install_btn.clicked.connect(self._queue_all)
        self.install_btn.setEnabled(False)

        self.game_combo = QComboBox()
        self.ctx.games_changed.connect(self._refresh_games)
        self._refresh_games()

        self.summary_label = QLabel("No collection imported.")

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

        top_row = QHBoxLayout()
        top_row.addWidget(import_btn)
        top_row.addWidget(QLabel("Install into:"))
        top_row.addWidget(self.game_combo)
        top_row.addWidget(self.install_btn)
        top_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def _refresh_games(self) -> None:
        current = self.game_combo.currentData()
        self.game_combo.clear()
        for game in self.ctx.games():
            self.game_combo.addItem(game.name, game.id)
        if current:
            idx = self.game_combo.findData(current)
            if idx >= 0:
                self.game_combo.setCurrentIndex(idx)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import collection", "", "Collection files (*.json *.zip)"
        )
        if not path:
            return
        try:
            manifest = import_manifest(path)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return

        self._manifest = manifest
        self.install_btn.setEnabled(True)
        self.summary_label.setText(
            f"{manifest.name} by {manifest.author or 'unknown'} - {len(manifest.mods)} mods"
        )
        self.table.setRowCount(len(manifest.mods))
        for row, mod in enumerate(manifest.mods):
            source = "manual / other" if not mod.is_nexus else f"nexus #{mod.mod_id} file {mod.file_id}"
            self.table.setItem(row, 0, QTableWidgetItem(mod.name))
            self.table.setItem(row, 1, QTableWidgetItem(mod.version))
            self.table.setItem(row, 2, QTableWidgetItem("yes" if mod.optional else "no"))
            self.table.setItem(row, 3, QTableWidgetItem(source))

        idx = self.game_combo.findData(
            next((g.id for g in self.ctx.games() if g.nexus_domain == manifest.domain_name), None)
        )
        if idx >= 0:
            self.game_combo.setCurrentIndex(idx)

    def _queue_all(self) -> None:
        if not self._manifest:
            return
        game_id = self.game_combo.currentData()
        if not game_id:
            QMessageBox.warning(self, "Queue downloads", "Add and select a game first.")
            return

        skipped = 0
        queued = 0
        for mod in self._manifest.mods:
            if mod.optional:
                continue
            if not mod.is_nexus:
                skipped += 1
                continue
            self.downloads_tab.queue_nexus_file(
                mod.domain_name or self._manifest.domain_name,
                mod.mod_id,
                mod.file_id,
                mod.name,
                game_id=game_id,
            )
            queued += 1

        message = f"Queued {queued} download(s)."
        if skipped:
            message += f" Skipped {skipped} non-Nexus source(s) - download those manually."
        QMessageBox.information(self, "Collections", message)
