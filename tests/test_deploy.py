import os
from pathlib import Path

from lmm.models import DeployMethod, InstalledMod
from lmm.mods import deploy


def _make_mod_file(mods_dir: Path, subdir: str, rel_path: str, content: str) -> None:
    path = mods_dir / subdir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_build_plan_last_mod_wins_conflicts(tmp_path):
    mods_dir = tmp_path / "mods"
    _make_mod_file(mods_dir, "mod-a", "shared.txt", "from A")
    _make_mod_file(mods_dir, "mod-a", "only-a.txt", "only A")
    _make_mod_file(mods_dir, "mod-b", "shared.txt", "from B")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    mod_b = InstalledMod(id="mod-b", name="B", game_id="g", staging_subdir="mod-b", priority=1)

    plan = deploy.build_plan(mods_dir, [mod_a, mod_b])

    assert plan.links["shared.txt"] == mods_dir / "mod-b" / "shared.txt"
    assert plan.links["only-a.txt"] == mods_dir / "mod-a" / "only-a.txt"
    assert plan.conflicts == {"shared.txt": ["mod-a", "mod-b"]}


def test_apply_plan_creates_and_replaces_symlinks(tmp_path):
    mods_dir = tmp_path / "mods"
    target_dir = tmp_path / "game" / "Data"
    state_dir = tmp_path / "state"
    _make_mod_file(mods_dir, "mod-a", "file.txt", "v1")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    plan = deploy.build_plan(mods_dir, [mod_a])
    result = deploy.apply_plan(plan, target_dir, state_dir, DeployMethod.SYMLINK)

    dest = target_dir / "file.txt"
    assert result.linked == 1
    assert dest.is_symlink()
    assert dest.read_text() == "v1"
    assert os.path.realpath(dest) == str((mods_dir / "mod-a" / "file.txt").resolve())


def test_apply_plan_removes_stale_links_from_previous_deploy(tmp_path):
    mods_dir = tmp_path / "mods"
    target_dir = tmp_path / "game" / "Data"
    state_dir = tmp_path / "state"
    _make_mod_file(mods_dir, "mod-a", "a.txt", "a")
    _make_mod_file(mods_dir, "mod-b", "b.txt", "b")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    mod_b = InstalledMod(id="mod-b", name="B", game_id="g", staging_subdir="mod-b", priority=1)

    plan1 = deploy.build_plan(mods_dir, [mod_a, mod_b])
    deploy.apply_plan(plan1, target_dir, state_dir)
    assert (target_dir / "a.txt").exists()
    assert (target_dir / "b.txt").exists()

    # Re-deploy with only mod_a enabled - mod_b's link must disappear.
    plan2 = deploy.build_plan(mods_dir, [mod_a])
    result2 = deploy.apply_plan(plan2, target_dir, state_dir)

    assert (target_dir / "a.txt").exists()
    assert not (target_dir / "b.txt").exists()
    assert result2.linked == 1


def test_undeploy_removes_links_but_keeps_target_directory(tmp_path):
    mods_dir = tmp_path / "mods"
    target_dir = tmp_path / "game" / "Data"
    state_dir = tmp_path / "state"
    _make_mod_file(mods_dir, "mod-a", "nested/file.txt", "a")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    plan = deploy.build_plan(mods_dir, [mod_a])
    deploy.apply_plan(plan, target_dir, state_dir)

    removed = deploy.undeploy_all(target_dir, state_dir)

    assert removed == 1
    assert target_dir.is_dir(), "the game's real deploy directory must never be deleted"
    assert list(target_dir.iterdir()) == []


def test_undeploy_never_touches_files_it_did_not_create(tmp_path):
    """Regression guard: undeploy must not delete a real game file that
    happens to share a path with something LMM once deployed there but no
    longer manages (e.g. the user replaced the symlink with a real file)."""
    mods_dir = tmp_path / "mods"
    target_dir = tmp_path / "game" / "Data"
    state_dir = tmp_path / "state"
    _make_mod_file(mods_dir, "mod-a", "file.txt", "a")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    plan = deploy.build_plan(mods_dir, [mod_a])
    deploy.apply_plan(plan, target_dir, state_dir)

    # User (or the game) replaces the symlink with a real file.
    dest = target_dir / "file.txt"
    dest.unlink()
    dest.write_text("real game file, not ours anymore")

    deploy.undeploy_all(target_dir, state_dir)

    assert dest.exists()
    assert dest.read_text() == "real game file, not ours anymore"


# -- case merging -----------------------------------------------------


def test_case_differing_folders_merge_into_one(tmp_path):
    """Windows-packaged mods disagree about capitalisation; on Linux those
    must still land in a single folder or the game only finds one."""
    mods_dir = tmp_path / "mods"
    _make_mod_file(mods_dir, "mod-a", "Meshes/thing.nif", "from A")
    _make_mod_file(mods_dir, "mod-b", "meshes/other.nif", "from B")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    mod_b = InstalledMod(id="mod-b", name="B", game_id="g", staging_subdir="mod-b", priority=1)

    plan = deploy.build_plan(mods_dir, [mod_a, mod_b])

    parents = {Path(key).parts[0] for key in plan.links}
    assert parents == {"Meshes"}  # first spelling seen wins, both merged


def test_case_differing_same_file_is_a_conflict(tmp_path):
    mods_dir = tmp_path / "mods"
    _make_mod_file(mods_dir, "mod-a", "Textures/Thing.DDS", "from A")
    _make_mod_file(mods_dir, "mod-b", "textures/thing.dds", "from B")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    mod_b = InstalledMod(id="mod-b", name="B", game_id="g", staging_subdir="mod-b", priority=1)

    plan = deploy.build_plan(mods_dir, [mod_a, mod_b])

    assert len(plan.links) == 1
    assert list(plan.conflicts.values()) == [["mod-a", "mod-b"]]
    # Later mod still wins, exactly as it would have on Windows.
    assert list(plan.links.values())[0] == mods_dir / "mod-b" / "textures/thing.dds"


def test_seeding_from_target_adopts_the_games_capitalisation(tmp_path):
    mods_dir = tmp_path / "mods"
    target_dir = tmp_path / "game" / "Data"
    (target_dir / "Textures").mkdir(parents=True)  # the game's own spelling
    _make_mod_file(mods_dir, "mod-a", "textures/thing.dds", "from A")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    plan = deploy.build_plan(mods_dir, [mod_a], target_dir=target_dir)

    assert list(plan.links) == ["Textures/thing.dds"]


def test_fomod_metadata_is_not_deployed(tmp_path):
    mods_dir = tmp_path / "mods"
    _make_mod_file(mods_dir, "mod-a", "fomod/ModuleConfig.xml", "<config/>")
    _make_mod_file(mods_dir, "mod-a", "Textures/thing.dds", "real content")

    mod_a = InstalledMod(id="mod-a", name="A", game_id="g", staging_subdir="mod-a", priority=0)
    plan = deploy.build_plan(mods_dir, [mod_a])

    assert list(plan.links) == ["Textures/thing.dds"]
