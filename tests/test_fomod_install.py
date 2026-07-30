import pytest

from lmm.mods import fomod, fomod_install
from lmm.mods.fomod_install import InstallState

from test_fomod import SAMPLE


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(SAMPLE, encoding="utf-8")
    return fomod.parse_module_config(path)


# -- condition evaluation -----------------------------------------------------


def test_empty_dependencies_are_always_satisfied():
    assert fomod_install.evaluate(fomod.DependencyGroup(), {}) is True


def test_and_requires_every_condition():
    group = fomod.DependencyGroup(
        operator="And",
        flags=[fomod.FlagDependency("a", "1"), fomod.FlagDependency("b", "2")],
    )
    assert fomod_install.evaluate(group, {"a": "1", "b": "2"})
    assert not fomod_install.evaluate(group, {"a": "1"})


def test_or_requires_only_one():
    group = fomod.DependencyGroup(
        operator="Or",
        flags=[fomod.FlagDependency("a", "1"), fomod.FlagDependency("b", "2")],
    )
    assert fomod_install.evaluate(group, {"b": "2"})
    assert not fomod_install.evaluate(group, {"c": "3"})


def test_nested_dependency_groups():
    inner = fomod.DependencyGroup(operator="Or", flags=[fomod.FlagDependency("x", "on")])
    outer = fomod.DependencyGroup(
        operator="And", flags=[fomod.FlagDependency("y", "on")], children=[inner]
    )
    assert fomod_install.evaluate(outer, {"x": "on", "y": "on"})
    assert not fomod_install.evaluate(outer, {"y": "on"})


def test_unset_flag_matches_empty_value():
    """An installer testing value="" means "this was never chosen"."""
    group = fomod.DependencyGroup(flags=[fomod.FlagDependency("never", "")])
    assert fomod_install.evaluate(group, {})


def test_file_dependency_unknown_is_treated_as_satisfied():
    group = fomod.DependencyGroup(files=[fomod.FileDependency("Foo.esm", "Active")])
    assert fomod_install.evaluate(group, {}, installed_files=None)


def test_file_dependency_checked_against_installed_set():
    active = fomod.DependencyGroup(files=[fomod.FileDependency("Foo.esm", "Active")])
    missing = fomod.DependencyGroup(files=[fomod.FileDependency("Foo.esm", "Missing")])
    installed = {"foo.esm"}
    assert fomod_install.evaluate(active, {}, installed)
    assert not fomod_install.evaluate(missing, {}, installed)
    assert fomod_install.evaluate(missing, {}, set())


# -- flags and visibility -----------------------------------------------------


def test_selecting_an_option_sets_its_flag(config):
    state = InstallState()
    state.select((0, 0, 0))  # Slim
    assert fomod_install.flags_for(config, state) == {"body": "slim"}


def test_step_visibility_follows_flags(config):
    state = InstallState()
    state.select((0, 0, 1))  # Curvy
    assert fomod_install.visible_steps(config, state) == [0]

    state = InstallState()
    state.select((0, 0, 0))  # Slim unlocks the extras step
    assert fomod_install.visible_steps(config, state) == [0, 1]


def test_flags_for_excludes_later_steps(config):
    """A step's own visibility can't depend on choices inside it."""
    state = InstallState()
    state.select((1, 0, 0))
    assert fomod_install.flags_for(config, state, up_to_step=1) == {}


def test_dynamic_plugin_type_resolves_from_flags(config):
    plugin = config.install_steps[1].groups[0].plugins[0]
    assert fomod_install.plugin_type(plugin, {}) is fomod.PluginType.NOT_USABLE
    assert fomod_install.plugin_type(plugin, {"body": "slim"}) is fomod.PluginType.OPTIONAL


# -- defaults -----------------------------------------------------


def test_defaults_pick_the_recommended_option(config):
    state = InstallState()
    fomod_install.apply_defaults(config, state, 0)
    assert state.is_selected((0, 0, 0))  # Slim is Recommended
    assert not state.is_selected((0, 0, 1))


