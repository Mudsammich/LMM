import pytest

from lmm.nexus.nxm import NxmCollectionLink, NxmModLink, NxmParseError, parse_nxm


def test_parse_mod_link_with_key_and_expires():
    url = (
        "nxm://skyrimspecialedition/mods/12345/files/67890"
        "?key=abcDEF&expires=1750000000&user_id=42"
    )
    link = parse_nxm(url)
    assert isinstance(link, NxmModLink)
    assert link.game_domain == "skyrimspecialedition"
    assert link.mod_id == 12345
    assert link.file_id == 67890
    assert link.key == "abcDEF"
    assert link.expires == 1750000000
    assert link.user_id == 42


def test_parse_mod_link_without_query_params():
    link = parse_nxm("nxm://fallout4/mods/1/files/2")
    assert link.key is None
    assert link.expires is None


def test_parse_collection_link():
    link = parse_nxm("nxm://site/collections/my-great-list/revisions/3")
    assert isinstance(link, NxmCollectionLink)
    assert link.game_domain == "site"
    assert link.collection_slug == "my-great-list"
    assert link.revision == 3


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/not-nxm",
        "nxm://domain/mods/notanumber/files/2",
        "nxm://domain/mods/1/files/2/extra",
        "nxm://domain/unknown/shape",
    ],
)
def test_parse_rejects_bad_input(url):
    with pytest.raises(NxmParseError):
        parse_nxm(url)
