from lmm import config as config_module
from lmm.models import DeployMethod, Game


def test_round_trip(tmp_path):
    cfg = config_module.AppConfig(nexus_api_key="abc123")
    game = Game(
        id="skyrimse",
        name="Skyrim Special Edition",
        nexus_domain="skyrimspecialedition",
        install_path="/games/skyrimse",
        deploy_subpath="Data",
        mods_dir="/mods/skyrimse",
        steam_appid=489830,
        proton_prefix="/steam/compatdata/489830/pfx",
        deploy_method=DeployMethod.HARDLINK,
        manages_plugins=True,
    )
    cfg.games[game.id] = game

    config_module.save(cfg)
    loaded = config_module.load()

    assert loaded.nexus_api_key == "abc123"
    loaded_game = loaded.games["skyrimse"]
    assert loaded_game == game


def test_load_missing_file_returns_defaults():
    cfg = config_module.load()
    assert cfg.nexus_api_key == ""
    assert cfg.games == {}


def test_deploy_target_with_and_without_subpath():
    g = Game(id="a", name="A", nexus_domain="a", install_path="/games/a", deploy_subpath="Data")
    assert g.deploy_target() == "/games/a/Data"

    g2 = Game(id="b", name="B", nexus_domain="b", install_path="/games/b")
    assert g2.deploy_target() == "/games/b"
