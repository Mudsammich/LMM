"""Top-level window: ties the tabs together over a shared AppContext."""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from .context import AppContext
from .collections_tab import CollectionsTab
from .downloads_tab import DownloadsTab
from .games_tab import GamesTab
from .mods_tab import ModsTab
from .settings_tab import SettingsTab


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext | None = None):
        super().__init__()
        self.ctx = ctx or AppContext()
        self.setWindowTitle("LMM - Linux Mod Manager")
        self.resize(1000, 650)

        tabs = QTabWidget()
        self.games_tab = GamesTab(self.ctx)
        self.mods_tab = ModsTab(self.ctx)
        self.downloads_tab = DownloadsTab(self.ctx)
        self.collections_tab = CollectionsTab(self.ctx, self.downloads_tab)
        self.settings_tab = SettingsTab(self.ctx)

        tabs.addTab(self.games_tab, "Games")
        tabs.addTab(self.mods_tab, "Mods")
        tabs.addTab(self.downloads_tab, "Downloads")
        tabs.addTab(self.collections_tab, "Collections")
        tabs.addTab(self.settings_tab, "Settings")

        self.setCentralWidget(tabs)

    def handle_nxm_url(self, url: str) -> None:
        self.downloads_tab.handle_nxm_url(url)
