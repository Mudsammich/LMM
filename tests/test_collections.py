import json
import zipfile

import pytest

from lmm.nexus.api import NexusAPIError
from lmm.nexus.collections import (
    CollectionAPIUnavailable,
    fetch_revision_manifest,
    import_manifest,
    parse_collection_url,
    parse_manifest,
)


SAMPLE = {
    "info": {
        "name": "My Great List",
        "author": "someone",
        "domainName": "skyrimspecialedition",
        "summary": "A curated list",
    },
    "mods": [
        {
            "name": "Unofficial Patch",
            "version": "4.3.0",
            "optional": False,
            "domainName": "skyrimspecialedition",
            "source": {"type": "nexus", "modId": 266, "fileId": 123456, "md5": "abc"},
        },
        {
            "name": "Some External Tool",
            "version": "1.0",
            "optional": True,
            "domainName": "skyrimspecialedition",
            "source": {"type": "direct", "url": "https://example.com/tool.zip"},
        },
    ],
}


def test_parse_manifest_fields():
    manifest = parse_manifest(SAMPLE)
    assert manifest.name == "My Great List"
    assert manifest.author == "someone"
    assert manifest.domain_name == "skyrimspecialedition"
    assert len(manifest.mods) == 2

    nexus_mod = manifest.mods[0]
    assert nexus_mod.is_nexus
    assert nexus_mod.mod_id == 266
    assert nexus_mod.file_id == 123456

    direct_mod = manifest.mods[1]
    assert not direct_mod.is_nexus
    assert direct_mod.optional is True
    assert direct_mod.direct_url == "https://example.com/tool.zip"


def test_import_manifest_from_json_file(tmp_path):
    path = tmp_path / "collection.json"
    path.write_text(json.dumps(SAMPLE))
    manifest = import_manifest(path)
    assert manifest.name == "My Great List"


def test_import_manifest_from_zip(tmp_path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("collection.json", json.dumps(SAMPLE))
        zf.writestr("other/README.txt", "hi")
    manifest = import_manifest(path)
    assert manifest.name == "My Great List"
    assert len(manifest.mods) == 2


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.nexusmods.com/fallout4/collections/5atq9t", ("fallout4", "5atq9t")),
        ("https://nexusmods.com/skyrimspecialedition/collections/AbC123", ("skyrimspecialedition", "AbC123")),
        (
            "https://www.nexusmods.com/games/fallout4/collections/5atq9t",
            ("fallout4", "5atq9t"),
        ),
        (
            "https://www.nexusmods.com/games/fallout4/collections/5atq9t/mods",
            ("fallout4", "5atq9t"),
        ),
        (
            "https://www.nexusmods.com/fallout4/collections/5atq9t/revisions/278",
            ("fallout4", "5atq9t"),
        ),
    ],
)
def test_parse_collection_url(url, expected):
    assert parse_collection_url(url) == expected


def test_parse_collection_url_rejects_non_collection_url():
    with pytest.raises(ValueError):
        parse_collection_url("https://www.nexusmods.com/fallout4/mods/12345")


class _StubGraphQLClient:
    """A minimal stand-in for NexusClient that only implements .graphql(),
    so fetch_revision_manifest's mapping logic can be tested without a
    live Nexus endpoint (which this sandbox's egress policy blocks)."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def graphql(self, query, variables=None):
        if self._error is not None:
            raise self._error
        return self._response


def test_fetch_revision_manifest_maps_graphql_response():
    client = _StubGraphQLClient(
        response={
            "collectionRevision": {
                "revisionNumber": 278,
                "collection": {
                    "name": "My Great List",
                    "summary": "A curated list",
                    "installInstructions": "Install in order",
                    "user": {"name": "someone"},
                },
                "modFiles": [
                    {
                        "optional": False,
                        "file": {
                            "modId": 266,
                            "fileId": 123456,
                            "name": "Unofficial Patch",
                            "version": "4.3.0",
                            "game": {"domainName": "fallout4"},
                        },
                    },
                    {
                        "optional": True,
                        "file": {
                            "modId": 99,
                            "fileId": 1,
                            "name": "Optional Extra",
                            "version": "1.0",
                            "game": {"domainName": "fallout4"},
                        },
                    },
                ],
            }
        }
    )

    manifest = fetch_revision_manifest(client, "fallout4", "5atq9t")

    assert manifest.name == "My Great List"
    assert manifest.author == "someone"
    assert len(manifest.mods) == 2
    first = manifest.mods[0]
    assert first.is_nexus
    assert first.mod_id == 266
    assert first.file_id == 123456
    assert manifest.mods[1].optional is True


def test_fetch_revision_manifest_wraps_api_errors():
    client = _StubGraphQLClient(error=NexusAPIError("boom"))
    with pytest.raises(CollectionAPIUnavailable):
        fetch_revision_manifest(client, "fallout4", "5atq9t")


def test_fetch_revision_manifest_handles_empty_response():
    client = _StubGraphQLClient(response={})
    with pytest.raises(CollectionAPIUnavailable):
        fetch_revision_manifest(client, "fallout4", "5atq9t")
