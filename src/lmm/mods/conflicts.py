"""Turning a deploy plan's raw conflict map into something a human can act
on.

A big modlist produces thousands of conflicting files, and a flat list of
every path is useless at that size - the question isn't "which files
collide" but "which *mods* are overriding which, and by how much". That's
the view that tells you whether an override is intentional (a patch beating
the mod it patches) or an accident (a texture pack quietly eating half of
another one).

So the summary is per mod pair, ordered by how many files each pair
disagrees on, and the exhaustive per-file listing goes to a log file where
it can be searched rather than scrolled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ConflictPair:
    """``winner_id`` overrides ``loser_id`` on ``paths``."""

    loser_id: str
    winner_id: str
    paths: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.paths)


@dataclass
class ConflictReport:
    total_paths: int = 0
    pairs: list[ConflictPair] = field(default_factory=list)
    by_path: dict[str, list[str]] = field(default_factory=dict)
    # mod id -> {folded path: [the differing real paths]} - an archive at
    # odds with itself, rather than with another mod.
    internal_case_collisions: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @property
    def mod_count(self) -> int:
        involved = {p.loser_id for p in self.pairs} | {p.winner_id for p in self.pairs}
        return len(involved)


def build_report(
    conflicts: dict[str, list[str]],
    internal_case_collisions: dict[str, dict[str, list[str]]] | None = None,
) -> ConflictReport:
    """``conflicts`` is a ``deploy.DeployPlan.conflicts`` map: path -> the
    mod ids providing it, in ascending priority order (so the last one is
    the winner)."""
    pairs: dict[tuple[str, str], ConflictPair] = {}
    inter_mod: dict[str, list[str]] = {}
    for path, providers in conflicts.items():
        # One mod can appear twice for a path when its own archive holds two
        # case-variants of it. That's a flaw in the archive, reported
        # separately - it isn't a conflict *between* mods and shouldn't
        # inflate the count of them.
        distinct = list(dict.fromkeys(providers))
        if len(distinct) < 2:
            continue
        inter_mod[path] = distinct
        winner = distinct[-1]
        for loser in distinct[:-1]:
            key = (loser, winner)
            pair = pairs.get(key)
            if pair is None:
                pair = pairs[key] = ConflictPair(loser_id=loser, winner_id=winner)
            pair.paths.append(path)

    ordered = sorted(pairs.values(), key=lambda p: (-p.count, p.loser_id, p.winner_id))
    for pair in ordered:
        pair.paths.sort()
    return ConflictReport(
        total_paths=len(inter_mod),
        pairs=ordered,
        by_path=dict(sorted(inter_mod.items())),
        internal_case_collisions=internal_case_collisions or {},
    )


def _render_internal_collisions(report: ConflictReport, names: dict[str, str]) -> list[str]:
    if not report.internal_case_collisions:
        return []

    def name_of(mod_id: str) -> str:
        return names.get(mod_id, mod_id)

    total = sum(len(paths) for paths in report.internal_case_collisions.values())
    lines = [
        "",
        f"WARNING - {total} path(s) in {len(report.internal_case_collisions)} mod(s) exist "
        "twice in the same archive under different capitalisation.",
        "On Windows one would simply have overwritten the other, so only one was ever",
        "meant to exist. LMM deploys one of them and can't know which the author meant -",
        "if that mod misbehaves, this is why.",
        "",
    ]
    for mod_id, collisions in sorted(report.internal_case_collisions.items()):
        lines.append(f"  {name_of(mod_id)}:")
        for paths in sorted(collisions.values()):
            lines.append(f"    {'  vs  '.join(paths)}")
    return lines


def render_summary(report: ConflictReport, names: dict[str, str], limit: int = 40) -> str:
    """The at-a-glance view, for on-screen display."""
    if not report.total_paths:
        no_conflicts = "No file conflicts among enabled mods."
        internal = _render_internal_collisions(report, names)
        return "\n".join([no_conflicts, *internal]) if internal else no_conflicts

    def name_of(mod_id: str) -> str:
        return names.get(mod_id, mod_id)

    lines = [
        f"{report.total_paths} file(s) are provided by more than one mod, "
        f"across {report.mod_count} mod(s).",
        "",
        "The mod listed second wins - it deploys later. That's correct when "
        "it's a patch for the first, and a problem when it isn't.",
        "",
    ]
    for pair in report.pairs[:limit]:
        lines.append(
            f"{pair.count:>6}  {name_of(pair.loser_id)}  ->  overridden by  {name_of(pair.winner_id)}"
        )
    if len(report.pairs) > limit:
        lines.append(f"        … and {len(report.pairs) - limit} more mod pair(s) - see the log file.")
    lines += _render_internal_collisions(report, names)
    return "\n".join(lines)


def render_log(report: ConflictReport, names: dict[str, str], game_name: str = "") -> str:
    """The exhaustive view, for the log file: every pair, then every file
    with the full provider chain."""
    def name_of(mod_id: str) -> str:
        return names.get(mod_id, mod_id)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = [
        f"LMM conflict report{f' - {game_name}' if game_name else ''}",
        f"Generated {stamp}",
        "",
        f"{report.total_paths} conflicting file(s) across {report.mod_count} mod(s), "
        f"in {len(report.pairs)} mod pair(s).",
        "",
        "=" * 72,
        "SUMMARY BY MOD PAIR (winner deploys later and overrides the loser)",
        "=" * 72,
        "",
    ]
    for pair in report.pairs:
        out.append(
            f"{pair.count:>6} file(s)  {name_of(pair.loser_id)}  ->  overridden by  {name_of(pair.winner_id)}"
        )

    if report.internal_case_collisions:
        out += ["", "=" * 72, "ARCHIVES CONTAINING THE SAME PATH TWICE (CASE ONLY)", "=" * 72]
        out += _render_internal_collisions(report, names)

    out += ["", "=" * 72, "EVERY CONFLICTING FILE", "=" * 72, ""]
    for path, providers in report.by_path.items():
        chain = " -> ".join(name_of(p) for p in providers)
        out.append(path)
        out.append(f"    {chain}")
        out.append(f"    winner: {name_of(providers[-1])}")
        out.append("")
    return "\n".join(out)


def write_log(
    directory: str | Path,
    report: ConflictReport,
    names: dict[str, str],
    game_name: str = "",
) -> Path:
    """Writes the full report and returns its path. Overwrites the previous
    one rather than accumulating files - it's a snapshot of the current mod
    list, and a stale one is only confusing."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "conflicts.log"
    path.write_text(render_log(report, names, game_name), encoding="utf-8")
    return path
