"""Nexus Mods Collections support.

Collections are a curated mod list + load order shipped as a
``collection.json`` manifest (schema used by Vortex and the Nexus Mods
App). Clicking "Vortex" / "Add collection" on the website does **not**
hand your browser a downloadable file - it's a protocol handoff (an
nxm://site/collections/{slug}/revisions/{revision} link, same shape as a
regular mod nxm link) that only a full mod-manager app can consume. Vortex
or the Nexus Mods App resolve it via an authenticated/OAuth session and
write collection.json into their own profile directory - there is no
public, key-only REST endpoint LMM can call to get that bundle itself.

``resolve_revision_bundle_url`` is a best-effort attempt at the same-shaped
endpoint the regular file-download flow uses, kept in case Nexus ever
exposes this; expect it to fail (``CollectionAPIUnavailable``) today. The
dependable paths are: (1) run Vortex/the Nexus Mods App once to fetch the
collection, then copy collection.json out of its profile directory and
import it here, or (2) skip the manifest entirely and download each mod
in the collection's "Mods" tab individually - those are ordinary per-file
nxm links LMM already handles.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import NexusClient, NexusAPIError


class CollectionAPIUnavailable(RuntimeError):
    pass


@dataclass
class CollectionModRef:
    name: str
    version: str = ""
    optional: bool = False
    domain_name: str = ""
    source_type: str = "nexus"  # "nexus" | "direct" | "browse"
    mod_id: int | None = None
    file_id: int | None = None
    md5: str = ""
    file_size: int = 0
    logical_filename: str = ""
    direct_url: str = ""

    @property
    def is_nexus(self) -> bool:
        return self.source_type == "nexus" and self.mod_id and self.file_id


@dataclass
class CollectionManifest:
    name: str
    author: str = ""
    summary: str = ""
    domain_name: str = ""
    install_instructions: str = ""
    mods: list[CollectionModRef] = field(default_factory=list)


def parse_manifest(data: dict[str, Any]) -> CollectionManifest:
    info = data.get("info", {})
    mods: list[CollectionModRef] = []
    for m in data.get("mods", []):
        source = m.get("source", {}) or {}
        mods.append(
            CollectionModRef(
                name=m.get("name", "unknown"),
                version=m.get("version", ""),
                optional=bool(m.get("optional", False)),
                domain_name=m.get("domainName", info.get("domainName", "")),
                source_type=source.get("type", "nexus"),
                mod_id=source.get("modId"),
                file_id=source.get("fileId"),
                md5=source.get("md5", ""),
                file_size=int(source.get("fileSize") or 0),
                logical_filename=source.get("logicalFilename", ""),
                direct_url=source.get("url", ""),
            )
        )
    return CollectionManifest(
        name=info.get("name", "Unnamed collection"),
        author=info.get("author", ""),
        summary=info.get("summary", ""),
        domain_name=info.get("domainName", ""),
        install_instructions=info.get("installInstructions", ""),
        mods=mods,
    )


def import_manifest(path: str | Path) -> CollectionManifest:
    """Load a collection manifest from a ``collection.json`` file, or from
    a .zip that contains one. There's no way to get either straight from
    the website - pull collection.json out of a Vortex/Nexus Mods App
    profile directory after it fetches the collection once."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            candidates = [n for n in zf.namelist() if n.endswith("collection.json")]
            if not candidates:
                raise ValueError(f"No collection.json found inside {path}")
            with zf.open(candidates[0]) as fh:
                data = json.load(fh)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    return parse_manifest(data)


def resolve_revision_bundle_url(
    client: NexusClient, game_domain: str, slug: str, revision: int
) -> str:
    """Best-effort lookup of the downloadable bundle for a collection
    revision, mirroring the regular mod-file download_link.json shape.
    """
    try:
        result = client._get(  # noqa: SLF001 - deliberate reuse of the low-level GET
            f"/games/{game_domain}/collections/{slug}/revisions/{revision}/download_link.json"
        )
    except NexusAPIError as exc:
        raise CollectionAPIUnavailable(
            "Nexus Mods has no public key-only API for resolving a collection "
            "bundle URL. Either run Vortex/the Nexus Mods App once to fetch this "
            "collection and import the collection.json from its profile directory "
            "here (Collections > Import collection.json), or open the collection's "
            "'Mods' tab on the website and download each mod individually - those "
            "are ordinary nxm links LMM already handles. "
            f"(underlying error: {exc})"
        ) from exc
    uri = result.get("URI") if isinstance(result, dict) else None
    if not uri:
        raise CollectionAPIUnavailable(
            "Nexus Mods returned no download URL for this collection revision."
        )
    return uri
