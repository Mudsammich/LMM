"""Evaluating a parsed FOMOD: which options are selectable, which steps
are visible, and which files a finished set of choices actually installs.

Kept separate from ``fomod.py`` (which only turns XML into dataclasses) so
the decision logic is testable without any XML or GUI involved - the
wizard in ``gui/fomod_dialog.py`` is a thin shell over this.

The core idea is *flags*. Selecting an option can set named flags; later
steps and options can then ask about those flags to decide whether they're
visible, required, or forbidden. That's how a FOMOD asks "which body
type?" on page one and then only offers the matching armour options on
page two. Flags accumulate in step order, and a later step re-setting the
same flag overwrites it, so evaluation always runs over the choices made
*up to* the step being displayed.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .fomod import (
    ConditionalInstall,
    DependencyGroup,
    FileEntry,
    FomodConfig,
    Group,
    GroupType,
    InstallStep,
    Plugin,
    PluginType,
)

# A selection is (step index, group index, plugin index) -> chosen or not.
# Keyed positionally rather than by name because names repeat: plenty of
# installers have several groups each offering a plugin called "Yes".
SelectionKey = tuple[int, int, int]


@dataclass
class InstallState:
    """The choices made so far, plus the flags they imply."""

    selected: set[SelectionKey] = field(default_factory=set)

    def is_selected(self, key: SelectionKey) -> bool:
        return key in self.selected

    def select(self, key: SelectionKey, chosen: bool = True) -> None:
        if chosen:
            self.selected.add(key)
        else:
            self.selected.discard(key)

    def clear_group(self, step_index: int, group_index: int) -> None:
        """Drops every selection in one group - used when an exclusive
        group's choice moves, and when a step stops being visible."""
        self.selected = {
            key for key in self.selected if not (key[0] == step_index and key[1] == group_index)
        }

    def clear_step(self, step_index: int) -> None:
        self.selected = {key for key in self.selected if key[0] != step_index}


def flags_for(config: FomodConfig, state: InstallState, up_to_step: int | None = None) -> dict[str, str]:
    """The flag state implied by ``state``. ``up_to_step`` limits it to
    steps strictly before that index, which is what conditions on a step
    being *displayed* must be evaluated against - a step can't depend on
    choices the user hasn't reached yet."""
    flags: dict[str, str] = {}
    for step_index, step in enumerate(config.install_steps):
        if up_to_step is not None and step_index >= up_to_step:
            break
        for group_index, group in enumerate(step.groups):
            for plugin_index, plugin in enumerate(group.plugins):
                if not state.is_selected((step_index, group_index, plugin_index)):
                    continue
                for flag in plugin.condition_flags:
                    flags[flag.flag] = flag.value
    return flags


def evaluate(
    dependencies: DependencyGroup,
    flags: dict[str, str],
    installed_files: set[str] | None = None,
) -> bool:
    """Evaluates a dependency tree against the current flags.

    An empty condition is True - "no conditions" means "always applies",
    which is what an absent ``<visible>`` element implies.

    ``installed_files`` supports ``fileDependency``: the set of plugin
    filenames (lowercased) already present in the game. When it's not
    provided we can't answer those questions, so they're treated as
    satisfied - an installer shouldn't hide options from the user just
    because LMM lacks the information to check a precondition.
    """
    if dependencies.is_empty():
        return True

    results: list[bool] = []

    for flag in dependencies.flags:
        # An absent flag reads as empty string, so `value=""` correctly
        # matches "this flag was never set".
        results.append(flags.get(flag.flag, "") == flag.value)

    for file_dep in dependencies.files:
        if installed_files is None:
            results.append(True)
            continue
        present = _matches_installed(file_dep.file, installed_files)
        wanted = file_dep.state.strip().lower()
        if wanted == "missing":
            results.append(not present)
        else:  # "Active" / "Inactive" - both mean "the file is there"
            results.append(present)

    for child in dependencies.children:
        results.append(evaluate(child, flags, installed_files))

    if not results:
        return True
    return any(results) if dependencies.operator == "Or" else all(results)


def _matches_installed(pattern: str, installed_files: set[str]) -> bool:
    """FOMOD file dependencies are usually plain filenames, but wildcards
    do turn up."""
    needle = pattern.strip().lower().replace("\\", "/")
    if needle in installed_files:
        return True
    if "*" in needle or "?" in needle:
        return any(fnmatch.fnmatch(name, needle) for name in installed_files)
    return False


