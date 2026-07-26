"""Games tab: add/edit/remove configured games and their Proton links."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .context import AppContext
from .dialogs import AddEditGameDialog
from ..proton import prefix as proton_prefix
from ..proton.sandbox import NetworkIsolationUnavailable

COLUMNS = ["Name", "Nexus domain", "Install path", "Proton prefix", "Network", "Deploy method"]


class GamesTab(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)

        add_btn = QPushButton("Add Game…")
        edit_btn = QPushButton("Edit…")
        remove_btn = QPushButton("Remove")
        launch_btn = QPushButton("Launch Game")
        launch_btn.setProperty("role", "primary")
        add_btn.clicked.connect(self._add_game)
        edit_btn.clicked.connect(self._edit_game)
        remove_btn.clicked.connect(self._remove_game)
        launch_btn.clicked.connect(self._launch_game)

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(edit_btn)
        button_row.addWidget(remove_btn)
        button_row.addWidget(launch_btn)
        button_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(button_row)
        layout.addWidget(self.table)

        self.ctx.games_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        games = self.ctx.games()
        self.table.setRowCount(len(games))
        for row, game in enumerate(games):
            values = [
                game.name,
                game.nexus_domain,
                game.install_path,
                game.proton_prefix or "(none)",
                "isolated (no network)" if game.network_isolated else "normal",
                game.deploy_method.value,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(1000, game.id)  # stash id for lookup
                self.table.setItem(row, col, item)

    def _selected_game_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(1000)

    def _add_game(self) -> None:
        dialog = AddEditGameDialog(parent=self)
        if dialog.exec():
            game = dialog.result_game()
            if game:
                self.ctx.add_or_update_game(game)

    def _edit_game(self) -> None:
        game_id = self._selected_game_id()
        if not game_id:
            QMessageBox.information(self, "Edit Game", "Select a game first.")
            return
        game = self.ctx.config.games[game_id]
        dialog = AddEditGameDialog(game=game, parent=self)
        if dialog.exec():
            updated = dialog.result_game()
            if updated:
                self.ctx.add_or_update_game(updated)

    def _launch_game(self) -> None:
        game_id = self._selected_game_id()
        if not game_id:
            QMessageBox.information(self, "Launch Game", "Select a game first.")
            return
        game = self.ctx.config.games[game_id]

        missing = [
            label
            for label, value in (
                ("game executable", game.launch_executable),
                ("Proton prefix", game.proton_prefix),
                ("Proton build path", game.proton_version_path),
            )
            if not value
        ]
        if missing:
            QMessageBox.warning(
                self,
                "Launch Game",
                f"Set the {', '.join(missing)} for this game first (Edit…).",
            )
            return

        try:
            proton_prefix.run_in_prefix(
                exe_path=game.launch_executable,
                prefix_path=game.proton_prefix,
                proton_path=game.proton_version_path,
                network_isolated=game.network_isolated,
            )
        except NetworkIsolationUnavailable as exc:
            QMessageBox.critical(self, "Launch Game", str(exc))
        except (FileNotFoundError, RuntimeError) as exc:
            QMessageBox.critical(self, "Launch Game", str(exc))

    def _remove_game(self) -> None:
        game_id = self._selected_game_id()
        if not game_id:
            QMessageBox.information(self, "Remove Game", "Select a game first.")
            return
        game = self.ctx.config.games[game_id]
        reply = QMessageBox.question(
            self,
            "Remove Game",
            f"Remove '{game.name}' from LMM? This does not delete any files on disk.",
        )
        if reply == QMessageBox.Yes:
            self.ctx.remove_game(game_id)
