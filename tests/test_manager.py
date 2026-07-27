import zipfile
from pathlib import Path

import pytest

from lmm.models import Game
from lmm.mods.manager import ModManager, ModManagerError, slugify


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
