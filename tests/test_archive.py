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
