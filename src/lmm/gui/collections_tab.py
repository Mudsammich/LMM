"""Collections tab: fetch a collection's mod list straight from Nexus
(no Vortex needed - see lmm.nexus.collections), or import a collection.json
by hand, then queue downloads for every Nexus-sourced mod into a chosen
game. Bulk queueing is only offered to premium accounts, since that's the
same restriction Nexus's own tools apply - LMM automates nothing a premium
key isn't already entitled to do."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import context as context_module
from .downloads_tab import DownloadsTab
from ..nexus.api import NexusAPIError, NexusRateLimitError
from ..nexus.collections import (
    CollectionAPIUnavailable,
    CollectionManifest,
    fetch_revision_manifest,
    import_manifest,
    parse_collection_url,
)

COLUMNS = ["Mod", "Version", "Optional", "Source"]


class CollectionsTab(QWidget):
    def __init__(self, ctx: context_module.AppContext, downloads_tab: DownloadsTab, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.downloads_tab = downloads_tab
        self._manifest: CollectionManifest | None = None

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("paste a collection URL, e.g. https://www.nexusmods.com/fallout4/collections/5atq9t")
        fetch_btn = QPushButton("Fetch from Nexus")
        fetch_btn.clicked.connect(self._fetch_from_nexus)
        fetch_row = QHBoxLayout()
        fetch_row.addWidget(self.url_edit, 1)
        fetch_row.addWidget(fetch_btn)

        import_btn = QPushButton("Import collection.json…")
        import_btn.clicked.connect(self._import)
        self.install_btn = QPushButton("Queue downloads for selected game")
        self.install_btn.setProperty("role", "primary")
        self.install_btn.clicked.connect(self._queue_all)
        self.install_btn.setEnabled(False)

        self.game_combo = QComboBox()
        self.ctx.games_changed.connect(self._refresh_games)
        self._refresh_games()

        self.summary_label = QLabel("No collection loaded.")

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
        layout.addLayout(fetch_row)
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

    def _fetch_from_nexus(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        try:
            domain, slug = parse_collection_url(url)
        except ValueError as exc:
            QMessageBox.warning(self, "Fetch from Nexus", str(exc))
            return

        try:
            manifest = fetch_revision_manifest(self.ctx.nexus_client(), domain, slug)
        except (CollectionAPIUnavailable, NexusAPIError) as exc:
            QMessageBox.critical(self, "Fetch failed", str(exc))
            return

        self._load_manifest(manifest)

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

        self._load_manifest(manifest)

    def _load_manifest(self, manifest: CollectionManifest) -> None:
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

        try:
            is_premium = self.ctx.nexus_client().is_premium()
        except NexusAPIError as exc:
            QMessageBox.critical(self, "Queue downloads", str(exc))
            return
        if not is_premium:
            QMessageBox.information(
                self,
                "Premium required",
                "Bulk-queueing every mod in a collection needs a premium Nexus API "
                "key - that's the same restriction Nexus's own tools apply, not an "
                "LMM limitation. With a free key, open the collection's 'Mods' tab "
                "on the website and download each mod individually; LMM's nxm:// "
                "handler will catch each one normally.",
            )
            return

        to_queue = [m for m in self._manifest.mods if not m.optional and m.is_nexus]
        skipped = sum(1 for m in self._manifest.mods if not m.optional and not m.is_nexus)

        if len(to_queue) > 25:
            reply = QMessageBox.question(
                self,
                "Queue downloads",
                f"This will resolve and queue {len(to_queue)} mods one at a time - it can "
                "take a while and may run into Nexus's API rate limit partway through "
                "(LMM will stop cleanly and report how far it got if so). Continue?",
            )
            if reply != QMessageBox.Yes:
                return

        # Downloads run concurrently, so they finish out of order - assign
        # each mod its intended priority up front (collection order,
        # appended after whatever's already installed) rather than letting
        # install order end up as whichever download happened to land first.
        manager = self.ctx.mod_manager(game_id)
        base_priority = max((m.priority for m in manager.list_mods()), default=-1) + 1

        queued = 0
        failures: list[str] = []
        rate_limited = False
        for i, mod in enumerate(to_queue, start=1):
            self.summary_label.setText(f"Queueing {i}/{len(to_queue)}: {mod.name}…")
            QApplication.processEvents()
            try:
                error = self.downloads_tab.queue_nexus_file(
                    mod.domain_name or self._manifest.domain_name,
                    mod.mod_id,
                    mod.file_id,
                    mod.name,
                    game_id=game_id,
                    priority_hint=base_priority + i - 1,
                )
            except NexusRateLimitError:
                rate_limited = True
                break
            if error:
                failures.append(f"{mod.name}: {error}")
            else:
                queued += 1

        self.summary_label.setText(
            f"{self._manifest.name} by {self._manifest.author or 'unknown'} - {len(self._manifest.mods)} mods"
        )

        message = f"Queued {queued} of {len(to_queue)} download(s)."
        if skipped:
            message += f" Skipped {skipped} non-Nexus source(s) - download those manually."
        if rate_limited:
            message += (
                f"\n\nStopped early: hit Nexus's API rate limit after {queued} mod(s). "
                "Wait for it to reset and click Queue downloads again to pick up the rest."
            )
        elif failures:
            shown = "\n".join(failures[:5])
            message += f"\n\n{len(failures)} mod(s) failed to resolve, e.g.:\n{shown}"
        QMessageBox.information(self, "Collections", message)
