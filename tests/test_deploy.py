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
