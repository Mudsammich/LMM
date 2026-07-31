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


# -- choosing which log to read -----------------------------------------------------


def _logs(*specs):
    """(name, minutes_ago) -> LogFile list, mirroring find_game_logs output."""
    return [
        diagnostics.LogFile(
            path=Path("/p") / name,
            modified=10_000 - minutes,
            size=1,
            category=diagnostics.classify_log(name),
        )
        for name, minutes in specs
    ]


def test_classify_log():
    assert diagnostics.classify_log("crash-2026-07-30-18-42-11.log") == diagnostics.CATEGORY_CRASH
    assert diagnostics.classify_log("f4se.log") == diagnostics.CATEGORY_EXTENDER
    assert diagnostics.classify_log("f4se_loader.log") == diagnostics.CATEGORY_LOADER
    assert diagnostics.classify_log("XDI.log") == diagnostics.CATEGORY_PLUGIN


def test_primary_log_prefers_a_crash_report_over_a_newer_plugin_log():
    """The exact case seen in the wild: XDI.log was newest, so a routine
    sigscan dump got surfaced instead of the log that explains anything."""
    logs = _logs(("XDI.log", 0), ("crash-2026-07-30.log", 30), ("f4se.log", 5))
    assert diagnostics.pick_primary_log(logs).name == "crash-2026-07-30.log"


def test_primary_log_falls_back_to_the_extender_log():
    logs = _logs(("XDI.log", 0), ("MCM.log", 1), ("f4se.log", 20))
    assert diagnostics.pick_primary_log(logs).name == "f4se.log"


def test_primary_log_picks_the_newest_within_a_category():
    logs = _logs(("crash-old.log", 100), ("crash-new.log", 1))
    assert diagnostics.pick_primary_log(logs).name == "crash-new.log"


def test_primary_log_of_nothing_is_none():
    assert diagnostics.pick_primary_log([]) is None


def test_crash_logger_absent_when_only_plugin_logs_exist():
    logs = _logs(("XDI.log", 0), ("f4se.log", 1), ("MCM.log", 2), ("LL_fourPlay.log", 3))
    assert not diagnostics.crash_logger_present(logs)


def test_crash_logger_present_from_its_own_log_before_any_crash():
    logs = _logs(("f4se.log", 1), ("Buffout4.log", 2))
    assert diagnostics.crash_logger_present(logs)


def test_crash_logger_present_from_an_actual_crash_report():
    assert diagnostics.crash_logger_present(_logs(("crash-2026-07-30.log", 1)))


# -- reading the script extender log -----------------------------------------------------

# Trimmed from a real f4se.log off a modded Fallout 4 install.
F4SE_LOG = """F4SE runtime: initialize (version = 0.7.8 010B0DD0 01DD1FD1AD5C8CB3, os = 6.2 (9200))
imagebase = 0000000140000000
checking plugin BakaFramework.dll
plugin BakaFramework.dll (00000001 BakaFramework 04010000) disabled, address library needs to be updated 0 (handle 0)
plugin WeaponDebrisCrashFix.dll (00000001 WeaponDebrisCrashFix 01040000) disabled, address library needs to be updated 0 (handle 0)
plugin SUP_F4SE.dll (00000000  00000000) no version data 0 (handle 0)
plugin mcm.dll (00000001 F4MCM 0000000A) loaded correctly (handle 5)
plugin XDI.dll (00000001 XDI 00000001) loaded correctly (handle 6)
"""


def test_decode_runtime_version_matches_known_builds():
    # The version every Fallout 4 mod page quotes, as the format check.
    assert diagnostics.decode_runtime_version("010A00A3", "0.6.23") == "1.10.163"
    assert diagnostics.decode_runtime_version("nonsense") == ""


def test_decode_runtime_version_handles_the_0_7_encoding():
    """F4SE 0.7 shifted the build up four bits to fit a sub-minor. Decoded
    with the old rule this reads 1.11.3536 - a version that doesn't exist,
    and exactly the wrong thing to go searching Nexus with."""
    assert diagnostics.decode_runtime_version("010B0DD0", "0.7.8") == "1.11.221"
    assert diagnostics.decode_runtime_version("010B0DD0", "0.6.23") == "1.11.3536"


def test_decode_runtime_version_keeps_a_nonzero_subminor():
    assert diagnostics.decode_runtime_version("010B0DD3", "0.7.8") == "1.11.221.3"


def test_decode_runtime_version_without_an_extender_version():
    """Falls back to the historically documented layout."""
    assert diagnostics.decode_runtime_version("010A00A3") == "1.10.163"


def test_summarise_extender_log_splits_loaded_from_failed():
    summary = diagnostics.summarise_extender_log(F4SE_LOG)

    assert summary.extender_version == "0.7.8"
    assert summary.runtime_raw == "010B0DD0"
    assert summary.runtime_version == "1.11.221"
    assert summary.total == 5
    assert {p.file for p in summary.loaded} == {"mcm.dll", "XDI.dll"}
    assert len(summary.failed) == 3


