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

from datetime import datetime
from pathlib import Path

from .context import AppContext
from .dialogs import AddEditGameDialog
from .text_report_dialog import TextReportDialog
from ..proton import diagnostics, prefix as proton_prefix
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
        diagnose_btn = QPushButton("Diagnose…")
        add_btn.clicked.connect(self._add_game)
        edit_btn.clicked.connect(self._edit_game)
        remove_btn.clicked.connect(self._remove_game)
        launch_btn.clicked.connect(self._launch_game)
        diagnose_btn.clicked.connect(self._diagnose)

        button_row = QHBoxLayout()
        button_row.addWidget(add_btn)
        button_row.addWidget(edit_btn)
        button_row.addWidget(remove_btn)
        button_row.addWidget(launch_btn)
        button_row.addWidget(diagnose_btn)
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

    def _diagnose(self) -> None:
        """Checks the things that stop a correctly-deployed modlist from
        working, and surfaces the script extender / crash logs that say what
        actually went wrong."""
        game_id = self._selected_game_id()
        if not game_id:
            QMessageBox.information(self, "Diagnose", "Select a game first.")
            return
        game = self.ctx.config.games[game_id]
        if not game.proton_prefix:
            QMessageBox.warning(self, "Diagnose", "Set this game's Proton prefix first (Edit…).")
            return

        folder = diagnostics.guess_game_folder(game.name, game.plugins_txt_path)
        status = diagnostics.check_archive_invalidation(game.proton_prefix, folder)
        logs = diagnostics.find_game_logs(game.proton_prefix, folder)

        # Checked against the real game folder rather than staging: these
        # are the game's own view, whatever put them there.
        duplicates = diagnostics.find_case_duplicates(game.install_path)

        lines = [
            f"Game folder in prefix: {folder}",
            "",
            "DUPLICATE PATHS DIFFERING ONLY IN CASE",
            "-" * 60,
        ]
        hiding = [d for d in duplicates if d.hides_something]
        empty = [d for d in duplicates if not d.hides_something]
        root = Path(game.install_path)

        if not duplicates:
            lines.append(
                "None - every path in the game folder is unique to the game, which "
                "is a Windows program and can't tell 'Scripts' from 'scripts'."
            )
        else:
            if hiding:
                lines += [
                    f"PROBLEM - {len(hiding)} location(s) hold the same name twice with",
                    "something real in at least one of them. The game finds only one, so",
                    "whatever is in the other is invisible to it.",
                    "",
                    "Mods tab > Repair Deployment clears the ones LMM created, then",
                    "Deploy lays them out correctly. Anything still listed afterwards",
                    "came from somewhere else and has to be merged or removed by hand -",
                    "move the smaller folder's contents into the larger, then delete it.",
                    "",
                ]
                for duplicate in hiding[:40]:
                    lines.append(f"  {duplicate.describe(root)}")
                if len(hiding) > 40:
                    lines.append(f"  … and {len(hiding) - 40} more")
            else:
                lines.append("No duplicate is hiding anything - nothing is being shadowed.")

            if empty:
                lines += [
                    "",
                    f"Plus {len(empty)} duplicate(s) where both sides are empty. Those",
                    "hide nothing - they're leftover folder shells - but they're still",
                    "clutter, and LMM can clear them safely since removing an empty",
                    "folder loses nothing.",
                    "",
                ]
                for duplicate in empty[:15]:
                    lines.append(f"  {duplicate.describe(root)}")
                if len(empty) > 15:
                    lines.append(f"  … and {len(empty) - 15} more")

        lines += [
            "",
            "ARCHIVE INVALIDATION",
            "-" * 60,
            ("OK - " if status.enabled else "PROBLEM - ") + status.detail,
            f"ini: {status.ini_path}",
            "",
            "SCRIPT EXTENDER / CRASH LOGS",
            "-" * 60,
        ]
        if not logs:
            lines.append(
                "No logs found. If you launched through a script extender and it "
                "crashed, no log at all usually means the extender never injected - "
                "check its loader is deployed to the game root (Mods tab, "
                "'Deploys to' column) and that its version matches the game's."
            )
        else:
            if not diagnostics.crash_logger_present(logs):
                lines += [
                    "NO CRASH LOGGER DETECTED.",
                    "",
                    "The script extender is running, but nothing here writes a crash",
                    "report - so a crash leaves no record of what caused it. Install a",
                    "crash logger (Buffout 4 for Fallout 4, Crash Logger for Skyrim),",
                    "make sure it deploys to the game root, and reproduce the crash;",
                    "it will then name the module that actually faulted.",
                    "",
                ]
            lines.append("Newest first:")
            lines.append("")
            for log in logs:
                stamp = datetime.fromtimestamp(log.modified).strftime("%Y-%m-%d %H:%M")
                lines.append(f"  [{log.category:<8}] {stamp}  {log.size:>9,} B  {log.name}")
                lines.append(f"      {log.path}")

        # Read the extender log rather than just printing it: its failures are
        # scattered among dozens of successes, and the most common one - the
        # Address Library not matching the game version - reads as an
        # unremarkable line rather than the showstopper it is.
        extender = next((l for l in logs if l.category == diagnostics.CATEGORY_EXTENDER), None)
        if extender is not None:
            summary = diagnostics.summarise_extender_log(
                diagnostics.read_log_tail(extender.path, max_bytes=256 * 1024)
            )
            rendered = diagnostics.render_extender_summary(summary)
            if rendered:
                lines += ["", *rendered]
            # The extender can only report "wrong version", never which one
            # is installed - the Address Library isn't a plugin, so it never
            # appears in its scan. Reading the .bin filenames names it.
            address = diagnostics.check_address_library(
                game.deploy_target(), summary.runtime_version
            )
            lines += ["", "ADDRESS LIBRARY", "-" * 60, address.detail]
            if address.plugins_dir:
                lines.append(f"looked in: {address.plugins_dir}")

        primary = diagnostics.pick_primary_log(logs)
        if primary is not None:
            # Chosen by how diagnostic it is, not by timestamp: every plugin
            # rewrites its log each launch, so the newest file is usually
            # just whichever one happened to finish last.
            lines += ["", "=" * 60, f"MOST USEFUL LOG: {primary.name}", "=" * 60, ""]
            lines.append(diagnostics.read_log_tail(primary.path))

        dialog = TextReportDialog(f"Diagnose - {game.name}", "\n".join(lines), parent=self)
        dialog.exec()

        if empty:
            reply = QMessageBox.question(
                self,
                "Empty duplicate folders",
                f"Remove {len(empty)} empty folder(s) that exist only as a "
                "differently-capitalised copy of a folder beside them?\n\n"
                "Each one is empty, so nothing is lost, and the version beside it "
                "stays - so the path itself doesn't disappear, it just stops "
                "existing twice.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                pruned = diagnostics.prune_empty_case_duplicates(game.install_path)
                QMessageBox.information(
                    self, "Empty duplicate folders", f"Removed {pruned} empty folder(s)."
                )

        if hiding:
            self._offer_repair(game_id, game)

        if not status.enabled:
            reply = QMessageBox.question(
                self,
                "Archive invalidation",
                "Set up archive invalidation now?\n\n"
                f"This writes the [Archive] settings into {status.ini_path}, keeping "
                "anything already in that file. Without them the game ignores every "
                "loose file LMM deploys, so mods appear to do nothing.",
            )
            if reply == QMessageBox.Yes:
                try:
                    written = diagnostics.enable_archive_invalidation(game.proton_prefix, folder)
                except OSError as exc:
                    QMessageBox.critical(self, "Archive invalidation", f"{type(exc).__name__}: {exc}")
                    return
                QMessageBox.information(
                    self, "Archive invalidation", f"Written to {written}"
                )

    def _offer_repair(self, game_id: str, game) -> None:
        """Diagnose found case-duplicate folders, which is exactly what
        Repair Deployment fixes - so offer it here rather than sending the
        user to another tab to find it."""
        manager = self.ctx.mod_manager(game_id)
        count = manager.count_managed_links()
        if not count:
            QMessageBox.information(
                self,
                "Repair Deployment",
                "None of those duplicate folders hold links LMM created, so there's "
                "nothing it can safely remove - they were put there by hand or by "
                "another tool, and need clearing manually.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Repair Deployment",
            f"Remove the {count} link(s) LMM has deployed into the game folder now?\n\n"
            "Only symlinks pointing into this game's mod staging folder are removed, "
            "so the game's own files are never touched, and your installed mods are "
            "unaffected. Deploy afterwards to lay them out correctly.\n\n"
            "Anything still duplicated after this came from somewhere other than LMM.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            links, dirs = manager.repair_deployment()
        except OSError as exc:
            QMessageBox.critical(self, "Repair Deployment", f"{type(exc).__name__}: {exc}")
            return
        remaining = diagnostics.find_case_duplicates(game.install_path)
        message = f"Removed {links} link(s) and {dirs} emptied folder(s).\n\n"
        message += (
            "No case-duplicate folders remain. Deploy your mods again from the Mods tab."
            if not remaining
            else f"{len(remaining)} case-duplicate location(s) remain - those weren't "
            "created by LMM and need removing by hand. Run Diagnose again to list them."
        )
        QMessageBox.information(self, "Repair Deployment", message)

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
