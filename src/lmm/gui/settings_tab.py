"""Settings tab: Nexus API key and the nxm:// OS handler registration."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import context as context_module
from ..nexus.api import NexusAPIError
from ..nexus.nxm import register_handler


class SettingsTab(QWidget):
    def __init__(self, ctx: context_module.AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        self.api_key_edit = QLineEdit(ctx.config.nexus_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._validate_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key_edit)
        key_row.addWidget(validate_btn)

        self.default_mods_root_edit = QLineEdit(ctx.config.default_mods_root)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_mods_root)
        mods_row = QHBoxLayout()
        mods_row.addWidget(self.default_mods_root_edit)
        mods_row.addWidget(browse_btn)

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save)

        register_btn = QPushButton("Register LMM as the nxm:// download handler")
        register_btn.clicked.connect(self._register_handler)

        self.status_label = QLabel("")

        form = QFormLayout()
        form.addRow("Nexus Mods API key", key_row)
        form.addRow("Default mod staging root", mods_row)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save_btn)
        layout.addWidget(register_btn)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def _browse_mods_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select default mod staging root")
        if path:
            self.default_mods_root_edit.setText(path)

    def _save(self) -> None:
        self.ctx.config.nexus_api_key = self.api_key_edit.text().strip()
        self.ctx.config.default_mods_root = self.default_mods_root_edit.text().strip()
        self.ctx.save_config()
        self.status_label.setText("Saved.")

    def _validate_key(self) -> None:
        self._save()
        try:
            info = self.ctx.nexus_client().validate_user()
        except NexusAPIError as exc:
            QMessageBox.critical(self, "Validation failed", str(exc))
            return
        premium = "premium" if info.get("is_premium") else "free"
        QMessageBox.information(
            self, "Validated", f"Logged in as {info.get('name', '?')} ({premium} account)."
        )

    def _register_handler(self) -> None:
        try:
            path = register_handler()
        except RuntimeError as exc:
            QMessageBox.warning(self, "Registration incomplete", str(exc))
            return
        QMessageBox.information(
            self, "Registered", f"LMM is now the default nxm:// handler.\nDesktop file: {path}"
        )
