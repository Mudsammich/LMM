"""Nexus Mods Collections support.

Collections are a curated mod list + load order shipped as a
``collection.json`` manifest (schema used by Vortex and the Nexus Mods
App). The reliable way to get one is exactly how Vortex gets it: the
website hands out an nxm://site/collections/{slug}/revisions/{revision}
link, which resolves to a downloadable bundle containing collection.json.

Nexus does not publish a stable, key-only REST endpoint for resolving that
bundle URL (the graphql.nexusmods.com API generally expects a browser/OAuth
session), so ``resolve_revision_bundle_url`` is best-effort: it tries the
same-shaped endpoint the regular file-download flow uses and raises
``CollectionAPIUnavailable`` with actionable guidance if Nexus rejects it.
Manual import of a collection.json (or the .zip Vortex/the site hands out)
is the dependable path and always works offline.
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
    a .zip that contains one (the format the Nexus site/Vortex hand out)."""
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
            "bundle URL. Use the website's 'Download' / 'Vortex' button to fetch "
            "the collection, then use Collections > Import collection.json in LMM. "
            f"(underlying error: {exc})"
        ) from exc
    uri = result.get("URI") if isinstance(result, dict) else None
    if not uri:
        raise CollectionAPIUnavailable(
            "Nexus Mods returned no download URL for this collection revision."
        )
    return uri