def plugin_type(
    plugin: Plugin,
    flags: dict[str, str],
    installed_files: set[str] | None = None,
) -> PluginType:
    """An option's effective type: either fixed, or the first matching
    pattern's type when it's computed from earlier choices."""
    for pattern in plugin.type_patterns:
        if evaluate(pattern.dependencies, flags, installed_files):
            return pattern.type
    return plugin.default_type


def visible_steps(
    config: FomodConfig,
    state: InstallState,
    installed_files: set[str] | None = None,
) -> list[int]:
    """Indices of the steps that should be shown, given current choices."""
    shown: list[int] = []
    for index, step in enumerate(config.install_steps):
        flags = flags_for(config, state, up_to_step=index)
        if evaluate(step.visible, flags, installed_files):
            shown.append(index)
    return shown


def apply_defaults(
    config: FomodConfig,
    state: InstallState,
    step_index: int,
    installed_files: set[str] | None = None,
) -> None:
    """Pre-selects a step's options the way the installer intends, so the
    user can click straight through a wizard and get the author's
    recommended setup.

    Required options are always selected; Recommended ones are selected as
    a default the user can change. An exclusive group with nothing
    recommended falls back to its first selectable option, because
    ``SelectExactlyOne`` can't be left empty.
    """
    step = config.install_steps[step_index]

    for group_index, group in enumerate(step.groups):
        # Recomputed per group: an option's type can depend on flags set by
        # an *earlier group in this same step*, so each group has to see the
        # defaults already applied above it.
        flags = flags_for(config, state, up_to_step=step_index + 1)
        types = [plugin_type(p, flags, installed_files) for p in group.plugins]

        for plugin_index, ptype in enumerate(types):
            key = (step_index, group_index, plugin_index)
            if ptype == PluginType.REQUIRED:
                state.select(key, True)
            elif ptype == PluginType.NOT_USABLE:
                state.select(key, False)

        if group.type == GroupType.SELECT_ALL:
            for plugin_index, ptype in enumerate(types):
                if ptype != PluginType.NOT_USABLE:
                    state.select((step_index, group_index, plugin_index), True)
            continue

        already = [
            i for i in range(len(group.plugins)) if state.is_selected((step_index, group_index, i))
        ]
        if group.type.is_exclusive:
            if len(already) > 1:
                # Keep only the first - an exclusive group can't hold two.
                for extra in already[1:]:
                    state.select((step_index, group_index, extra), False)
                already = already[:1]
            if already:
                continue

        if already:
            continue

        preferred = _first_index(types, PluginType.RECOMMENDED)
        if preferred is None and group.type.requires_selection:
            preferred = _first_selectable(types)
        if preferred is not None:
            state.select((step_index, group_index, preferred), True)


def default_state(
    config: FomodConfig,
    installed_files: set[str] | None = None,
) -> InstallState:
    """The setup the installer's author recommends, with no user input.

    This is what a bulk install (a whole Collection) uses: prompting for
    hundreds of archives isn't an option, and the author's own
    Required/Recommended defaults are a far better answer than dumping the
    installer's scaffolding into the game. Steps are walked in order
    because a later step's visibility depends on earlier choices.
    """
    state = InstallState()
    for index, step in enumerate(config.install_steps):
        if not evaluate(step.visible, flags_for(config, state, up_to_step=index), installed_files):
            continue
        apply_defaults(config, state, index, installed_files)
    return state


def _first_index(types: list[PluginType], wanted: PluginType) -> int | None:
    for index, ptype in enumerate(types):
        if ptype == wanted:
            return index
    return None


def _first_selectable(types: list[PluginType]) -> int | None:
    for index, ptype in enumerate(types):
        if ptype != PluginType.NOT_USABLE:
            return index
    return None


def group_error(
    group: Group,
    step_index: int,
    group_index: int,
    state: InstallState,
) -> str | None:
    """A human-readable reason this group's selection isn't valid yet, or
    None. Drives whether the wizard's Next button is enabled."""
    count = sum(
        1 for i in range(len(group.plugins)) if state.is_selected((step_index, group_index, i))
    )
    if group.type == GroupType.SELECT_EXACTLY_ONE and count != 1:
        return f"{group.name}: choose exactly one option."
    if group.type == GroupType.SELECT_AT_LEAST_ONE and count < 1:
        return f"{group.name}: choose at least one option."
    if group.type == GroupType.SELECT_AT_MOST_ONE and count > 1:
        return f"{group.name}: choose at most one option."
    return None


# -- resolving the final file list -----------------------------------------------------


@dataclass
class ResolvedFile:
    """One concrete copy instruction: ``source`` relative to the extracted
    archive root, ``destination`` relative to the mod's staging root."""

    source: str
    destination: str
    priority: int


