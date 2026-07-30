from pathlib import Path

from lmm.proton import diagnostics


def _make_prefix(tmp_path):
    prefix = tmp_path / "prefix"
    (prefix / "drive_c" / "users" / "steamuser" / "My Documents").mkdir(parents=True)
    (prefix / "user.reg").write_text("")
    return prefix


def test_guess_game_folder_prefers_the_plugins_txt_folder():
    folder = diagnostics.guess_game_folder(
        "Fallout 4", "/p/drive_c/users/steamuser/AppData/Local/Fallout4/Plugins.txt"
    )
    assert folder == "Fallout4"


def test_guess_game_folder_falls_back_to_the_name():
    assert diagnostics.guess_game_folder("Fallout 4") == "Fallout4"


def test_missing_ini_reports_not_enabled(tmp_path):
    prefix = _make_prefix(tmp_path)
    status = diagnostics.check_archive_invalidation(prefix, "Fallout4")

    assert not status.exists
    assert not status.enabled
    assert "ignores every loose file" in status.detail


def test_enable_then_check_reports_enabled(tmp_path):
    prefix = _make_prefix(tmp_path)
    written = diagnostics.enable_archive_invalidation(prefix, "Fallout4")

    assert written.name == "Fallout4Custom.ini"
    status = diagnostics.check_archive_invalidation(prefix, "Fallout4")
    assert status.exists and status.enabled
    body = written.read_text()
    assert "bInvalidateOlderFiles=1" in body
    assert "sResourceDataDirsFinal=" in body


def test_enable_preserves_unrelated_settings(tmp_path):
    prefix = _make_prefix(tmp_path)
    path = diagnostics.custom_ini_path(prefix, "Fallout4")
    path.parent.mkdir(parents=True)
    path.write_text("[Display]\niPresentInterval=0\n")

    diagnostics.enable_archive_invalidation(prefix, "Fallout4")

    body = path.read_text()
    assert "iPresentInterval=0" in body
    assert "bInvalidateOlderFiles=1" in body


def test_partially_applied_settings_are_reported_as_a_problem(tmp_path):
    """A missing sResourceDataDirsFinal is the usual half-applied case, and
    it doesn't work - so it must not read as OK."""
    prefix = _make_prefix(tmp_path)
    path = diagnostics.custom_ini_path(prefix, "Fallout4")
    path.parent.mkdir(parents=True)
    path.write_text("[Archive]\nbInvalidateOlderFiles=1\n")

    status = diagnostics.check_archive_invalidation(prefix, "Fallout4")

    assert status.exists
    assert not status.enabled
    assert status.missing == ["sResourceDataDirsFinal"]


def test_case_variant_keys_are_recognised_and_not_duplicated(tmp_path):
    prefix = _make_prefix(tmp_path)
    path = diagnostics.custom_ini_path(prefix, "Fallout4")
    path.parent.mkdir(parents=True)
    path.write_text("[Archive]\nbinvalidateolderfiles=1\nsresourcedatadirsfinal=\n")

    assert diagnostics.check_archive_invalidation(prefix, "Fallout4").enabled

    diagnostics.enable_archive_invalidation(prefix, "Fallout4")
    body = path.read_text().lower()
    assert body.count("binvalidateolderfiles") == 1


def test_find_game_logs_newest_first(tmp_path):
    import os
    import time

    prefix = _make_prefix(tmp_path)
    log_dir = prefix / "drive_c" / "users" / "steamuser" / "My Documents" / "My Games" / "Fallout4" / "F4SE"
    log_dir.mkdir(parents=True)
    old = log_dir / "f4se.log"
    new = log_dir / "crash-2026-07-30.log"
    old.write_text("old")
    new.write_text("boom")
    os.utime(old, (time.time() - 5000, time.time() - 5000))

    logs = diagnostics.find_game_logs(prefix, "Fallout4")

    assert [f.path.name for f in logs] == ["crash-2026-07-30.log", "f4se.log"]


def test_find_game_logs_handles_a_never_launched_game(tmp_path):
    assert diagnostics.find_game_logs(_make_prefix(tmp_path), "Fallout4") == []


def test_read_log_tail_truncates_a_large_file(tmp_path):
    big = tmp_path / "big.log"
    big.write_text("x" * 200_000)

    body = diagnostics.read_log_tail(big, max_bytes=1024)

    assert "truncated" in body
    assert len(body) < 5_000


def test_read_log_tail_returns_a_small_file_whole(tmp_path):
    small = tmp_path / "small.log"
    small.write_text("just this")
    assert diagnostics.read_log_tail(small) == "just this"


def test_modern_proton_documents_folder_is_found(tmp_path):
    """Current Proton names it "Documents"; only checking "My Documents"
    would report a game as having no logs at all."""
    prefix = tmp_path / "prefix"
    log_dir = prefix / "drive_c/users/steamuser/Documents/My Games/Fallout4/F4SE"
    log_dir.mkdir(parents=True)
    (log_dir / "crash-1.log").write_text("boom")

    logs = diagnostics.find_game_logs(prefix, "Fallout4")

    assert [f.path.name for f in logs] == ["crash-1.log"]


def test_legacy_my_documents_folder_is_still_found(tmp_path):
    prefix = tmp_path / "prefix"
    log_dir = prefix / "drive_c/users/steamuser/My Documents/My Games/Fallout4/F4SE"
    log_dir.mkdir(parents=True)
    (log_dir / "f4se.log").write_text("hi")

    assert [f.path.name for f in diagnostics.find_game_logs(prefix, "Fallout4")] == ["f4se.log"]


def test_ini_lands_in_the_prefixs_existing_documents_folder(tmp_path):
    prefix = tmp_path / "prefix"
    (prefix / "drive_c/users/steamuser/Documents").mkdir(parents=True)

    written = diagnostics.enable_archive_invalidation(prefix, "Fallout4")

    assert "/Documents/My Games/Fallout4/" in str(written)
    assert "My Documents" not in str(written)
