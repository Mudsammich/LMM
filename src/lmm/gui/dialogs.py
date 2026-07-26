"""Modal dialogs used by the GUI tabs."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QCheckBox,
    QWidget,
)

from ..models import DeployMethod, Game
from ..mods.manager import slugify
from ..proton import steam as proton_steam


def _browse_row(line_edit: QLineEdit, directory: bool = True, parent: QWidget | None = None) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(line_edit)
    button = QPushButton("Browse…")

    def _browse() -> None:
        if directory:
            path = QFileDialog.getExistingDirectory(parent, "Select directory", line_edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(parent, "Select file", line_edit.text())
        if path:
            line_edit.setText(path)

    button.clicked.connect(_browse)
    layout.addWidget(button)
    return row


class AddEditGameDialog(QDialog):
    """Add a new Game, or edit an existing one (pass ``game``)."""

    def __init__(self, game: Game | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Game" if game else "Add Game")
        self._editing = game

        self.name_edit = QLineEdit(game.name if game else "")
        self.domain_edit = QLineEdit(game.nexus_domain if game else "")
        self.domain_edit.setPlaceholderText("e.g. skyrimspecialedition, fallout4, cyberpunk2077")
        self.install_edit = QLineEdit(game.install_path if game else "")
        self.deploy_subpath_edit = QLineEdit(game.deploy_subpath if game else "Data")
        self.mods_dir_edit = QLineEdit(game.mods_dir if game else "")
        self.appid_edit = QSpinBox()
        self.appid_edit.setRange(0, 9_999_999)
        self.appid_edit.setValue(game.steam_appid or 0 if game else 0)
        self.prefix_edit = QLineEdit(game.proton_prefix if game else "")
        self.proton_version_edit = QLineEdit(game.proton_version_path if game else "")
        self.deploy_method_combo = QComboBox()
        self.deploy_method_combo.addItems([m.value for m in DeployMethod])
        if game:
            self.deploy_method_combo.setCurrentText(game.deploy_method.value)
        self.manages_plugins_check = QCheckBox("Manage Bethesda-style plugin load order")
        if game:
            self.manages_plugins_check.setChecked(game.manages_plugins)

        detect_button = QPushButton("Detect from Steam…")
        detect_button.clicked.connect(self._detect_from_steam)

        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Nexus Mods game domain", self.domain_edit)
        form.addRow("Game install path", _browse_row(self.install_edit, parent=self))
        form.addRow("Deploy subfolder (under install path)", self.deploy_subpath_edit)
        form.addRow("Mod staging directory", _browse_row(self.mods_dir_edit, parent=self))
        form.addRow("Steam AppID", self.appid_edit)
        form.addRow("Proton prefix (pfx) path", _browse_row(self.prefix_edit, parent=self))
        form.addRow("Proton build path", _browse_row(self.proton_version_edit, parent=self))
        form.addRow("Deploy method", self.deploy_method_combo)
        form.addRow(self.manages_plugins_check)
        form.addRow(detect_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._result_game: Game | None = None

    def _detect_from_steam(self) -> None:
        apps = proton_steam.find_installed_apps()
        if not apps:
            QMessageBox.information(self, "Detect from Steam", "No Steam apps found.")
            return
        names = [f"{a.name} ({a.appid})" for a in apps]
        from PySide6.QtWidgets import QInputDialog

        choice, ok = QInputDialog.getItem(self, "Detect from Steam", "Select an installed app:", names, 0, False)
        if not ok:
            return
        app = apps[names.index(choice)]
        self.name_edit.setText(app.name)
        self.install_edit.setText(str(app.install_dir))
        self.appid_edit.setValue(app.appid)
        if app.prefix_path.is_dir():
            self.prefix_edit.setText(str(app.prefix_path))
        builds = proton_steam.find_proton_builds()
        if builds:
            self.proton_version_edit.setText(str(builds[-1].path))

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        install_path = self.install_edit.text().strip()
        if not name or not install_path:
            QMessageBox.warning(self, "Missing fields", "Name and install path are required.")
            return

        game_id = self._editing.id if self._editing else slugify(name)
        mods_dir = self.mods_dir_edit.text().strip()

        self._result_game = Game(
            id=game_id,
            name=name,
            nexus_domain=self.domain_edit.text().strip(),
            install_path=install_path,
            deploy_subpath=self.deploy_subpath_edit.text().strip(),
            mods_dir=mods_dir,
            steam_appid=self.appid_edit.value() or None,
            proton_prefix=self.prefix_edit.text().strip(),
            proton_version_path=self.proton_version_edit.text().strip(),
            deploy_method=DeployMethod(self.deploy_method_combo.currentText()),
            manages_plugins=self.manages_plugins_check.isChecked(),
        )
        self.accept()

    def result_game(self) -> Game | None:
        return self._result_game
