"""FOMOD installer support: parsing ``fomod/ModuleConfig.xml``.

A FOMOD is the "choose your options" wizard you see on a lot of Nexus mod
pages. The archive holds a ``fomod/`` folder with ``info.xml`` (cosmetic
metadata) and ``ModuleConfig.xml`` (the actual installer script), plus
payload folders the script picks from. Without an installer, extracting
one dumps its scaffolding straight into the game - which is why an
unhandled FOMOD shows up as ``00 Core``, ``01 - ESP``, ``Optional`` and
friends sitting in the Data folder.

The format is XML with a published schema (``ModConfig5.0.xsd``), but
real-world files are frequently loose about it - optional elements
missing, attributes omitted and left to default, occasional stray
namespaces. So this parser is deliberately lenient: unknown elements are
ignored, missing attributes fall back to the documented defaults, and
anything unparseable raises ``FomodError`` so the caller can fall back to
installing the archive as-is rather than failing the install outright.

Structure, as parsed here::

    config
      moduleName
      requiredInstallFiles      always installed, no choice involved
      installSteps              one wizard page each
        installStep
          visible               optional condition gating the whole page
          optionalFileGroups
            group               type= sets selection cardinality
              plugins
                plugin          one selectable option
                  description
                  files         what installing it copies
                  conditionFlags flags it sets when selected
                  typeDescriptor static type, or one computed from flags
      conditionalFileInstalls   extra files chosen by the final flag state

Deliberately unsupported: ``gameDependency``/``fommDependency`` version
checks (there's no meaningful version to compare against under Proton, and
every real installer treats them as advisory), and option images (a v1
scope call - descriptions carry the actual decision-making information).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class FomodError(ValueError):
    """Raised when a ModuleConfig.xml can't be understood. Callers should
    treat this as "install this archive normally" rather than as a fatal
    error - a mod with a broken installer script is still a mod."""


class GroupType(str, Enum):
    """How many options a group lets you pick. Names match the XML."""

    SELECT_EXACTLY_ONE = "SelectExactlyOne"
    SELECT_AT_MOST_ONE = "SelectAtMostOne"
    SELECT_AT_LEAST_ONE = "SelectAtLeastOne"
    SELECT_ANY = "SelectAny"
    SELECT_ALL = "SelectAll"

    @property
    def is_exclusive(self) -> bool:
        """True if at most one option can be chosen - radio buttons rather
        than checkboxes."""
        return self in (GroupType.SELECT_EXACTLY_ONE, GroupType.SELECT_AT_MOST_ONE)

    @property
    def requires_selection(self) -> bool:
        return self in (GroupType.SELECT_EXACTLY_ONE, GroupType.SELECT_AT_LEAST_ONE)


class PluginType(str, Enum):
    """An option's recommendation state. ``NotUsable`` options can't be
    selected at all; ``Required`` ones can't be deselected."""

    REQUIRED = "Required"
    OPTIONAL = "Optional"
    RECOMMENDED = "Recommended"
    NOT_USABLE = "NotUsable"
    COULD_BE_USABLE = "CouldBeUsable"


@dataclass
class FileEntry:
    """One ``<file>`` or ``<folder>`` copy instruction. ``destination``
    defaults to ``source`` when the XML omits it, which is the common case
    ("install this folder where it already claims to live")."""

    source: str
    destination: str
    is_folder: bool
    priority: int = 0
    always_install: bool = False
    install_if_usable: bool = False


@dataclass
class FlagDependency:
    flag: str
    value: str


@dataclass
class FileDependency:
    file: str
    state: str  # "Active" | "Inactive" | "Missing"


@dataclass
class DependencyGroup:
    """A ``<dependencies>`` node: child conditions plus the operator that
    combines them. Nests arbitrarily deep."""

    operator: str = "And"  # "And" | "Or"
    flags: list[FlagDependency] = field(default_factory=list)
    files: list[FileDependency] = field(default_factory=list)
    children: list[DependencyGroup] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.flags or self.files or self.children)


@dataclass
class TypePattern:
    dependencies: DependencyGroup
    type: PluginType


@dataclass
class Plugin:
    """One selectable option within a group."""

    name: str
    description: str = ""
    files: list[FileEntry] = field(default_factory=list)
    condition_flags: list[FlagDependency] = field(default_factory=list)
    default_type: PluginType = PluginType.OPTIONAL
    # Non-empty when the option's type is computed from earlier choices
    # rather than fixed - first matching pattern wins.
    type_patterns: list[TypePattern] = field(default_factory=list)


