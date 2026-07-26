"""Extraction of downloaded mod archives (zip / 7z / rar) into a mod's
staging directory."""
from __future__ import annotations

import zipfile
from pathlib import Path

import py7zr
import rarfile

SUPPORTED_EXTENSIONS = {".zip", ".7z", ".rar"}


class UnsupportedArchiveError(ValueError):
    pass


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def extract(archive_path: str | Path, dest_dir: str | Path) -> Path:
    """Extracts ``archive_path`` into ``dest_dir`` (created if needed) and
    returns dest_dir. Raises UnsupportedArchiveError for unknown formats
    and OSError-derived exceptions on corrupt archives.
    """
    archive_path = Path(archive_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
    elif suffix == ".7z":
        with py7zr.SevenZipFile(archive_path, mode="r") as zf:
            zf.extractall(path=dest_dir)
    elif suffix == ".rar":
        with rarfile.RarFile(archive_path) as rf:
            rf.extractall(path=dest_dir)
    else:
        raise UnsupportedArchiveError(f"Unsupported archive type: {archive_path}")

    return dest_dir
