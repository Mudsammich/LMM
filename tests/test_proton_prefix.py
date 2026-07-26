import pytest

from lmm.proton import prefix as proton_prefix
from lmm.proton import sandbox


@pytest.fixture
def fake_proton(tmp_path):
    proton_dir = tmp_path / "Proton-GE"
    proton_dir.mkdir()
    script = proton_dir / "proton"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    return proton_dir


@pytest.fixture
def fake_prefix(tmp_path):
    p = tmp_path / "compatdata" / "12345" / "pfx"
    p.mkdir(parents=True)
    return p


def test_run_in_prefix_builds_plain_command(monkeypatch, fake_proton, fake_prefix, tmp_path):
    captured = {}

    def fake_popen(cmd, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return "POPEN_HANDLE"

    monkeypatch.setattr(proton_prefix.subprocess, "Popen", fake_popen)

    result = proton_prefix.run_in_prefix(
        "game.exe", fake_prefix, fake_proton, steam_root=tmp_path / "steam"
    )

    assert result == "POPEN_HANDLE"
    assert captured["cmd"] == [str(fake_proton / "proton"), "run", "game.exe"]
    assert captured["env"]["STEAM_COMPAT_DATA_PATH"] == str(fake_prefix.parent)
    assert captured["env"]["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(tmp_path / "steam")


def test_run_in_prefix_wraps_with_bwrap_when_isolated(monkeypatch, fake_proton, fake_prefix, tmp_path):
    monkeypatch.setattr(sandbox, "bwrap_available", lambda: True)
    captured = {}

    def fake_popen(cmd, env=None):
        captured["cmd"] = cmd
        return "POPEN_HANDLE"

    monkeypatch.setattr(proton_prefix.subprocess, "Popen", fake_popen)

    proton_prefix.run_in_prefix(
        "game.exe",
        fake_prefix,
        fake_proton,
        steam_root=tmp_path / "steam",
        network_isolated=True,
    )

    assert captured["cmd"][0] == "bwrap"
    assert "--unshare-net" in captured["cmd"]
    assert captured["cmd"][-3:] == [str(fake_proton / "proton"), "run", "game.exe"]


def test_run_in_prefix_refuses_to_launch_unisolated_when_bwrap_missing(
    monkeypatch, fake_proton, fake_prefix, tmp_path
):
    monkeypatch.setattr(sandbox, "bwrap_available", lambda: False)
    popen_called = []
    monkeypatch.setattr(proton_prefix.subprocess, "Popen", lambda *a, **k: popen_called.append(1))

    with pytest.raises(sandbox.NetworkIsolationUnavailable):
        proton_prefix.run_in_prefix(
            "game.exe",
            fake_prefix,
            fake_proton,
            steam_root=tmp_path / "steam",
            network_isolated=True,
        )

    assert not popen_called, "must never launch without isolation when isolation was requested"


def test_run_in_prefix_raises_without_proton_script(tmp_path, fake_prefix):
    empty_dir = tmp_path / "not-proton"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        proton_prefix.run_in_prefix("game.exe", fake_prefix, empty_dir, steam_root=tmp_path)


def test_run_in_prefix_raises_without_steam_root(monkeypatch, fake_proton, fake_prefix):
    monkeypatch.setattr(proton_prefix, "find_steam_root", lambda: None)
    with pytest.raises(RuntimeError, match="Steam installation"):
        proton_prefix.run_in_prefix("game.exe", fake_prefix, fake_proton)
