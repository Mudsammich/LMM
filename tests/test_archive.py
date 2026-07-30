import zipfile

import pytest

from lmm.mods import archive


def test_is_supported():
    assert archive.is_supported("mod.zip")
    assert archive.is_supported("mod.7z")
    assert archive.is_supported("mod.rar")
    assert not archive.is_supported("mod.tar.gz")


def test_extract_zip(tmp_path):
    archive_path = tmp_path / "mod.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("sub/file.txt", "contents")

    dest = tmp_path / "out"
    archive.extract(archive_path, dest)

    assert (dest / "sub" / "file.txt").read_text() == "contents"


def test_extract_unsupported_raises(tmp_path):
    bogus = tmp_path / "mod.rpm"
    bogus.write_bytes(b"not an archive")
    with pytest.raises(archive.UnsupportedArchiveError):
        archive.extract(bogus, tmp_path / "out")


# -- wrapper-folder flattening -----------------------------------------------------


def _tree(root, paths):
    for rel in paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")


def test_flatten_strips_a_wrapping_data_folder(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["Data/Textures/thing.dds", "Data/mod.esp"])

    flattened = archive.flatten_payload_root(staging)

    assert flattened is not None
    assert (staging / "Textures" / "thing.dds").is_file()
    assert (staging / "mod.esp").is_file()
    assert not (staging / "Data").exists()


def test_flatten_strips_a_named_wrapper_folder(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["My Cool Mod v1.2/Textures/thing.dds"])

    archive.flatten_payload_root(staging)

    assert (staging / "Textures" / "thing.dds").is_file()
    assert not (staging / "My Cool Mod v1.2").exists()


def test_flatten_strips_nested_wrapper_then_data(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["My Mod v3/Data/Meshes/thing.nif"])

    archive.flatten_payload_root(staging)

    assert (staging / "Meshes" / "thing.nif").is_file()


def test_flatten_tolerates_a_readme_beside_the_wrapper(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["Data/mod.esp", "readme.txt"])

    archive.flatten_payload_root(staging)

    assert (staging / "mod.esp").is_file()


def test_flatten_leaves_a_correct_archive_alone(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["Textures/thing.dds", "mod.esp"])

    assert archive.flatten_payload_root(staging) is None
    assert (staging / "Textures" / "thing.dds").is_file()


def test_flatten_stops_at_a_fomod_folder(tmp_path):
    """A FOMOD's paths are relative to the archive root, so descending past
    it would break every path in ModuleConfig.xml."""
    staging = tmp_path / "staging"
    _tree(staging, ["fomod/ModuleConfig.xml", "00 Core/Data/mod.esp"])

    assert archive.flatten_payload_root(staging) is None
    assert (staging / "fomod" / "ModuleConfig.xml").is_file()
    assert (staging / "00 Core" / "Data" / "mod.esp").is_file()


def test_flatten_leaves_ambiguous_multi_folder_archives_alone(tmp_path):
    staging = tmp_path / "staging"
    _tree(staging, ["Option A/mod.esp", "Option B/mod.esp"])

    assert archive.flatten_payload_root(staging) is None
    assert (staging / "Option A" / "mod.esp").is_file()


def test_payload_entries_win_over_outer_duplicates(tmp_path):
    staging = tmp_path / "staging"
    (staging / "Data").mkdir(parents=True)
    (staging / "Data" / "mod.esp").write_text("inner")
    (staging / "Data" / "readme.txt").write_text("inner readme")
    (staging / "readme.txt").write_text("outer readme")

    archive.flatten_payload_root(staging)

    assert (staging / "readme.txt").read_text() == "inner readme"