def resolve_files(
    config: FomodConfig,
    state: InstallState,
    installed_files: set[str] | None = None,
) -> list[ResolvedFile]:
    """The full set of files a finished wizard installs: always-installed
    files, plus every selected option's files, plus whatever
    ``conditionalFileInstalls`` matches the final flag state.

    Only *visible* steps contribute - a step hidden by its condition
    shouldn't install anything even if it holds stale selections from
    before the user changed an earlier answer.
    """
    entries: list[FileEntry] = list(config.required_files)

    shown = set(visible_steps(config, state, installed_files))
    final_flags = flags_for(config, state)

    for step_index, step in enumerate(config.install_steps):
        if step_index not in shown:
            continue
        for group_index, group in enumerate(step.groups):
            for plugin_index, plugin in enumerate(group.plugins):
                selected = state.is_selected((step_index, group_index, plugin_index))
                # Judged against the final flag state, matching what the
                # user actually saw in the wizard - an option's type can
                # depend on choices made in its own step.
                ptype = plugin_type(plugin, final_flags, installed_files)
                for entry in plugin.files:
                    # alwaysInstall / installIfUsable let an author attach
                    # files to an option that ship regardless of whether
                    # the user picked it, as long as it wasn't ruled out.
                    if selected:
                        entries.append(entry)
                    elif entry.always_install:
                        entries.append(entry)
                    elif entry.install_if_usable and ptype != PluginType.NOT_USABLE:
                        entries.append(entry)

    for conditional in config.conditional_installs:
        if evaluate(conditional.dependencies, final_flags, installed_files):
            entries.extend(conditional.files)

    return _flatten_entries(entries)


def _flatten_entries(entries: list[FileEntry]) -> list[ResolvedFile]:
    """Normalises paths and returns the entries in *install order*.

    Note entries are not deduplicated by destination: several sources
    routinely install into the same destination and are meant to merge
    there (a base ``00 Core`` folder plus an option's overrides, both
    landing at the payload root). ``priority`` decides who wins where two
    of them provide the same file, which is handled by copy order - low
    priority first, so higher priority overwrites. The sort is stable, so
    equal priorities keep the order the installer declared them in.

    Exact duplicates *are* dropped, since an ``alwaysInstall`` entry on a
    selected option would otherwise be copied twice.
    """
    seen: set[tuple[str, str, bool]] = set()
    resolved: list[ResolvedFile] = []
    for entry in entries:
        source = entry.source.replace("\\", "/").strip("/")
        destination = entry.destination.replace("\\", "/").strip("/")
        key = (source.lower(), destination.lower(), entry.is_folder)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(ResolvedFile(source=source, destination=destination, priority=entry.priority))
    resolved.sort(key=lambda r: r.priority)
    return resolved


def stage_resolved_files(
    extracted_root: str | Path,
    resolved: list[ResolvedFile],
    dest_root: str | Path,
) -> int:
    """Copies the resolved selection out of the extracted archive into
    ``dest_root``, which becomes the mod's staging directory.

    ``resolved`` is copied in the order given - which is the install order
    ``resolve_files`` returns, so higher-priority sources land last and win
    any file they share with an earlier one.

    Sources are matched case-insensitively, since ModuleConfig.xml is
    written against a case-insensitive filesystem and frequently disagrees
    with the archive's real capitalisation - on Linux that's the difference
    between a working install and an empty one. Returns the number of files
    copied.
    """
    import shutil

    extracted_root = Path(extracted_root)
    dest_root = Path(dest_root)
    copied = 0

    for entry in resolved:
        source = _resolve_case_insensitive(extracted_root, entry.source)
        if source is None:
            continue  # a source the archive doesn't actually contain - skip quietly
        destination = dest_root / entry.destination if entry.destination else dest_root

        if source.is_dir():
            for item in sorted(source.rglob("*")):
                if not item.is_file():
                    continue
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied += 1
        elif source.is_file():
            # A file entry's destination may name the folder to land in
            # rather than the new filename; treat a trailing-slash or
            # existing-directory destination that way.
            if entry.destination.endswith("/") or destination.is_dir():
                destination = destination / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1

    return copied


def _resolve_case_insensitive(root: Path, relative: str) -> Path | None:
    """Walks ``relative`` one component at a time, accepting a
    case-insensitive match at each level."""
    if not relative:
        return root
    current = root
    for part in Path(relative).parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            entries = list(current.iterdir())
        except OSError:
            return None
        folded = part.lower()
        match = next((e for e in entries if e.name.lower() == folded), None)
        if match is None:
            return None
        current = match
    return current