def test_defaults_fill_a_required_group_with_no_recommendation(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        """<config><moduleName>M</moduleName><installSteps order="Explicit">
        <installStep name="S"><optionalFileGroups order="Explicit">
        <group name="G" type="SelectExactlyOne"><plugins order="Explicit">
        <plugin name="A"><description>a</description>
          <typeDescriptor><type name="Optional"/></typeDescriptor></plugin>
        <plugin name="B"><description>b</description>
          <typeDescriptor><type name="Optional"/></typeDescriptor></plugin>
        </plugins></group></optionalFileGroups></installStep>
        </installSteps></config>""",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    state = InstallState()
    fomod_install.apply_defaults(config, state, 0)
    assert state.is_selected((0, 0, 0))  # can't leave SelectExactlyOne empty


def test_defaults_skip_a_not_usable_option(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        """<config><moduleName>M</moduleName><installSteps order="Explicit">
        <installStep name="S"><optionalFileGroups order="Explicit">
        <group name="G" type="SelectExactlyOne"><plugins order="Explicit">
        <plugin name="Blocked"><description>x</description>
          <typeDescriptor><type name="NotUsable"/></typeDescriptor></plugin>
        <plugin name="Fine"><description>y</description>
          <typeDescriptor><type name="Optional"/></typeDescriptor></plugin>
        </plugins></group></optionalFileGroups></installStep>
        </installSteps></config>""",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    state = InstallState()
    fomod_install.apply_defaults(config, state, 0)
    assert not state.is_selected((0, 0, 0))
    assert state.is_selected((0, 0, 1))


def test_select_all_group_selects_everything(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        """<config><moduleName>M</moduleName><installSteps order="Explicit">
        <installStep name="S"><optionalFileGroups order="Explicit">
        <group name="G" type="SelectAll"><plugins order="Explicit">
        <plugin name="A"><description>a</description></plugin>
        <plugin name="B"><description>b</description></plugin>
        </plugins></group></optionalFileGroups></installStep>
        </installSteps></config>""",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    state = InstallState()
    fomod_install.apply_defaults(config, state, 0)
    assert state.is_selected((0, 0, 0)) and state.is_selected((0, 0, 1))


# -- validation -----------------------------------------------------


def test_select_exactly_one_reports_an_error_when_empty(config):
    group = config.install_steps[0].groups[0]
    state = InstallState()
    assert fomod_install.group_error(group, 0, 0, state) is not None
    state.select((0, 0, 0))
    assert fomod_install.group_error(group, 0, 0, state) is None


# -- file resolution -----------------------------------------------------


def test_resolve_includes_required_and_selected_files(config):
    state = InstallState()
    state.select((0, 0, 0))  # Slim
    sources = {r.source for r in fomod_install.resolve_files(config, state)}
    assert "00 Core" in sources  # requiredInstallFiles
    assert "01 Slim" in sources
    assert "02 Curvy" not in sources


def test_resolve_applies_conditional_file_installs(config):
    state = InstallState()
    state.select((0, 0, 1))  # Curvy triggers the conditional patch
    sources = {r.source for r in fomod_install.resolve_files(config, state)}
    assert "99 Curvy Patch" in sources


def test_resolve_ignores_selections_in_hidden_steps(config):
    """Picking Curvy hides the slim-only extras step, so a leftover
    selection there must not install anything."""
    state = InstallState()
    state.select((0, 0, 1))  # Curvy - hides step 1
    state.select((1, 0, 0))  # stale selection from before
    sources = {r.source for r in fomod_install.resolve_files(config, state)}
    assert "03 Slim Armour" not in sources


def test_resolve_normalises_windows_separators(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        '<config><moduleName>M</moduleName><requiredInstallFiles>'
        r'<folder source="00 Core\Textures" destination="Textures"/>'
        "</requiredInstallFiles></config>",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    resolved = fomod_install.resolve_files(config, InstallState())
    assert resolved[0].source == "00 Core/Textures"


def test_sources_sharing_a_destination_are_ordered_by_priority(tmp_path):
    """Both must survive - they merge into one folder - but the higher
    priority one has to be copied last so it wins any shared file."""
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        '<config><moduleName>M</moduleName><requiredInstallFiles>'
        '<folder source="high" destination="Textures" priority="5"/>'
        '<folder source="low" destination="Textures" priority="0"/>'
        "</requiredInstallFiles></config>",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    resolved = fomod_install.resolve_files(config, InstallState())
    assert [r.source for r in resolved] == ["low", "high"]


def test_exact_duplicate_entries_are_dropped(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        '<config><moduleName>M</moduleName><requiredInstallFiles>'
        '<folder source="Core" destination="" priority="0"/>'
        '<folder source="Core" destination="" priority="0"/>'
        "</requiredInstallFiles></config>",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    assert len(fomod_install.resolve_files(config, InstallState())) == 1


def test_higher_priority_source_overwrites_on_copy(tmp_path):
    extracted = tmp_path / "extracted"
    for name in ("low", "high"):
        (extracted / name).mkdir(parents=True)
        (extracted / name / "shared.dds").write_text(name)
    dest = tmp_path / "staged"

    fomod_install.stage_resolved_files(
        extracted,
        [
            fomod_install.ResolvedFile("low", "Textures", 0),
            fomod_install.ResolvedFile("high", "Textures", 5),
        ],
        dest,
    )

    assert (dest / "Textures" / "shared.dds").read_text() == "high"


# -- staging -----------------------------------------------------


def test_stage_copies_folders_to_their_destination(tmp_path):
    extracted = tmp_path / "extracted"
    (extracted / "00 Core" / "Textures").mkdir(parents=True)
    (extracted / "00 Core" / "Textures" / "thing.dds").write_text("data")
    dest = tmp_path / "staged"

    copied = fomod_install.stage_resolved_files(
        extracted, [fomod_install.ResolvedFile("00 Core", "", 0)], dest
    )

    assert copied == 1
    assert (dest / "Textures" / "thing.dds").read_text() == "data"


def test_stage_matches_sources_case_insensitively(tmp_path):
    """ModuleConfig paths are written for Windows and routinely disagree
    with the archive's real capitalisation."""
    extracted = tmp_path / "extracted"
    (extracted / "00 core" / "textures").mkdir(parents=True)
    (extracted / "00 core" / "textures" / "thing.dds").write_text("data")
    dest = tmp_path / "staged"

    copied = fomod_install.stage_resolved_files(
        extracted, [fomod_install.ResolvedFile("00 Core/Textures", "Textures", 0)], dest
    )

    assert copied == 1
    assert (dest / "Textures" / "thing.dds").read_text() == "data"


def test_stage_skips_a_source_the_archive_lacks(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    dest = tmp_path / "staged"

    copied = fomod_install.stage_resolved_files(
        extracted, [fomod_install.ResolvedFile("nope", "", 0)], dest
    )

    assert copied == 0


def test_stage_copies_a_single_file_with_a_rename(tmp_path):
    extracted = tmp_path / "extracted"
    (extracted / "docs").mkdir(parents=True)
    (extracted / "docs" / "readme.txt").write_text("hi")
    dest = tmp_path / "staged"

    copied = fomod_install.stage_resolved_files(
        extracted, [fomod_install.ResolvedFile("docs/readme.txt", "Docs/About.txt", 0)], dest
    )

    assert copied == 1
    assert (dest / "Docs" / "About.txt").read_text() == "hi"


# -- same-step flag dependencies -----------------------------------------------------

# Shaped directly after Nexus's own Vortex test fixture, where a "Results"
# group's options depend on flags set by a *different group in the same
# step* - the case that breaks if evaluation only looks at earlier steps.
SAME_STEP = """<config>
  <moduleName>Same Step</moduleName>
  <installSteps order="Explicit">
    <installStep name="Everything">
      <optionalFileGroups order="Explicit">
        <group name="Choice" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="File A">
              <description>a</description>
              <conditionFlags><flag name="picked">a</flag></conditionFlags>
              <typeDescriptor><type name="Optional"/></typeDescriptor>
            </plugin>
            <plugin name="File B">
              <description>b</description>
              <conditionFlags><flag name="picked">b</flag></conditionFlags>
              <typeDescriptor><type name="Optional"/></typeDescriptor>
            </plugin>
          </plugins>
        </group>
        <group name="Results" type="SelectAny">
          <plugins order="Explicit">
            <plugin name="A Result">
              <description>only when A</description>
              <files><folder source="A Files" destination=""/></files>
              <typeDescriptor>
                <dependencyType>
                  <defaultType name="NotUsable"/>
                  <patterns>
                    <pattern>
                      <dependencies><flagDependency flag="picked" value="a"/></dependencies>
                      <type name="Required"/>
                    </pattern>
                  </patterns>
                </dependencyType>
              </typeDescriptor>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
  </installSteps>
</config>
"""


@pytest.fixture
def same_step_config(tmp_path):
    path = tmp_path / "SameStep.xml"
    path.write_text(SAME_STEP, encoding="utf-8")
    return fomod.parse_module_config(path)


def test_same_step_flags_drive_a_later_groups_type(same_step_config):
    config = same_step_config
    result_plugin = config.install_steps[0].groups[1].plugins[0]

    state = InstallState()
    state.select((0, 0, 0))  # File A, in the same step
    flags = fomod_install.flags_for(config, state, up_to_step=1)
    assert fomod_install.plugin_type(result_plugin, flags) is fomod.PluginType.REQUIRED

    state = InstallState()
    state.select((0, 0, 1))  # File B
    flags = fomod_install.flags_for(config, state, up_to_step=1)
    assert fomod_install.plugin_type(result_plugin, flags) is fomod.PluginType.NOT_USABLE


def test_defaults_see_earlier_groups_in_the_same_step(same_step_config):
    """Group 2's Required option must be auto-selected because group 1's
    default set the flag it depends on."""
    state = InstallState()
    fomod_install.apply_defaults(same_step_config, state, 0)

    assert state.is_selected((0, 0, 0))  # first selectable in exclusive group
    assert state.is_selected((0, 1, 0))  # became Required via that flag


def test_same_step_required_option_installs_its_files(same_step_config):
    state = InstallState()
    fomod_install.apply_defaults(same_step_config, state, 0)
    sources = {r.source for r in fomod_install.resolve_files(same_step_config, state)}
    assert "A Files" in sources
