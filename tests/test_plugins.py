from pathlib import Path

from lmm.mods.plugins import (
    Plugin,
    detect_plugins,
    import_from_plugins_txt,
    load_plugins,
    save_plugins,
    sync_plugins,
    write_plugins_txt,
)


def test_detect_plugins_only_top_level_matching_extensions():
    links = {
        "mod.esp": Path("/mods/a/mod.esp"),
        "master.esm": Path("/mods/a/master.esm"),
        "light.esl": Path("/mods/a/light.esl"),
        "textures/rock.dds": Path("/mods/a/textures/rock.dds"),
        "nested/deep.esp": Path("/mods/a/nested/deep.esp"),  # not top-level - ignored
        "readme.txt": Path("/mods/a/readme.txt"),
    }
    assert detect_plugins(links) == ["light.esl", "master.esm", "mod.esp"]


def test_detect_plugins_case_insensitive_extension():
    links = {"Weird.ESP": Path("/x/Weird.ESP")}
    assert detect_plugins(links) == ["Weird.ESP"]


def test_sync_plugins_preserves_order_and_enabled_state():
    existing = [
        Plugin(name="b.esp", enabled=False),
        Plugin(name="a.esp", enabled=True),
    ]
    updated = sync_plugins(existing, ["a.esp", "b.esp", "c.esp"])

    assert [p.name for p in updated] == ["b.esp", "a.esp", "c.esp"]
    assert updated[0].enabled is False  # preserved
    assert updated[1].enabled is True
    assert updated[2].enabled is True  # newly detected defaults to enabled


def test_sync_plugins_drops_plugins_no_longer_detected():
    existing = [Plugin(name="gone.esp"), Plugin(name="still-here.esp")]
    updated = sync_plugins(existing, ["still-here.esp"])
    assert [p.name for p in updated] == ["still-here.esp"]


def test_save_and_load_plugins_round_trip(tmp_path):
    plugins = [Plugin(name="a.esm", enabled=True), Plugin(name="b.esp", enabled=False)]
    save_plugins(tmp_path, plugins)
    loaded = load_plugins(tmp_path)
    assert loaded == plugins


def test_load_plugins_missing_file_returns_empty(tmp_path):
    assert load_plugins(tmp_path) == []


def test_write_plugins_txt_uses_star_prefix_for_enabled(tmp_path):
    path = tmp_path / "Plugins.txt"
    write_plugins_txt(
        path,
        [
            Plugin(name="Fallout4.esm", enabled=True),
            Plugin(name="DisabledMod.esp", enabled=False),
            Plugin(name="Unofficial Patch.esp", enabled=True),
        ],
    )
    content = path.read_text(encoding="utf-8")
    assert content == "*Fallout4.esm\nDisabledMod.esp\n*Unofficial Patch.esp\n"


def test_write_plugins_txt_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dirs" / "Plugins.txt"
    write_plugins_txt(path, [Plugin(name="a.esp")])
    assert path.exists()


def test_import_from_plugins_txt_round_trips_with_writer(tmp_path):
    path = tmp_path / "Plugins.txt"
    original = [
        Plugin(name="Fallout4.esm", enabled=True),
        Plugin(name="Inactive.esp", enabled=False),
    ]
    write_plugins_txt(path, original)
    imported = import_from_plugins_txt(path)
    assert imported == original


def test_import_from_plugins_txt_skips_blank_and_comment_lines(tmp_path):
    path = tmp_path / "Plugins.txt"
    path.write_text("*Fallout4.esm\n\n# a comment\nInactive.esp\n", encoding="utf-8")
    imported = import_from_plugins_txt(path)
    assert imported == [
        Plugin(name="Fallout4.esm", enabled=True),
        Plugin(name="Inactive.esp", enabled=False),
    ]


def test_import_from_plugins_txt_missing_file_returns_empty(tmp_path):
    assert import_from_plugins_txt(tmp_path / "nope.txt") == []


def test_detect_plugins_looks_inside_the_data_prefix():
    """Deploy plans are game-root-relative now, so plugins live one level
    down under the data folder."""
    links = {
        "Data/Thing.esp": None,
        "Data/Other.esm": None,
        "Data/Textures/notaplugin.dds": None,
        "Data/F4SE/Plugins/nested.esp": None,  # too deep to be a real plugin
        "WinHTTP.dll": None,
        "RootLevel.esp": None,  # in the game root, not the data folder
    }
    assert detect_plugins(links, data_prefix="Data") == ["Other.esm", "Thing.esp"]


def test_detect_plugins_matches_the_prefix_case_insensitively():
    assert detect_plugins({"data/Thing.esp": None}, data_prefix="Data") == ["Thing.esp"]


def test_detect_plugins_without_a_prefix_uses_top_level():
    """Games that mod straight into their root have no data subfolder."""
    assert detect_plugins({"Thing.esp": None, "sub/Other.esp": None}) == ["Thing.esp"]
