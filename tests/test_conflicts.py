from lmm.mods import conflicts


def test_empty_conflicts_report():
    report = conflicts.build_report({})
    assert report.total_paths == 0
    assert report.pairs == []
    assert "No file conflicts" in conflicts.render_summary(report, {})


def test_pairs_are_grouped_and_counted():
    """The useful unit is "which mod overrides which, how often" - not a
    flat list of thousands of paths."""
    report = conflicts.build_report(
        {
            "Data/a.dds": ["base", "patch"],
            "Data/b.dds": ["base", "patch"],
            "Data/c.dds": ["base", "other"],
        }
    )

    assert report.total_paths == 3
    assert [(p.loser_id, p.winner_id, p.count) for p in report.pairs] == [
        ("base", "patch", 2),
        ("base", "other", 1),
    ]
    assert report.mod_count == 3


def test_last_provider_is_the_winner_for_every_loser():
    report = conflicts.build_report({"Data/x.dds": ["a", "b", "c"]})

    assert [(p.loser_id, p.winner_id) for p in report.pairs] == [("a", "c"), ("b", "c")]


def test_summary_uses_display_names_and_truncates():
    raw = {f"Data/f{i}.dds": [f"loser{i}", "winner"] for i in range(50)}
    report = conflicts.build_report(raw)
    names = {f"loser{i}": f"Loser Mod {i}" for i in range(50)}
    names["winner"] = "Winning Mod"

    summary = conflicts.render_summary(report, names, limit=5)

    assert "Winning Mod" in summary
    assert "Loser Mod 0" in summary
    assert "and 45 more mod pair(s)" in summary


def test_log_contains_every_file_and_the_full_chain():
    report = conflicts.build_report(
        {"Data/a.dds": ["base", "patch"], "Data/b.dds": ["base", "mid", "patch"]}
    )
    names = {"base": "Base Mod", "mid": "Middle Mod", "patch": "Patch Mod"}

    log = conflicts.render_log(report, names, game_name="Fallout 4")

    assert "Fallout 4" in log
    assert "Data/a.dds" in log and "Data/b.dds" in log
    assert "Base Mod -> Middle Mod -> Patch Mod" in log
    assert "winner: Patch Mod" in log


def test_write_log_overwrites_rather_than_accumulating(tmp_path):
    first = conflicts.build_report({"Data/a.dds": ["x", "y"]})
    path = conflicts.write_log(tmp_path, first, {})
    second = conflicts.build_report({"Data/b.dds": ["x", "y"]})
    again = conflicts.write_log(tmp_path, second, {})

    assert path == again
    assert list(tmp_path.glob("*.log")) == [path]
    assert "Data/b.dds" in path.read_text()
    assert "Data/a.dds" not in path.read_text()


def test_a_path_with_one_provider_is_not_a_conflict():
    report = conflicts.build_report({"Data/solo.dds": ["only"]})
    assert report.pairs == []
