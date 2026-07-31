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


# -- off-site (direct / GitHub) sources -----------------------------------------------------


class _RoutingGraphQLClient:
    """Answers the mod-list query and the external-resources query
    separately, and can reject the wider external field sets so the
    progressive fallback is exercised. ``accept`` is the substring that must
    appear in an external query for this stub to answer it."""

    MOD_LIST = {
        "collectionRevision": {
            "collection": {"name": "List", "user": {"name": "author"}},
            "modFiles": [
                {
                    "optional": False,
                    "file": {
                        "modId": 1,
                        "fileId": 2,
                        "name": "A Nexus Mod",
                        "version": "1.0",
                        "game": {"domainName": "fallout4"},
                    },
                }
            ],
        }
    }

    def __init__(self, externals, accept="resourceType"):
        self._externals = externals
        self._accept = accept
        self.external_attempts = 0

    def graphql(self, query, variables=None):
        if "externalResources" not in query:
            return self.MOD_LIST
        self.external_attempts += 1
        if self._accept not in query:
            raise NexusAPIError("Cannot query field")
        return {"collectionRevision": {"externalResources": self._externals}}


def test_external_resources_are_appended_to_the_manifest():
    client = _RoutingGraphQLClient(
        [
            {
                "name": "xSE PluginPreloader",
                "version": "0.2.5",
                "optional": False,
                "resourceUrl": "https://github.com/owner/repo/releases/download/v0.2.5/xSE.7z",
                "resourceType": "direct",
                "fileExpression": "xSE.7z",
            }
        ]
    )

    manifest = fetch_revision_manifest(client, "fallout4", "axerbq")

    assert [m.name for m in manifest.mods] == ["A Nexus Mod", "xSE PluginPreloader"]
    offsite = manifest.mods[1]
    assert offsite.is_direct
    assert not offsite.is_nexus
    assert offsite.direct_url.endswith("xSE.7z")
    assert offsite.suggested_filename == "xSE.7z"


def test_external_resources_fall_back_to_a_narrower_field_set():
    """The exact selection set is undocumented, so a server that rejects the
    widest query must still yield results from a narrower one."""
    client = _RoutingGraphQLClient(
        [{"name": "Some Tool", "resourceUrl": "https://github.com/o/r/releases/download/v1/t.zip"}],
        accept="name resourceUrl",
    )

    manifest = fetch_revision_manifest(client, "fallout4", "axerbq")

    assert client.external_attempts > 1  # the wide sets were tried and refused
    assert manifest.mods[1].is_direct


def test_unknown_external_schema_never_breaks_the_mod_list():
    client = _RoutingGraphQLClient([], accept="this-will-never-match")

    manifest = fetch_revision_manifest(client, "fallout4", "axerbq")

    assert [m.name for m in manifest.mods] == ["A Nexus Mod"]


def test_browse_only_resources_are_not_treated_as_downloadable():
    client = _RoutingGraphQLClient(
        [
            {
                "name": "Manual Thing",
                "resourceUrl": "https://example.com/a-page",
                "resourceType": "browse",
            },
            {"name": "No URL At All", "resourceType": "direct"},
        ]
    )

    manifest = fetch_revision_manifest(client, "fallout4", "axerbq")

    for mod in manifest.mods[1:]:
        assert not mod.is_direct
        assert mod.is_browse_only


def test_direct_source_from_collection_json():
    manifest = parse_manifest(
        {
            "info": {"name": "L", "domainName": "fallout4"},
            "mods": [
                {
                    "name": "Buffout Loader",
                    "source": {
                        "type": "direct",
                        "url": "https://github.com/o/r/releases/download/v1/loader.zip",
                        "logicalFilename": "loader.zip",
                    },
                }
            ],
        }
    )

    mod = manifest.mods[0]
    assert mod.is_direct
    assert mod.suggested_filename == "loader.zip"


def test_suggested_filename_falls_back_to_the_url_tail():
    manifest = parse_manifest(
        {
            "info": {"name": "L", "domainName": "fallout4"},
            "mods": [
                {"name": "A", "source": {"type": "direct", "url": "https://x.com/dl/thing-1.2.7z"}},
                {"name": "B", "source": {"type": "direct", "url": "https://x.com/releases/latest"}},
            ],
        }
    )

    assert manifest.mods[0].suggested_filename == "thing-1.2.7z"
    # No filename in the URL - better to save nothing than a version tag.
    assert manifest.mods[1].suggested_filename == ""