def test_address_library_failures_are_singled_out():
    """The line reads like any other, but it means the game version and the
    mods disagree - which is the whole diagnosis."""
    summary = diagnostics.summarise_extender_log(F4SE_LOG)

    assert {p.file for p in summary.address_library_failures} == {
        "BakaFramework.dll",
        "WeaponDebrisCrashFix.dll",
    }
    # "no version data" is a different problem and must not be lumped in.
    others = [p for p in summary.failed if not p.is_address_library_problem]
    assert [p.file for p in others] == ["SUP_F4SE.dll"]


def test_rendered_summary_explains_the_mismatch():
    rendered = "\n".join(
        diagnostics.render_extender_summary(diagnostics.summarise_extender_log(F4SE_LOG))
    )

    assert "2 of 5 plugin(s) loaded" in rendered
    assert "Address Library doesn't match" in rendered
    assert "BakaFramework.dll" in rendered
    assert "SUP_F4SE.dll" in rendered


def test_a_healthy_log_reports_no_problem():
    healthy = (
        "F4SE runtime: initialize (version = 0.6.23 010A00A3 x, os = 6.2 (9200))\n"
        "plugin mcm.dll (00000001 F4MCM 0000000A) loaded correctly (handle 1)\n"
    )
    summary = diagnostics.summarise_extender_log(healthy)
    rendered = "\n".join(diagnostics.render_extender_summary(summary))

    assert summary.address_library_failures == []
    assert "1 of 1 plugin(s) loaded" in rendered
    assert "1.10.163" in rendered
    assert "PROBLEM" not in rendered


def test_summarising_an_unrelated_log_yields_nothing():
    assert diagnostics.render_extender_summary(
        diagnostics.summarise_extender_log("XDI v1.4.2\nSigscan elapsed: 234 ms.\n")
    ) == []


# -- address library -----------------------------------------------------


def _plugins_dir(tmp_path, extender="F4SE"):
    d = tmp_path / "Data" / extender / "Plugins"
    d.mkdir(parents=True)
    return d


def test_address_library_mismatch_names_both_versions(tmp_path):
    """The extender only ever says "needs to be updated" - this says which
    version is actually installed, which is the missing half."""
    plugins = _plugins_dir(tmp_path)
    (plugins / "version-1-10-163-0.bin").write_bytes(b"")
    (plugins / "SomePlugin.dll").write_bytes(b"")

    status = diagnostics.check_address_library(tmp_path / "Data", "1.11.3536")

    assert status.installed_versions == ["1.10.163"]
    assert not status.matches
    assert "MISMATCH" in status.detail
    assert "1.10.163" in status.detail and "1.11.3536" in status.detail


def test_address_library_match_is_reported_clean(tmp_path):
    plugins = _plugins_dir(tmp_path)
    (plugins / "version-1-10-163-0.bin").write_bytes(b"")

    status = diagnostics.check_address_library(tmp_path / "Data", "1.10.163")

    assert status.matches
    assert "matches" in status.detail


def test_several_address_libraries_installed_are_all_listed(tmp_path):
    plugins = _plugins_dir(tmp_path)
    (plugins / "version-1-10-163-0.bin").write_bytes(b"")
    (plugins / "version-1-10-984-0.bin").write_bytes(b"")

    status = diagnostics.check_address_library(tmp_path / "Data", "1.10.984")

    assert status.installed_versions == ["1.10.163", "1.10.984"]
    assert status.matches  # one of them is right, which is what matters


def test_skyrim_versionlib_naming_is_recognised(tmp_path):
    plugins = _plugins_dir(tmp_path, extender="SKSE")
    (plugins / "versionlib-1-5-97-0.bin").write_bytes(b"")

    status = diagnostics.check_address_library(tmp_path / "Data", "1.5.97")

    assert status.installed_versions == ["1.5.97"]
    assert status.matches


def test_missing_address_library_is_reported(tmp_path):
    _plugins_dir(tmp_path)
    status = diagnostics.check_address_library(tmp_path / "Data", "1.10.163")

    assert status.installed_versions == []
    assert "No Address Library found" in status.detail


def test_lowercase_extender_folder_is_found(tmp_path):
    """Mods disagree about F4SE vs f4se, and on Linux that matters."""
    plugins = tmp_path / "Data" / "f4se" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "version-1-10-163-0.bin").write_bytes(b"")

    status = diagnostics.check_address_library(tmp_path / "Data", "1.10.163")

    assert status.matches


def test_no_extender_folder_at_all(tmp_path):
    (tmp_path / "Data").mkdir()
    status = diagnostics.check_address_library(tmp_path / "Data", "1.10.163")

    assert status.plugins_dir is None
    assert "No script extender Plugins folder" in status.detail