@dataclass
class Group:
    name: str
    type: GroupType = GroupType.SELECT_ANY
    plugins: list[Plugin] = field(default_factory=list)


@dataclass
class InstallStep:
    """One wizard page. ``visible`` gates whether it's shown at all, based
    on flags set by earlier pages."""

    name: str
    groups: list[Group] = field(default_factory=list)
    visible: DependencyGroup = field(default_factory=DependencyGroup)


@dataclass
class ConditionalInstall:
    dependencies: DependencyGroup
    files: list[FileEntry] = field(default_factory=list)


@dataclass
class FomodConfig:
    module_name: str = ""
    required_files: list[FileEntry] = field(default_factory=list)
    install_steps: list[InstallStep] = field(default_factory=list)
    conditional_installs: list[ConditionalInstall] = field(default_factory=list)

    @property
    def has_choices(self) -> bool:
        """False for a FOMOD that's really just a fixed file list - no
        point showing a wizard with nothing to decide."""
        return any(step.groups for step in self.install_steps)


# -- locating -----------------------------------------------------


def find_module_config(staging_dir: str | Path) -> Path | None:
    """Locates ``fomod/ModuleConfig.xml`` under ``staging_dir``, matching
    case-insensitively since archives spell it every possible way
    (``fomod``, ``FOMOD``, ``FoMod``; ``ModuleConfig.xml``,
    ``moduleconfig.xml``)."""
    staging_dir = Path(staging_dir)
    if not staging_dir.is_dir():
        return None
    for child in staging_dir.iterdir():
        if not child.is_dir() or child.name.lower() != "fomod":
            continue
        for entry in child.iterdir():
            if entry.is_file() and entry.name.lower() == "moduleconfig.xml":
                return entry
    return None


# -- parsing -----------------------------------------------------


