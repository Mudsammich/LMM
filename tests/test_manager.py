import zipfile
from pathlib import Path

import pytest

from lmm.models import Game
from lmm.mods.fomod_install import InstallState
from lmm.mods.manager import InstallCancelled, ModManager, ModManagerError, slugify


@pytest.fixture
def game(tmp_path):
    install = tmp_path / "install"
    (install / "Data").mkdir(parents=True)
    mods_dir = tmp_path / "mods_staging"
    mods_dir.mkdir()
    return Game(
        id="testgame",
        name="Test Game",
        nexus_domain="testgame",
        install_path=str(install),
        deploy_subpath="Data",
        mods_dir=str(mods_dir),
    )


def _make_zip(path, files: dict[str, str]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_slugify():
    assert slugify("My Cool Mod!") == "my-cool-mod"
    assert slugify("") == "mod"


def test_install_extracts_and_records_mod(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "My Mod")

    assert mod.enabled is True
    assert mod.priority == 0
    staged_file = tmp_path / "mods_staging" / mod.staging_subdir / "file.txt"
    assert staged_file.read_text() == "hi"

    # Reload from disk to confirm persistence.
    manager2 = ModManager(game)
    assert [m.id for m in manager2.list_mods()] == [mod.id]


def test_duplicate_names_get_distinct_staging_dirs(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})

    manager = ModManager(game)
    mod1 = manager.install_from_archive(archive_path, "Same Name")
    mod2 = manager.install_from_archive(archive_path, "Same Name")

    assert mod1.staging_subdir != mod2.staging_subdir
    assert mod2.priority == 1


def test_install_rejects_unsupported_archive(tmp_path, game):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("not an archive")
    manager = ModManager(game)
    with pytest.raises(ModManagerError):
        manager.install_from_archive(bogus, "Bad")


def test_reorder_and_enable(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})
    manager = ModManager(game)
    a = manager.install_from_archive(archive_path, "A")
    b = manager.install_from_archive(archive_path, "B")

    manager.reorder([b.id, a.id])
    ordered = [m.id for m in manager.list_mods()]
    assert ordered == [b.id, a.id]

    manager.set_enabled(a.id, False)
    assert manager.get(a.id).enabled is False


def test_remove_deletes_staged_files_when_requested(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})
    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "A")
    staged_dir = tmp_path / "mods_staging" / mod.staging_subdir
    assert staged_dir.exists()

    manager.remove(mod.id, delete_files=True)

    assert manager.get(mod.id) is None
    assert not staged_dir.exists()


def test_remove_many_deletes_all_given_mods(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})
    manager = ModManager(game)
    mods = [manager.install_from_archive(archive_path, f"Mod {i}") for i in range(5)]

    to_remove = [m.id for m in mods[:3]]
    removed = manager.remove_many(to_remove, delete_files=True)

    assert {m.id for m in removed} == set(to_remove)
    remaining_ids = {m.id for m in manager.list_mods()}
    assert remaining_ids == {mods[3].id, mods[4].id}
    for mod_id in to_remove:
        staged_dir = tmp_path / "mods_staging" / mod_id
        assert not staged_dir.exists()


def test_remove_many_is_all_or_nothing_on_unknown_id(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})
    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "A")

    with pytest.raises(ModManagerError, match="No such mod"):
        manager.remove_many([mod.id, "does-not-exist"])

    # Nothing removed - the valid id in the batch must survive the failure.
    assert manager.get(mod.id) is not None


def test_deploy_end_to_end_through_manager(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"textures/rock.dds": "data", "mod.esp": "esp"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "A")

    result = manager.deploy()
    assert result.linked == 2

    deployed_dir = tmp_path / "install" / "Data"
    assert (deployed_dir / "mod.esp").is_symlink()
    assert (deployed_dir / "textures" / "rock.dds").is_symlink()

    removed = manager.undeploy()
    assert removed == 2
    assert deployed_dir.is_dir()


def test_sync_plugins_from_mods_detects_and_persists(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"mod.esp": "esp", "textures/rock.dds": "data"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "A Mod")

    plugins = manager.sync_plugins_from_mods()
    assert [p.name for p in plugins] == ["mod.esp"]
    assert plugins[0].enabled is True

    # Persisted - a fresh ModManager for the same game sees it too.
    manager2 = ModManager(game)
    assert [p.name for p in manager2.list_plugins()] == ["mod.esp"]


def test_sync_plugins_ignores_disabled_mods(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"mod.esp": "esp"})
    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "A Mod")
    manager.set_enabled(mod.id, False)

    plugins = manager.sync_plugins_from_mods()
    assert plugins == []


