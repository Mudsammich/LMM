"""A scrollable, selectable, copyable text dialog.

QMessageBox is the wrong container for anything longer than a few lines: it
grows until it runs off the screen, clips the rest, and can't be scrolled or
searched. Reports that can legitimately be thousands of lines - conflict
listings especially - go here instead, with the full version on disk.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TextReportDialog(QDialog):
    def __init__(
        self,
        title: str,
        body: str,
        log_path: Path | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 620)
        self._log_path = log_path

        view = QPlainTextEdit()
        view.setPlainText(body)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.NoWrap)  # paths stay on one line
        # Monospace keeps the aligned counts in the summary lined up.
        view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        button_row = QHBoxLayout()
        if log_path is not None:
            path_label = QLabel(f"Full report: {log_path}")
            path_label.setProperty("role", "status")
            path_label.setWordWrap(True)
            open_btn = QPushButton("Open Log Folder")
            open_btn.clicked.connect(self._open_log_folder)
            button_row.addWidget(open_btn)
            layout_label = path_label
        else:
            layout_label = None

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(lambda: self._copy(view))
        close_btn = QPushButton("Close")
        close_btn.setProperty("role", "primary")
        close_btn.clicked.connect(self.accept)

        button_row.addWidget(copy_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(view, 1)
        if layout_label is not None:
            layout.addWidget(layout_label)
        layout.addLayout(button_row)

    def _copy(self, view: QPlainTextEdit) -> None:
        view.selectAll()
        view.copy()
        view.moveCursor(view.textCursor().Start)

    def _open_log_folder(self) -> None:
        if self._log_path is None:
            return
        # Deliberately not QDesktopServices: this is a plain file manager
        # open, and a failure here shouldn't be able to take the dialog down.
        try:
            subprocess.Popen(["xdg-open", str(self._log_path.parent)])
        except OSError:
            pass
