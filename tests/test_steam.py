import vdf

from lmm.proton import steam


def _write_vdf(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vdf.dumps(data, pretty=True))


def _make_steam_root(root, second_library=None):
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    libraries = {"0": {"path": str(root)}}
    if second_library:
        (second_library / "steamapps").mkdir(parents=True, exist_ok=True)
        libraries["1"] = {"path": str(second_library)}
    _write_vdf(root / "steamapps" / "libraryfolders.vdf", {"libraryfolders": libraries})
    return root


def test_find_library_folders_includes_root_and_extra_libraries(tmp_path):
    root = _make_steam_root(tmp_path / "steam", second_library=tmp_path / "extra")
    libraries = steam.find_library_folders(root)
    assert root in libraries
    assert (tmp_path / "extra") in libraries


def test_find_installed_apps_parses_appmanifest(tmp_path):
    root = _make_steam_root(tmp_path / "steam")
    _write_vdf(
        root / "steamapps" / "appmanifest_489830.acf",
        {
            "AppState": {
                "appid": "489830",
                "name": "Skyrim Special Edition",
                "installdir": "Skyrim Special Edition",
            }
        },
    )

    apps = steam.find_installed_apps(root)
    assert len(apps) == 1
    app = apps[0]
    assert app.appid == 489830
    assert app.name == "Skyrim Special Edition"
    assert app.install_dir == root / "steamapps" / "common" / "Skyrim Special Edition"
    assert app.prefix_path == root / "steamapps" / "compatdata" / "489830" / "pfx"


def test_find_proton_builds_finds_official_and_custom(tmp_path):
    root = _make_steam_root(tmp_path / "steam")

    official = root / "steamapps" / "common" / "Proton 9.0"
    official.mkdir(parents=True)
    (official / "proton").write_text("#!/bin/sh\n")

    custom = root / "compatibilitytools.d" / "GE-Proton9-20"
    custom.mkdir(parents=True)
    (custom / "proton").write_text("#!/bin/sh\n")

    not_a_build = root / "steamapps" / "common" / "Proton Empty"
    not_a_build.mkdir(parents=True)  # no 'proton' script - must be ignored

    builds = steam.find_proton_builds(root)
    names = {b.name for b in builds}
    assert "Proton 9.0" in names
    assert "GE-Proton9-20" in names
    assert "Proton Empty" not in names


def test_find_steam_root_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(steam, "DEFAULT_STEAM_ROOTS", [str(tmp_path / "nonexistent")])
    assert steam.find_steam_root() is None