def test_set_plugin_enabled_and_reorder(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"a.esp": "x", "b.esp": "x"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "Two Plugins")
    manager.sync_plugins_from_mods()

    manager.set_plugin_enabled("a.esp", False)
    plugins = {p.name: p for p in manager.list_plugins()}
    assert plugins["a.esp"].enabled is False
    assert plugins["b.esp"].enabled is True

    manager.reorder_plugins(["b.esp", "a.esp"])
    assert [p.name for p in manager.list_plugins()] == ["b.esp", "a.esp"]


def test_set_plugin_enabled_unknown_plugin_raises(game):
    manager = ModManager(game)
    with pytest.raises(ModManagerError):
        manager.set_plugin_enabled("nope.esp", True)


def test_remove_plugins_multiple_at_once(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"a.esp": "x", "b.esp": "x", "c.esp": "x"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "Three Plugins")
    manager.sync_plugins_from_mods()

    manager.remove_plugins(["a.esp", "c.esp"])

    assert [p.name for p in manager.list_plugins()] == ["b.esp"]


def test_remove_plugins_unknown_name_raises_and_removes_nothing(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"a.esp": "x"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "One Plugin")
    manager.sync_plugins_from_mods()

    with pytest.raises(ModManagerError, match="No such plugin"):
        manager.remove_plugins(["a.esp", "nope.esp"])

    # all-or-nothing - a.esp must survive the failed batch
    assert [p.name for p in manager.list_plugins()] == ["a.esp"]


def test_write_plugins_txt_requires_configured_path(game):
    manager = ModManager(game)
    with pytest.raises(ModManagerError, match="No Plugins.txt path"):
        manager.write_plugins_txt()


def test_write_plugins_txt_writes_to_configured_path(tmp_path, game):
    game.plugins_txt_path = str(tmp_path / "Plugins.txt")
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"mod.esp": "esp"})
    manager = ModManager(game)
    manager.install_from_archive(archive_path, "A Mod")
    manager.sync_plugins_from_mods()

    written_path = manager.write_plugins_txt()

    assert written_path == Path(game.plugins_txt_path)
    assert written_path.read_text(encoding="utf-8") == "*mod.esp\n"


def test_write_plugins_txt_rejects_directory_path_with_clear_message(tmp_path, game):
    """Regression test: pointing plugins_txt_path at the containing folder
    (e.g. mixing it up with LOOT's separate "game local path" setting,
    which does want the folder) used to raise a raw IsADirectoryError with
    no indication of what was wrong."""
    folder = tmp_path / "AppData" / "Local" / "Fallout4"
    folder.mkdir(parents=True)
    game.plugins_txt_path = str(folder)
    manager = ModManager(game)

    with pytest.raises(ModManagerError, match="is a folder"):
        manager.write_plugins_txt()


def test_import_plugins_from_txt_rejects_directory_path(tmp_path, game):
    folder = tmp_path / "AppData" / "Local" / "Fallout4"
    folder.mkdir(parents=True)
    game.plugins_txt_path = str(folder)
    manager = ModManager(game)

    with pytest.raises(ModManagerError, match="is a folder"):
        manager.import_plugins_from_txt()


def test_import_plugins_from_txt_resyncs_state(tmp_path, game):
    game.plugins_txt_path = str(tmp_path / "Plugins.txt")
    Path(game.plugins_txt_path).write_text("*FromLoot.esm\nInactive.esp\n", encoding="utf-8")

    manager = ModManager(game)
    imported = manager.import_plugins_from_txt()

    assert [p.name for p in imported] == ["FromLoot.esm", "Inactive.esp"]
    assert imported[0].enabled is True
    assert imported[1].enabled is False
    # Persisted too.
    manager2 = ModManager(game)
    assert [p.name for p in manager2.list_plugins()] == ["FromLoot.esm", "Inactive.esp"]


def test_install_with_explicit_priority_is_used_as_is(tmp_path, game):
    archive_path = tmp_path / "mod.zip"
    _make_zip(archive_path, {"file.txt": "hi"})

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Late Mod", priority=7)

    assert mod.priority == 7
    # Next unhinted install still appends after the *actual* current max,
    # not after the hint - so it doesn't collide with earlier real mods.
    mod2 = manager.install_from_archive(archive_path, "Next Mod")
    assert mod2.priority == 8


def test_out_of_order_installs_preserve_intended_priority(tmp_path, game):
    """Simulates a collection where downloads (and so installs) complete in
    a different order than the collection's authored order - install_from_archive's
    priority argument must make the final list_mods() order match the
    intended order, not the completion order."""
    archive_a = tmp_path / "a.zip"
    archive_b = tmp_path / "b.zip"
    _make_zip(archive_a, {"a.esp": "x"})
    _make_zip(archive_b, {"b.esp": "x"})

    manager = ModManager(game)
    # "B" was authored second (priority 1) but its download finishes first.
    mod_b = manager.install_from_archive(archive_b, "Mod B", priority=1)
    mod_a = manager.install_from_archive(archive_a, "Mod A", priority=0)

    assert [m.id for m in manager.list_mods()] == [mod_a.id, mod_b.id]


