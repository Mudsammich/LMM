"""Heuristic conflict-aware reordering.

This does **not** guarantee a conflict-free load order - reordering only
picks which mod *wins* a file conflict, and picking the "correct" winner
in general requires understanding what each mod actually does, which
nothing here has. What it does instead is apply two signals that are
real, documented modding conventions (not guesses invented for this
project) to the conflicts LMM can already detect:

- **Naming convention**: a mod whose name suggests it's a patch, fix, or
  compatibility mod is conventionally meant to load after (and override)
  whatever it patches - that is the entire point of such a mod. See e.g.
  https://en.uesp.net/wiki/Oblivion_Mod:A_General_Order_for_Installing_Mods
  ("foundations first, features second, patches last").
- **Specificity by file count**: failing a naming signal, the mod that
  deploys *fewer* files is treated as the more targeted one (a single
  texture swap vs. the overhaul it's swapping textures for) and placed
  after the mod it conflicts with - the same "specific overrides general"
  convention. This mirrors how Vortex/LOOT treat explicit ordering rules
  as a dependency graph: conflicting pairs become directed edges ("loser
  loads before winner"), resolved with a topological sort. A pair with no
  signal either way is left exactly where it already was - no edge, no
  forced decision. An edge that would create a cycle (A must load before
  B, and B before A, transitively) is dropped rather than forced, the
  same "soft rule" behaviour LOOT's plugin groups use.

Disabled mods are left untouched in their exact slot; only the enabled
mods that actually participate in a conflict can move, and only ever
relative to one another.
"""
from __future__ import annotations

import heapq
import itertools
from collections import defaultdict
from dataclasses import dataclass

from ..models import InstalledMod

_PATCH_KEYWORDS = ("patch", "fix", "compat", "addon", "tweak", "override")


def _looks_like_patch(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in _PATCH_KEYWORDS)


@dataclass(frozen=True)
class OrderingHint:
    """One conflicting pair where a signal picked a winner and that
    actually changed something relative to the mod list's prior order."""

    loser_id: str
    winner_id: str
    reason: str


@dataclass
class SortSuggestion:
    """``new_order`` is the full proposed mod id list (same ids as given,
    just reordered) - pass it straight to ``ModManager.reorder()`` to
    apply it. ``hints`` explains only the constraints that actually moved
    something, for a confirmation UI to show before applying."""

    new_order: list[str]
    hints: list[OrderingHint]
    changed: bool


def suggest_order(
    all_mods: list[InstalledMod],
    conflicts: dict[str, list[str]],
    file_counts: dict[str, int],
) -> SortSuggestion:
    """``all_mods`` must already be sorted by current priority (ascending).
    ``conflicts`` is ``deploy.DeployPlan.conflicts`` (relative path -> mod
    ids providing it, in current priority order) for the enabled subset of
    ``all_mods``. ``file_counts`` maps mod id -> number of files it
    deploys, for every enabled mod."""
    name_by_id = {m.id: m.name for m in all_mods}
    original_ids = [m.id for m in all_mods]

    enabled_positions = [i for i, m in enumerate(all_mods) if m.enabled]
    enabled_order = [all_mods[i].id for i in enabled_positions]
    index_of = {mod_id: i for i, mod_id in enumerate(enabled_order)}

    candidates = _score_conflicts(conflicts, name_by_id, file_counts, index_of)
    new_enabled_order, hints = _stable_topo_sort(enabled_order, candidates)

    new_full_order = list(original_ids)
    for pos, mod_id in zip(enabled_positions, new_enabled_order):
        new_full_order[pos] = mod_id

    return SortSuggestion(
        new_order=new_full_order,
        hints=hints,
        changed=new_full_order != original_ids,
    )


def _compare(a: str, b: str, name_by_id: dict[str, str], file_counts: dict[str, int]):
    """Returns (strength, loser, winner, reason), or None if neither
    signal distinguishes the pair (leave their relative order alone)."""
    a_patch = _looks_like_patch(name_by_id.get(a, ""))
    b_patch = _looks_like_patch(name_by_id.get(b, ""))
    if a_patch != b_patch:
        loser, winner = (b, a) if a_patch else (a, b)
        return (
            0,  # naming is the stronger signal - applied first
            loser,
            winner,
            f"{name_by_id.get(winner, winner)!r} looks like a patch/fix/compat mod for "
            f"{name_by_id.get(loser, loser)!r}, so it should load after it",
        )

    fa, fb = file_counts.get(a, 0), file_counts.get(b, 0)
    if fa == fb:
        return None
    loser, winner = (b, a) if fa < fb else (a, b)
    return (
        1,
        loser,
        winner,
        f"{name_by_id.get(winner, winner)!r} deploys fewer files than "
        f"{name_by_id.get(loser, loser)!r} - treating it as the more specific override",
    )


def _score_conflicts(
    conflicts: dict[str, list[str]],
    name_by_id: dict[str, str],
    file_counts: dict[str, int],
    index_of: dict[str, int],
) -> list[tuple[int, str, str, str]]:
    """One candidate edge per conflicting pair (deduped across the
    possibly many files two mods both conflict on), sorted strongest
    signal first, then deterministically by original position."""
    seen: dict[tuple[str, str], tuple[int, str, str, str]] = {}
    for providers in conflicts.values():
        enabled_providers = [p for p in providers if p in index_of]
        for a, b in itertools.combinations(enabled_providers, 2):
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            verdict = _compare(a, b, name_by_id, file_counts)
            if verdict is not None:
                seen[key] = verdict
    return sorted(
        seen.values(),
        key=lambda edge: (edge[0], index_of[edge[1]], index_of[edge[2]]),
    )


def _reachable(adjacency: dict[str, list[str]], start: str, target: str) -> bool:
    stack = [start]
    visited: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency.get(node, ()))
    return False


def _stable_topo_sort(
    node_order: list[str], candidates: list[tuple[int, str, str, str]]
) -> tuple[list[str], list[OrderingHint]]:
    """Kahn's algorithm, tie-broken by original position so any node with
    no remaining constraint keeps its relative place. Candidate edges that
    would introduce a cycle are dropped rather than forced (a "soft
    rule" - see module docstring)."""
    index_of = {node_id: i for i, node_id in enumerate(node_order)}
    id_by_index = {i: node_id for node_id, i in index_of.items()}
    adjacency: dict[str, list[str]] = defaultdict(list)
    hints: list[OrderingHint] = []

    for _strength, loser, winner, reason in candidates:
        if _reachable(adjacency, winner, loser):
            continue  # would create a cycle - skip this rule
        adjacency[loser].append(winner)
        if index_of[loser] > index_of[winner]:
            # Original order already violated this constraint - this is
            # an actual move, worth explaining to the user.
            hints.append(OrderingHint(loser, winner, reason))

    indegree = {n: 0 for n in node_order}
    for winners in adjacency.values():
        for w in winners:
            indegree[w] += 1

    heap = [index_of[n] for n in node_order if indegree[n] == 0]
    heapq.heapify(heap)
    result: list[str] = []
    while heap:
        i = heapq.heappop(heap)
        node = id_by_index[i]
        result.append(node)
        for nxt in adjacency[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, index_of[nxt])

    return result, hints
