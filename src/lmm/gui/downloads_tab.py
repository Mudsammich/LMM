"""Downloads tab: paste an nxm:// link (from the site's "Mod Manager
Download" / "Vortex" buttons, caught by the OS handler) and watch it
download. Successful downloads for a known game are offered for install.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import context as context_module
from .. import paths
from ..models import ModSource
from ..nexus.api import NexusAPIError, NexusRateLimitError
from ..nexus.collections import CollectionAPIUnavailable, resolve_revision_bundle_url
from ..nexus.nxm import NxmCollectionLink, NxmModLink, NxmParseError, parse_nxm


class _DownloadBridge(QObject):
    """Re-emits DownloadManager callbacks as Qt signals so updates cross
    safely from worker threads back onto the GUI thread."""

    progress = Signal(str, int, int)
    done = Signal(str, str)
    error = Signal(str, str)


class DownloadsTab(QWidget):
    def __init__(self, ctx: context_module.AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._rows: dict[str, int] = {}
        self._pending_install: dict[str, str] = {}  # task_id -> game_id

        self.bridge = _DownloadBridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self.bridge.error.connect(self._on_error)

        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("paste an nxm:// link here, or a direct https:// URL")
        go_btn = QPushButton("Download")
        go_btn.setProperty("role", "primary")
        go_btn.clicked.connect(self._start_from_input)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Link:"))
        input_row.addWidget(self.link_edit, 1)
        input_row.addWidget(go_btn)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Progress", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

        layout = QVBoxLayout(self)
        layout.addLayout(input_row)
        layout.addWidget(self.table)

    # -- entry points -----------------------------------------------------

    def handle_nxm_url(self, url: str) -> None:
        """Called for links caught by the OS nxm:// handler as well as
        manually pasted ones."""
        try:
            link = parse_nxm(url)
        except NxmParseError as exc:
            QMessageBox.warning(self, "Invalid link", str(exc))
            return

        if isinstance(link, NxmModLink):
            self._start_mod_download(link)
        elif isinstance(link, NxmCollectionLink):
            self._start_collection_download(link)

    def _start_from_input(self) -> None:
        text = self.link_edit.text().strip()
        if not text:
            return
        self.link_edit.clear()
        if text.startswith("nxm://"):
            self.handle_nxm_url(text)
        elif text.startswith("http://") or text.startswith("https://"):
            self._queue_download(str(uuid.uuid4()), Path(text).name or "download", text, dest_dir=paths.download_cache_dir())
        else:
            QMessageBox.warning(self, "Unrecognised link", "Paste an nxm:// link or a direct https:// URL.")

    # -- nexus resolution -----------------------------------------------------

    def _game_for_domain(self, domain: str):
        for game in self.ctx.games():
            if game.nexus_domain == domain:
                return game
        return None

    def _start_mod_download(self, link: NxmModLink) -> None:
        client = self.ctx.nexus_client()
        try:
            mirrors = client.get_download_links(
                link.game_domain, link.mod_id, link.file_id, link.key, link.expires
            )
        except NexusAPIError as exc:
            QMessageBox.critical(self, "Download failed", str(exc))
            return
        if not mirrors:
            QMessageBox.critical(self, "Download failed", "Nexus Mods returned no download mirrors.")
            return

        game = self._game_for_domain(link.game_domain)
        dest_dir = paths.download_cache_dir()  # archives always land in the shared cache; install extracts them

        task_id = str(uuid.uuid4())
        name = f"{link.game_domain} mod {link.mod_id} file {link.file_id}"
        source = ModSource(kind="nexus", mod_id=link.mod_id, file_id=link.file_id)
        self._queue_download(task_id, name, mirrors[0]["URI"], dest_dir, source=source, game_id=game.id if game else None)

    def _start_collection_download(self, link: NxmCollectionLink) -> None:
        client = self.ctx.nexus_client()
        try:
            url = resolve_revision_bundle_url(client, link.game_domain, link.collection_slug, link.revision)
        except CollectionAPIUnavailable as exc:
            QMessageBox.information(self, "Collections", str(exc))
            return
        task_id = str(uuid.uuid4())
        name = f"collection {link.collection_slug} rev {link.revision}"
        self._queue_download(task_id, name, url, paths.download_cache_dir())

    def queue_nexus_file(
        self, domain: str, mod_id: int, file_id: int, display_name: str, game_id: str | None = None
    ) -> str | None:
        """Resolves and queues a specific Nexus mod file directly (used by
        the Collections tab, where there's no nxm key/expires pair - this
        only works for premium API keys).

        Returns an error message on failure instead of showing a dialog
        itself, so a caller queueing many files in a loop (a whole
        collection) can aggregate failures into one summary instead of one
        modal per mod. NexusRateLimitError is left to propagate uncaught,
        since a caller queueing many files needs to stop the loop on it
        rather than treat it like any other per-mod failure.
        """
        client = self.ctx.nexus_client()
        try:
            mirrors = client.get_download_links(domain, mod_id, file_id)
        except NexusRateLimitError:
            raise
        except NexusAPIError as exc:
            return str(exc)
        if not mirrors:
            return "no mirrors returned"
        task_id = str(uuid.uuid4())
        source = ModSource(kind="nexus", mod_id=mod_id, file_id=file_id)
        self._queue_download(
            task_id, display_name, mirrors[0]["URI"], paths.download_cache_dir(), source=source, game_id=game_id
        )
        return None

    # -- queueing / progress -----------------------------------------------------

    def _queue_download(
        self,
        task_id: str,
        display_name: str,
        url: str,
        dest_dir: Path,
        source: ModSource | None = None,
        game_id: str | None = None,
    ) -> None:
        dest_path = dest_dir / (Path(url.split("?")[0]).name or f"{task_id}.download")
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(display_name))
        bar = QProgressBar()
        bar.setRange(0, 100)
        self.table.setCellWidget(row, 1, bar)
        self.table.setItem(row, 2, QTableWidgetItem("queued"))
        self._rows[task_id] = row
        if game_id:
            self._pending_install[task_id] = game_id

        self.ctx.download_manager.submit(
            task_id,
            url,
            dest_path,
            on_progress=lambda d, t: self.bridge.progress.emit(task_id, d, t),
            on_done=lambda p: self.bridge.done.emit(task_id, str(p)),
            on_error=lambda e: self.bridge.error.emit(task_id, str(e)),
        )

    def _on_progress(self, task_id: str, downloaded: int, total: int) -> None:
        row = self._rows.get(task_id)
        if row is None:
            return
        bar: QProgressBar = self.table.cellWidget(row, 1)
        if total:
            bar.setValue(int(downloaded * 100 / total))
        self.table.item(row, 2).setText("downloading")

    def _on_done(self, task_id: str, dest_path: str) -> None:
        row = self._rows.get(task_id)
        if row is not None:
            self.table.item(row, 2).setText("done")
            self.table.cellWidget(row, 1).setValue(100)

        game_id = self._pending_install.pop(task_id, None)
        if not game_id:
            return
        game = self.ctx.config.games.get(game_id)
        if not game:
            return
        reply = QMessageBox.question(
            self, "Install mod", f"Downloaded for {game.name}. Install it now?"
        )
        if reply != QMessageBox.Yes:
            return
        default_name = Path(dest_path).stem
        name, ok = QInputDialog.getText(self, "Mod name", "Display name:", text=default_name)
        if not ok or not name:
            return
        manager = self.ctx.mod_manager(game_id)
        manager.install_from_archive(dest_path, name)
        self.ctx.notify_mods_changed(game_id)

    def _on_error(self, task_id: str, message: str) -> None:
        row = self._rows.get(task_id)
        if row is not None:
            self.table.item(row, 2).setText(f"error: {message}")
        self._pending_install.pop(task_id, None)
