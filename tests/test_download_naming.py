"""The one piece of downloads_tab worth unit testing without Qt: turning a
downloaded filename into the name that shows up in the mod list."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from lmm.gui.downloads_tab import mod_name_from_filename


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("AAF_UAP_v2.6.64.zip", "AAF_UAP_v2.6.64"),
        ("Extended_AAF_Patch_v1.10.ZIP", "Extended_AAF_Patch_v1.10"),
        ("Some Mod-12345-1-0.7z", "Some Mod-12345-1-0"),
        ("Legacy Thing.rar", "Legacy Thing"),
        # Already clean, or a dot that isn't an archive extension.
        ("Commonwealth Cuts 2.5.1", "Commonwealth Cuts 2.5.1"),
        ("Caliente's Beautiful Bodies Enhancer - v2.7.2", "Caliente's Beautiful Bodies Enhancer - v2.7.2"),
        # Not an archive format we handle - left alone.
        ("notes.txt", "notes.txt"),
    ],
)
def test_archive_extensions_are_trimmed(filename, expected):
    assert mod_name_from_filename(filename) == expected


def test_a_bare_extension_is_left_alone():
    """Stripping would leave nothing, which is worse than an odd name."""
    assert mod_name_from_filename(".zip") == ".zip"
