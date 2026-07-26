"""Nexus Mods Collections support.

Collections are a curated mod list + load order. Clicking "Vortex" / "Add
collection" on the website does **not** hand your browser a downloadable
file - it's a protocol handoff that only a full mod-manager app can
consume, and there's no public REST endpoint for the download bundle
itself (see ``resolve_revision_bundle_url``).

That said, *viewing* a collection is public - it isn't premium-gated, only
bulk-downloading one is - so its mod list is available straight from the
same GraphQL API the website's own collection page calls to render itself.
``fetch_revision_manifest`` queries that directly: no Vortex, no cookies,
no login flow, just the same data anyone loading the page already gets.
The query shape is undocumented for third-party use and reconstructed
best-effort, so treat failures as "the schema needs adjusting," not "this
approach doesn't work" - the raised error carries the raw GraphQL response.

Getting the manifest this way is independent of account tier. Actually
*queueing* every mod's download automatically, however, only works for
premium keys (regular download_link.json rules apply per mod, same as
everywhere else in this app) - callers should check
``NexusClient.is_premium()`` before bulk-queueing and fall back to the
manual per-mod flow otherwise, exactly as Nexus's own tools do.

The fallback paths remain available if the GraphQL query ever breaks:
(1) run Vortex/the Nexus Mods App once to fetch the collection, then copy
collection.json out of its profile directory and import it via
``import_manifest``, or (2) skip the manifest entirely and download each
mod in the collection's "Mods" tab individually - those are ordinary
per-file nxm links LMM already handles.
"""
from __future__ import annotations

import json
import re
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


_COLLECTION_URL_RE = re.compile(r"nexusmods\.com/(?:games/)?([a-z0-9]+)/collections/([a-zA-Z0-9]+)")


def parse_collection_url(url: str) -> tuple[str, str]:
    """Parses an ordinary browser URL into (game_domain, collection_slug).
    Handles both URL shapes Nexus uses:
    https://www.nexusmods.com/fallout4/collections/5atq9t and
    https://www.nexusmods.com/games/fallout4/collections/5atq9t(/mods)."""
    match = _COLLECTION_URL_RE.search(url)
    if not match:
        raise ValueError(f"Not a recognisable Nexus Mods collection URL: {url!r}")
    return match.group(1), match.group(2)


_COLLECTION_REVISION_QUERY = """
query CollectionRevision($slug: String!, $domain: String!, $revision: Int) {
  collectionRevision(slug: $slug, domainName: $domain, revision: $revision) {
    revisionNumber
    collection {
      name
      summary
      installInstructions
      user { name }
    }
    modFiles {
      optional
      file {
        modId
        fileId
        name
        version
        game { domainName }
      }
    }
  }
}
"""


def fetch_revision_manifest(
    client: NexusClient, game_domain: str, slug: str, revision: int | None = None
) -> CollectionManifest:
    """Fetches a collection's manifest straight from Nexus's GraphQL API -
    see the module docstring for why this needs neither Vortex nor a
    manually-imported collection.json, and why the query shape is
    best-effort. ``revision=None`` asks for the latest published revision.
    """
    try:
        data = client.graphql(
            _COLLECTION_REVISION_QUERY,
            {"slug": slug, "domain": game_domain, "revision": revision},
        )
    except NexusAPIError as exc:
        raise CollectionAPIUnavailable(
            f"Couldn't fetch collection '{slug}' ({game_domain}) via the GraphQL API "
            "- its schema is undocumented and may have shifted. Fall back to "
            "Import collection.json, or report the error below so the query can be "
            f"fixed. (underlying error: {exc})"
        ) from exc

    revision_data = data.get("collectionRevision")
    if not revision_data:
        raise CollectionAPIUnavailable(
            f"Nexus Mods returned no data for collection '{slug}' ({game_domain})."
        )

    info = revision_data.get("collection") or {}
    mods: list[CollectionModRef] = []
    for entry in revision_data.get("modFiles") or []:
        f = entry.get("file") or {}
        mods.append(
            CollectionModRef(
                name=f.get("name", "unknown"),
                version=f.get("version", ""),
                optional=bool(entry.get("optional", False)),
                domain_name=(f.get("game") or {}).get("domainName", game_domain),
                source_type="nexus",
                mod_id=f.get("modId"),
                file_id=f.get("fileId"),
            )
        )

    return CollectionManifest(
        name=info.get("name", slug),
        author=(info.get("user") or {}).get("name", ""),
        summary=info.get("summary", ""),
        domain_name=game_domain,
        install_instructions=info.get("installInstructions", ""),
        mods=mods,
    )
