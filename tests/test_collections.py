import json
import zipfile

from lmm.nexus.collections import import_manifest, parse_manifest


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
