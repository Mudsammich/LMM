from lmm.models import InstalledMod
from lmm.mods import sorter


def _mod(mod_id, name, priority, enabled=True):
    return InstalledMod(
        id=mod_id,
        name=name,
        game_id="g",
        staging_subdir=mod_id,
        enabled=enabled,
        priority=priority,
    )


def test_no_signal_leaves_order_unchanged():
    mods = [_mod("a", "Alpha Overhaul", 0), _mod("b", "Beta Overhaul", 1)]
    conflicts = {"file.esp": ["a", "b"]}
    file_counts = {"a": 50, "b": 50}  # identical - no specificity signal
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    assert not suggestion.changed
    assert suggestion.new_order == ["a", "b"]
    assert suggestion.hints == []


def test_patch_keyword_wins_even_if_installed_first():
    # "Compat Patch" was installed (and so currently loads) *before* the
    # mod it patches - the naming signal should move it after.
    mods = [_mod("patch", "Big Mod Compat Patch", 0), _mod("big", "Big Mod", 1)]
    conflicts = {"file.esp": ["patch", "big"]}
    file_counts = {"patch": 5, "big": 500}
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    assert suggestion.changed
    assert suggestion.new_order == ["big", "patch"]
    assert len(suggestion.hints) == 1
    assert suggestion.hints[0].winner_id == "patch"
    assert suggestion.hints[0].loser_id == "big"


def test_fewer_files_wins_as_specificity_tiebreak():
    # "small" (fewer files) currently loads *before* "big" - wrong per the
    # heuristic, since the mod with fewer files is treated as the more
    # specific one and should win the conflict.
    mods = [_mod("small", "Specific Texture Swap", 0), _mod("big", "Texture Overhaul", 1)]
    conflicts = {"textures/thing.dds": ["small", "big"]}
    file_counts = {"big": 200, "small": 3}
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    assert suggestion.changed
    # "small" must end up after "big" regardless of starting position.
    assert suggestion.new_order.index("small") > suggestion.new_order.index("big")


def test_already_correct_order_produces_no_hint():
    mods = [_mod("big", "Texture Overhaul", 0), _mod("small", "Specific Texture Swap", 1)]
    conflicts = {"textures/thing.dds": ["big", "small"]}
    file_counts = {"big": 200, "small": 3}
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    # small already loads after big - nothing to fix.
    assert not suggestion.changed
    assert suggestion.hints == []


def test_disabled_mods_keep_their_exact_slot():
    mods = [
        _mod("patch", "Fix Patch", 0),
        _mod("disabled", "Disabled Mod", 1, enabled=False),
        _mod("target", "Target Mod", 2),
    ]
    conflicts = {"file.esp": ["patch", "target"]}
    file_counts = {"patch": 1, "target": 100}
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    assert suggestion.new_order[1] == "disabled"  # untouched slot
    assert suggestion.new_order.index("target") < suggestion.new_order.index("patch")


def test_cyclic_signals_are_dropped_not_forced():
    # Contrived: three mods where pairwise file-count comparisons would
    # form a cycle (a<b<c<a) if every edge were forced. The algorithm must
    # still return a full, valid permutation rather than raising or
    # dropping a mod.
    mods = [_mod("a", "Mod A", 0), _mod("b", "Mod B", 1), _mod("c", "Mod C", 2)]
    conflicts = {
        "f1": ["a", "b"],
        "f2": ["b", "c"],
        "f3": ["c", "a"],
    }
    # a beats b (fewer files), b beats c, c beats a: cyclic constraints.
    file_counts = {"a": 1, "b": 2, "c": 3}
    suggestion = sorter.suggest_order(mods, conflicts, file_counts)

    assert sorted(suggestion.new_order) == ["a", "b", "c"]


def test_no_conflicts_means_no_change():
    mods = [_mod("a", "Alpha", 0), _mod("b", "Beta", 1)]
    suggestion = sorter.suggest_order(mods, {}, {"a": 10, "b": 10})

    assert not suggestion.changed
    assert suggestion.new_order == ["a", "b"]
