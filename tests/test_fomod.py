import pytest

from lmm.mods import fomod

# Shaped after Nexus's own Vortex test fixture (tools/testfomod), which
# exercises static types, flag-driven dynamic types, and both group orders.
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <moduleName>Test Module</moduleName>
  <requiredInstallFiles>
    <folder source="00 Core" destination="" priority="0"/>
    <file source="docs/readme.txt" destination="readme.txt"/>
  </requiredInstallFiles>
  <installSteps order="Explicit">
    <installStep name="Body Type">
      <optionalFileGroups order="Explicit">
        <group name="Pick a body" type="SelectExactlyOne">
          <plugins order="Explicit">
            <plugin name="Slim">
              <description>Slim body</description>
              <files>
                <folder source="01 Slim" destination=""/>
              </files>
              <conditionFlags>
                <flag name="body">slim</flag>
              </conditionFlags>
              <typeDescriptor><type name="Recommended"/></typeDescriptor>
            </plugin>
            <plugin name="Curvy">
              <description>Curvy body</description>
              <files>
                <folder source="02 Curvy" destination=""/>
              </files>
              <conditionFlags>
                <flag name="body">curvy</flag>
              </conditionFlags>
              <typeDescriptor><type name="Optional"/></typeDescriptor>
            </plugin>
          </plugins>
        </group>
      </optionalFileGroups>
    </installStep>
    <installStep name="Slim Extras">
      <visible>
        <dependencies operator="And">
          <flagDependency flag="body" value="slim"/>
        </dependencies>
      </visible>
      <optionalFileGroups>
        <group name="Extras" type="SelectAny">
          <plugins order="Explicit">
            <plugin name="Extra Armour">
              <description>Only makes sense for slim</description>
              <files><folder source="03 Slim Armour" destination=""/></files>
              <typeDescriptor>
                <dependencyType>
                  <defaultType name="NotUsable"/>
                  <patterns>
                    <pattern>
                      <dependencies>
                        <flagDependency flag="body" value="slim"/>
                      </dependencies>
                      <type name="Optional"/>
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
  <conditionalFileInstalls>
    <patterns>
      <pattern>
        <dependencies>
          <flagDependency flag="body" value="curvy"/>
        </dependencies>
        <files>
          <folder source="99 Curvy Patch" destination=""/>
        </files>
      </pattern>
    </patterns>
  </conditionalFileInstalls>
</config>
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(SAMPLE, encoding="utf-8")
    return fomod.parse_module_config(path)


def test_parses_module_name_and_required_files(config):
    assert config.module_name == "Test Module"
    assert len(config.required_files) == 2
    core = config.required_files[0]
    assert core.source == "00 Core"
    assert core.destination == ""  # explicit empty means the payload root
    assert core.is_folder is True
    assert config.required_files[1].is_folder is False


def test_parses_steps_groups_and_plugins(config):
    assert [s.name for s in config.install_steps] == ["Body Type", "Slim Extras"]
    group = config.install_steps[0].groups[0]
    assert group.type is fomod.GroupType.SELECT_EXACTLY_ONE
    assert group.type.is_exclusive
    assert group.type.requires_selection
    assert [p.name for p in group.plugins] == ["Slim", "Curvy"]
    assert group.plugins[0].description == "Slim body"
    assert group.plugins[0].default_type is fomod.PluginType.RECOMMENDED


def test_parses_condition_flags(config):
    slim = config.install_steps[0].groups[0].plugins[0]
    assert [(f.flag, f.value) for f in slim.condition_flags] == [("body", "slim")]


def test_parses_step_visibility_condition(config):
    visible = config.install_steps[1].visible
    assert not visible.is_empty()
    # <visible> wraps a <dependencies> child here, which nests one level.
    nested = visible.children[0]
    assert nested.flags[0].flag == "body"
    assert nested.flags[0].value == "slim"


def test_parses_dynamic_plugin_type(config):
    plugin = config.install_steps[1].groups[0].plugins[0]
    assert plugin.default_type is fomod.PluginType.NOT_USABLE
    assert len(plugin.type_patterns) == 1
    assert plugin.type_patterns[0].type is fomod.PluginType.OPTIONAL


def test_parses_conditional_file_installs(config):
    assert len(config.conditional_installs) == 1
    conditional = config.conditional_installs[0]
    assert conditional.dependencies.flags[0].value == "curvy"
    assert conditional.files[0].source == "99 Curvy Patch"


def test_has_choices(config):
    assert config.has_choices


def test_omitted_destination_defaults_to_source(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        '<config><moduleName>M</moduleName><requiredInstallFiles>'
        '<folder source="Textures"/></requiredInstallFiles></config>',
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    assert config.required_files[0].destination == "Textures"


def test_alphabetical_order_is_the_default(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        """<config><moduleName>M</moduleName><installSteps>
        <installStep name="Zebra"><optionalFileGroups/></installStep>
        <installStep name="Apple"><optionalFileGroups/></installStep>
        </installSteps></config>""",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    assert [s.name for s in config.install_steps] == ["Apple", "Zebra"]


def test_namespaced_xml_is_understood(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        '<config xmlns="http://example.com/fomod"><moduleName>Namespaced</moduleName></config>',
        encoding="utf-8",
    )
    assert fomod.parse_module_config(path).module_name == "Namespaced"


def test_unknown_group_type_falls_back_instead_of_raising(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text(
        """<config><moduleName>M</moduleName><installSteps order="Explicit">
        <installStep name="S"><optionalFileGroups order="Explicit">
        <group name="G" type="SelectSomeNonsense"><plugins order="Explicit">
        <plugin name="P"><description>d</description></plugin>
        </plugins></group></optionalFileGroups></installStep>
        </installSteps></config>""",
        encoding="utf-8",
    )
    config = fomod.parse_module_config(path)
    assert config.install_steps[0].groups[0].type is fomod.GroupType.SELECT_ANY


def test_malformed_xml_raises_fomod_error(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text("<config><moduleName>unclosed", encoding="utf-8")
    with pytest.raises(fomod.FomodError):
        fomod.parse_module_config(path)


def test_wrong_root_element_raises_fomod_error(tmp_path):
    path = tmp_path / "ModuleConfig.xml"
    path.write_text("<notaconfig/>", encoding="utf-8")
    with pytest.raises(fomod.FomodError):
        fomod.parse_module_config(path)


# -- locating -----------------------------------------------------


def test_find_module_config_is_case_insensitive(tmp_path):
    (tmp_path / "FOMOD").mkdir()
    target = tmp_path / "FOMOD" / "moduleconfig.xml"
    target.write_text("<config/>", encoding="utf-8")
    assert fomod.find_module_config(tmp_path) == target


def test_find_module_config_returns_none_for_a_plain_mod(tmp_path):
    (tmp_path / "Textures").mkdir()
    assert fomod.find_module_config(tmp_path) is None