def _local(tag: str) -> str:
    """Strips any XML namespace, so ``{ns}group`` matches ``group``.
    Namespaced ModuleConfig files are rare but do exist."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(node: ET.Element, name: str) -> ET.Element | None:
    for child in node:
        if _local(child.tag) == name:
            return child
    return None


def _findall(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node if _local(child.tag) == name]


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _enum(enum_cls, raw: str | None, default):
    """Case-insensitive enum lookup that falls back to ``default`` rather
    than raising - a typo'd group type shouldn't sink the whole install."""
    if not raw:
        return default
    wanted = raw.strip().lower()
    for member in enum_cls:
        if member.value.lower() == wanted:
            return member
    return default


def _parse_file_entries(container: ET.Element | None) -> list[FileEntry]:
    if container is None:
        return []
    entries: list[FileEntry] = []
    for child in container:
        kind = _local(child.tag)
        if kind not in ("file", "folder"):
            continue
        source = (child.get("source") or "").strip()
        if not source:
            continue
        destination = child.get("destination")
        entries.append(
            FileEntry(
                source=source,
                # An omitted destination means "same place as source" -
                # note an empty-string destination is meaningful and
                # different: it means the payload root.
                destination=(destination if destination is not None else source).strip(),
                is_folder=kind == "folder",
                priority=_int(child.get("priority"), 0),
                always_install=_bool(child.get("alwaysInstall")),
                install_if_usable=_bool(child.get("installIfUsable")),
            )
        )
    return entries


def _int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _bool(raw: str | None) -> bool:
    return str(raw).strip().lower() == "true"


def _parse_dependencies(node: ET.Element | None) -> DependencyGroup:
    """Parses a ``<dependencies>``/``<visible>`` node. Unsupported
    dependency kinds (game/fomm version checks) are skipped rather than
    failing - see the module docstring."""
    group = DependencyGroup()
    if node is None:
        return group
    group.operator = "Or" if (node.get("operator") or "And").strip().lower() == "or" else "And"
    for child in node:
        kind = _local(child.tag)
        if kind == "flagDependency":
            group.flags.append(
                FlagDependency(flag=(child.get("flag") or "").strip(), value=(child.get("value") or "").strip())
            )
        elif kind == "fileDependency":
            group.files.append(
                FileDependency(
                    file=(child.get("file") or "").strip(),
                    state=(child.get("state") or "Active").strip(),
                )
            )
        elif kind == "dependencies":
            group.children.append(_parse_dependencies(child))
    return group


def _parse_type_descriptor(node: ET.Element | None) -> tuple[PluginType, list[TypePattern]]:
    if node is None:
        return PluginType.OPTIONAL, []

    static = _find(node, "type")
    if static is not None:
        return _enum(PluginType, static.get("name"), PluginType.OPTIONAL), []

    dependency_type = _find(node, "dependencyType")
    if dependency_type is None:
        return PluginType.OPTIONAL, []

    default_node = _find(dependency_type, "defaultType")
    default = _enum(PluginType, default_node.get("name") if default_node is not None else None, PluginType.OPTIONAL)

    patterns: list[TypePattern] = []
    patterns_node = _find(dependency_type, "patterns")
    for pattern in _findall(patterns_node, "pattern") if patterns_node is not None else []:
        type_node = _find(pattern, "type")
        patterns.append(
            TypePattern(
                dependencies=_parse_dependencies(_find(pattern, "dependencies")),
                type=_enum(PluginType, type_node.get("name") if type_node is not None else None, default),
            )
        )
    return default, patterns


def _parse_plugin(node: ET.Element) -> Plugin:
    default_type, patterns = _parse_type_descriptor(_find(node, "typeDescriptor"))
    flags_node = _find(node, "conditionFlags")
    return Plugin(
        name=(node.get("name") or "").strip() or "(unnamed option)",
        description=_text(_find(node, "description")),
        files=_parse_file_entries(_find(node, "files")),
        condition_flags=[
            FlagDependency(flag=(f.get("name") or "").strip(), value=_text(f))
            for f in (_findall(flags_node, "flag") if flags_node is not None else [])
        ],
        default_type=default_type,
        type_patterns=patterns,
    )


def _ordered(nodes: list[ET.Element], order: str | None) -> list[ET.Element]:
    """``order`` defaults to ``Ascending`` (alphabetical by name) per the
    schema; ``Explicit`` keeps document order."""
    mode = (order or "Ascending").strip().lower()
    if mode == "explicit":
        return nodes
    reverse = mode == "descending"
    return sorted(nodes, key=lambda n: (n.get("name") or "").lower(), reverse=reverse)


def _parse_group(node: ET.Element) -> Group:
    plugins_node = _find(node, "plugins")
    plugin_nodes = _findall(plugins_node, "plugin") if plugins_node is not None else []
    ordered = _ordered(plugin_nodes, plugins_node.get("order") if plugins_node is not None else None)
    return Group(
        name=(node.get("name") or "").strip() or "(unnamed group)",
        type=_enum(GroupType, node.get("type"), GroupType.SELECT_ANY),
        plugins=[_parse_plugin(p) for p in ordered],
    )


def _parse_install_step(node: ET.Element) -> InstallStep:
    groups_node = _find(node, "optionalFileGroups")
    group_nodes = _findall(groups_node, "group") if groups_node is not None else []
    ordered = _ordered(group_nodes, groups_node.get("order") if groups_node is not None else None)
    return InstallStep(
        name=(node.get("name") or "").strip() or "Options",
        groups=[_parse_group(g) for g in ordered],
        visible=_parse_dependencies(_find(node, "visible")),
    )


def parse_module_config(path: str | Path) -> FomodConfig:
    """Parses a ModuleConfig.xml. Raises ``FomodError`` for anything that
    isn't recognisably one."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise FomodError(f"{path.name} isn't valid XML: {exc}") from exc
    except OSError as exc:
        raise FomodError(f"Couldn't read {path}: {exc}") from exc

    if _local(root.tag) != "config":
        raise FomodError(f"{path.name} has root element <{_local(root.tag)}>, expected <config>")

    steps_node = _find(root, "installSteps")
    step_nodes = _findall(steps_node, "installStep") if steps_node is not None else []
    ordered_steps = _ordered(step_nodes, steps_node.get("order") if steps_node is not None else None)

    conditional: list[ConditionalInstall] = []
    conditional_node = _find(root, "conditionalFileInstalls")
    if conditional_node is not None:
        patterns_node = _find(conditional_node, "patterns")
        for pattern in _findall(patterns_node, "pattern") if patterns_node is not None else []:
            conditional.append(
                ConditionalInstall(
                    dependencies=_parse_dependencies(_find(pattern, "dependencies")),
                    files=_parse_file_entries(_find(pattern, "files")),
                )
            )

    return FomodConfig(
        module_name=_text(_find(root, "moduleName")),
        required_files=_parse_file_entries(_find(root, "requiredInstallFiles")),
        install_steps=[_parse_install_step(s) for s in ordered_steps],
        conditional_installs=conditional,
    )
