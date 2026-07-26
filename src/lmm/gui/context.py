"""Shared, in-memory application state the GUI tabs read and mutate.
Kept separate from the tabs themselves so the persistence/business logic
(config, ModManager, DownloadManager, NexusClient) has one obvious home.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .. import config as config_module
from ..models import Game
from ..mods.downloader import DownloadManager
from ..mods.manager import ModManager
from ..nexus.api import NexusClient


class AppContext(QObject):
    games_changed = Signal()
    mods_changed = Signal(str)  # game_id
    downloads_changed = Signal()

    def __init__(self):
        super().__init__()
        self.config = config_module.load()
        self.download_manager = DownloadManager(max_workers=3)
        self._mod_managers: dict[str, ModManager] = {}

    # -- config / games -----------------------------------------------------

    def save_config(self) -> None:
        config_module.save(self.config)

    def add_or_update_game(self, game: Game) -> None:
        self.config.games[game.id] = game
        self.save_config()
        self._mod_managers.pop(game.id, None)
        self.games_changed.emit()

    def remove_game(self, game_id: str) -> None:
        self.config.games.pop(game_id, None)
        self.save_config()
        self._mod_managers.pop(game_id, None)
        self.games_changed.emit()

    def games(self) -> list[Game]:
        return sorted(self.config.games.values(), key=lambda g: g.name.lower())

    # -- per-game mod manager -----------------------------------------------------

    def mod_manager(self, game_id: str) -> ModManager:
        if game_id not in self._mod_managers:
            game = self.config.games[game_id]
            self._mod_managers[game_id] = ModManager(game)
        return self._mod_managers[game_id]

    def notify_mods_changed(self, game_id: str) -> None:
        self.mods_changed.emit(game_id)

    # -- nexus -----------------------------------------------------

    def nexus_client(self) -> NexusClient:
        return NexusClient(self.config.nexus_api_key)
