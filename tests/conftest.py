"""Isolates every test from the real user config/data/cache directories."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_xdg_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield
