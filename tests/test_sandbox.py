import pytest

from lmm.proton import sandbox


def test_wrap_command_prepends_bwrap_with_unshare_net(monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_available", lambda: True)
    wrapped = sandbox.wrap_command(["proton", "run", "game.exe"])

    assert wrapped[0] == "bwrap"
    assert "--unshare-net" in wrapped
    assert "--die-with-parent" in wrapped
    # the original command must still be present, in order, at the end
    assert wrapped[-3:] == ["proton", "run", "game.exe"]


def test_wrap_command_binds_full_filesystem(monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_available", lambda: True)
    wrapped = sandbox.wrap_command(["echo", "hi"])
    # --dev-bind / / must appear so the sandbox keeps X11/Wayland/GPU/audio access
    idx = wrapped.index("--dev-bind")
    assert wrapped[idx : idx + 3] == ["--dev-bind", "/", "/"]


def test_wrap_command_raises_when_bwrap_missing(monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_available", lambda: False)
    with pytest.raises(sandbox.NetworkIsolationUnavailable):
        sandbox.wrap_command(["proton", "run", "game.exe"])
