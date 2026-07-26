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

COLUMNS = ["Name", "Nexus domain", "Install path", "Proton prefix", "Deploy method"]


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
        add_btn.clicked.connect(self._add_game)
        edit_btn.clicked.connect(self._edit_game)
        remove_btn.clicked.connect(self._remove_game)

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(edit_btn)
        button_row.addWidget(remove_btn)
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