def test_root_mod_deploys_beside_the_executable(tmp_path, game):
    """End to end: a Buffout-style archive must put its loader at the game
    root and its plugin in the real Data folder, not Data/Data."""
    archive_path = tmp_path / "buffout.zip"
    _make_zip(
        archive_path,
        {"WinHTTP.dll": "loader", "Data/F4SE/Plugins/buffout.dll": "plugin"},
    )

    manager = ModManager(game)
    manager.install_from_archive(archive_path, "Buffout 4")
    manager.deploy()

    install = tmp_path / "install"
    assert (install / "WinHTTP.dll").read_text() == "loader"
    assert (install / "Data" / "F4SE" / "Plugins" / "buffout.dll").read_text() == "plugin"
    assert not (install / "Data" / "Data").exists()
    assert not (install / "Data" / "WinHTTP.dll").exists()


def test_set_deploy_root_overrides_detection(tmp_path, game):
    archive_path = tmp_path / "odd.zip"
    _make_zip(archive_path, {"weird.dll": "x"})

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Odd Mod")
    assert manager.deploy_roots()[mod.id] == "game_root"

    manager.set_deploy_root(mod.id, "data")
    assert manager.deploy_roots()[mod.id] == "data"

    # Survives a reload from disk.
    assert ModManager(game).deploy_roots()[mod.id] == "data"

    manager.deploy()
    assert (tmp_path / "install" / "Data" / "weird.dll").read_text() == "x"


def test_set_deploy_root_rejects_an_unknown_value(tmp_path, game):
    archive_path = tmp_path / "m.zip"
    _make_zip(archive_path, {"a.esp": "x"})
    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "M")
    with pytest.raises(ModManagerError):
        manager.set_deploy_root(mod.id, "somewhere-else")


def test_plugins_are_still_detected_with_root_relative_paths(tmp_path, game):
    archive_path = tmp_path / "m.zip"
    _make_zip(archive_path, {"Thing.esp": "x", "Textures/t.dds": "y"})

    manager = ModManager(game)
    manager.install_from_archive(archive_path, "Plugin Mod")

    assert [p.name for p in manager.sync_plugins_from_mods()] == ["Thing.esp"]


def test_install_flattens_a_data_wrapped_archive(tmp_path, game):
    """A mod packaged as Data/... must land as Textures/... in staging, or
    every file deploys one level too deep for the game to find."""
    archive_path = tmp_path / "wrapped.zip"
    _make_zip(archive_path, {"Data/Textures/thing.dds": "x", "Data/mod.esp": "y"})

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Wrapped Mod")

    staging = tmp_path / "mods_staging" / mod.staging_subdir
    assert (staging / "Textures" / "thing.dds").is_file()
    assert (staging / "mod.esp").is_file()
    assert not (staging / "Data").exists()


_FOMOD_CONFIG = """<config>
  <moduleName>Fancy Mod</moduleName>
  <requiredInstallFiles>
    <folder source="00 Core" destination=""/>
  </requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Flavour">
      <optionalFileGroups order="Explicit">
        <group name="Pick one" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Red">
              <description>Red version</description>
              <files><folder source="01 Red" destination=""/></files>
              <typeDescriptor><type name="Recommended"/></typeDescriptor>
            </plugin>
            <plugin name="Blue">
              <description>Blue version</description>
              <files><folder source="02 Blue" destination=""/></files>
              <typeDescriptor><type name="Optional"/></typeDescriptor>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"""


def _make_fomod_zip(path):
    _make_zip(
        path,
        {
            "fomod/ModuleConfig.xml": _FOMOD_CONFIG,
            "00 Core/Textures/base.dds": "base",
            "01 Red/Textures/colour.dds": "red",
            "02 Blue/Textures/colour.dds": "blue",
        },
    )


def test_fomod_install_uses_author_defaults_without_a_chooser(tmp_path, game):
    """A bulk install can't prompt, so it takes the installer's own
    Required/Recommended defaults - never the raw scaffolding."""
    archive_path = tmp_path / "fancy.zip"
    _make_fomod_zip(archive_path)

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Fancy Mod")

    staging = tmp_path / "mods_staging" / mod.staging_subdir
    assert (staging / "Textures" / "base.dds").read_text() == "base"
    assert (staging / "Textures" / "colour.dds").read_text() == "red"  # Recommended
    # The installer's scaffolding must not survive into the mod.
    assert not (staging / "00 Core").exists()
    assert not (staging / "01 Red").exists()
    assert not (staging / "02 Blue").exists()


