"""Parsing of nxm:// links and registration of LMM as the OS handler for
that URI scheme, so clicking "Mod Manager Download" / "Vortex" on the
Nexus Mods website hands the link straight to LMM.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DESKTOP_FILE_NAME = "lmm-nxm-handler.desktop"


class NxmParseError(ValueError):
    pass


@dataclass
class NxmModLink:
    game_domain: str
    mod_id: int
    file_id: int
    key: str | None = None
    expires: int | None = None
    user_id: int | None = None


@dataclass
class NxmCollectionLink:
    game_domain: str
    collection_slug: str
    revision: int


def parse_nxm(url: str) -> NxmModLink | NxmCollectionLink:
    """Parse an nxm:// URL into a mod-file link or a collection-revision link."""
    parsed = urlparse(url)
    if parsed.scheme != "nxm":
        raise NxmParseError(f"Not an nxm:// URL: {url!r}")

    domain = parsed.netloc
    parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if len(parts) == 4 and parts[0] == "mods" and parts[2] == "files":
        try:
            mod_id = int(parts[1])
            file_id = int(parts[3])
        except ValueError as exc:
            raise NxmParseError(f"Malformed mod nxm link: {url!r}") from exc
        key = query.get("key", [None])[0]
        expires_raw = query.get("expires", [None])[0]
        user_id_raw = query.get("user_id", [None])[0]
        return NxmModLink(
            game_domain=domain,
            mod_id=mod_id,
            file_id=file_id,
            key=key,
            expires=int(expires_raw) if expires_raw else None,
            user_id=int(user_id_raw) if user_id_raw else None,
        )

    if len(parts) == 4 and parts[0] == "collections" and parts[2] == "revisions":
        try:
            revision = int(parts[3])
        except ValueError as exc:
            raise NxmParseError(f"Malformed collection nxm link: {url!r}") from exc
        return NxmCollectionLink(
            game_domain=domain, collection_slug=parts[1], revision=revision
        )

    raise NxmParseError(f"Unrecognised nxm link shape: {url!r}")


def _applications_dir() -> Path:
    p = Path.home() / ".local" / "share" / "applications"
    p.mkdir(parents=True, exist_ok=True)
    return p


def register_handler(executable: str | None = None) -> Path:
    """Writes a .desktop file advertising LMM as an x-scheme-handler/nxm
    handler and sets it as the default via ``xdg-mime``.

    Returns the path to the written .desktop file. Raises RuntimeError if
    the ``xdg-mime`` tool (part of xdg-utils, present on any desktop
    CachyOS install) is unavailable.
    """
    exe = executable or shutil.which("lmm") or "lmm"
    desktop_path = _applications_dir() / DESKTOP_FILE_NAME
    contents = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=LMM (Linux Mod Manager)\n"
        f"Exec={exe} handle-nxm %u\n"
        "Icon=lmm\n"
        "StartupNotify=false\n"
        "NoDisplay=true\n"
        "MimeType=x-scheme-handler/nxm;\n"
    )
    desktop_path.write_text(contents, encoding="utf-8")

    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(_applications_dir())], check=False
        )

    if not shutil.which("xdg-mime"):
        raise RuntimeError(
            "xdg-mime not found (package xdg-utils). Desktop file was written to "
            f"{desktop_path} but could not be set as the default nxm handler."
        )
    subprocess.run(
        ["xdg-mime", "default", DESKTOP_FILE_NAME, "x-scheme-handler/nxm"],
        check=True,
    )
    return desktop_path