def test_fomod_chooser_selection_is_honoured(tmp_path, game):
    archive_path = tmp_path / "fancy.zip"
    _make_fomod_zip(archive_path)

    def choose_blue(config):
        state = InstallState()
        state.select((0, 0, 1))  # Blue
        return state

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Fancy Mod", fomod_chooser=choose_blue)

    staging = tmp_path / "mods_staging" / mod.staging_subdir
    assert (staging / "Textures" / "colour.dds").read_text() == "blue"


def test_fomod_cancel_leaves_nothing_behind(tmp_path, game):
    archive_path = tmp_path / "fancy.zip"
    _make_fomod_zip(archive_path)

    manager = ModManager(game)
    with pytest.raises(InstallCancelled):
        manager.install_from_archive(archive_path, "Fancy Mod", fomod_chooser=lambda config: None)

    assert manager.list_mods() == []
    assert not (tmp_path / "mods_staging" / "fancy-mod").exists()
    # And the scratch extraction dir is cleaned up too.
    assert list((tmp_path / "mods_staging").glob(".*")) == []


def test_broken_fomod_script_falls_back_to_installing_whole_archive(tmp_path, game):
    archive_path = tmp_path / "broken.zip"
    _make_zip(
        archive_path,
        {"fomod/ModuleConfig.xml": "<config><unclosed", "Textures/thing.dds": "x"},
    )

    manager = ModManager(game)
    mod = manager.install_from_archive(archive_path, "Broken Fomod")

    staging = tmp_path / "mods_staging" / mod.staging_subdir
    assert (staging / "Textures" / "thing.dds").read_text() == "x"


def test_suggest_reorder_moves_patch_after_the_mod_it_patches(tmp_path, game):
    big_archive = tmp_path / "big.zip"
    _make_zip(big_archive, {f"file{i}.esp": "x" for i in range(20)})
    patch_archive = tmp_path / "patch.zip"
    _make_zip(patch_archive, {"file0.esp": "y"})  # conflicts on file0.esp

    manager = ModManager(game)
    patch_mod = manager.install_from_archive(patch_archive, "Big Mod Fix Patch")  # installed first
    big_mod = manager.install_from_archive(big_archive, "Big Mod")

    assert patch_mod.priority < big_mod.priority  # currently loses to Big Mod

    suggestion = manager.suggest_reorder()
    assert suggestion.changed
    assert suggestion.new_order.index(patch_mod.id) > suggestion.new_order.index(big_mod.id)

    manager.reorder(suggestion.new_order)
    reloaded = {m.id: m for m in manager.list_mods()}
    assert reloaded[patch_mod.id].priority > reloaded[big_mod.id].priority


def test_concurrent_installs_do_not_corrupt_state(tmp_path, game):
    """Regression guard for backgrounding installs off the GUI thread:
    many archives installing in parallel, with GUI-thread-style
    remove/enable/reorder calls interleaved on the same ModManager, must
    never crash, lose an install, or corrupt mods.json."""
    import threading

    manager = ModManager(game)
    archive_paths = []
    for i in range(20):
        path = tmp_path / f"mod{i}.zip"
        _make_zip(path, {f"mod{i}.esp": "x"})
        archive_paths.append(path)

    installed_ids: list[str] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def install_worker(path, index):
        try:
            mod = manager.install_from_archive(path, f"Mod {index}")
            with lock:
                installed_ids.append(mod.id)
        except Exception as exc:  # noqa: BLE001 - test wants to see any failure
            with lock:
                errors.append(exc)

    def churn_worker():
        # Simulates the GUI thread poking the same ModManager while
        # installs are draining in the background.
        for _ in range(50):
            for mod in manager.list_mods():
                manager.set_enabled(mod.id, True)

    install_threads = [
        threading.Thread(target=install_worker, args=(p, i)) for i, p in enumerate(archive_paths)
    ]
    churn_threads = [threading.Thread(target=churn_worker) for _ in range(3)]

    for t in install_threads + churn_threads:
        t.start()
    for t in install_threads + churn_threads:
        t.join(timeout=30)

    assert not errors, f"unexpected errors during concurrent installs: {errors}"
    assert len(installed_ids) == 20
    assert len(set(installed_ids)) == 20, "duplicate/colliding mod ids - a race clobbered a slot"

    # Reload from disk into a fresh manager - proves mods.json itself
    # ended up consistent, not just the in-memory dict.
    reloaded = ModManager(game)
    assert {m.id for m in reloaded.list_mods()} == set(installed_ids)
