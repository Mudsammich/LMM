"""The FOMOD installer wizard.

A thin shell over ``mods/fomod_install`` - all the decision logic (which
options are selectable, which pages are visible, what gets installed)
lives there and is unit tested without Qt. This module only draws it.

One page per visible install step. Because a step's visibility and an
option's Required/NotUsable state can depend on earlier choices, the page
list isn't fixed up front: ``_advance`` recomputes which step comes next
every time the user moves forward.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..mods import fomod_install
from ..mods.fomod import FomodConfig, GroupType, PluginType


class FomodDialog(QDialog):
    """Returns ``QDialog.Accepted`` with ``state`` holding the choices, or
    ``Rejected`` if the user cancelled."""

    def __init__(self, config: FomodConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.state = fomod_install.InstallState()
        self._history: list[int] = []  # visited step indices, for Back
        self._current: int | None = None
        # The current page, held as one widget so switching pages can drop
        # it in a single step - see _rebuild_body.
        self._page: QWidget | None = None
        self._rebuilding = False

        self.setWindowTitle(f"Install {config.module_name}" if config.module_name else "Install mod")
        self.resize(720, 560)

        self.step_label = QLabel()
        self.step_label.setProperty("role", "section")

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setAlignment(Qt.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)

        self.error_label = QLabel()
        self.error_label.setProperty("role", "status")
        self.error_label.setWordWrap(True)

        self.back_btn = QPushButton("Back")
        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("role", "primary")
        cancel_btn = QPushButton("Cancel")

        self.back_btn.clicked.connect(self._go_back)
        self.next_btn.clicked.connect(self._advance)
        cancel_btn.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(cancel_btn)
        button_row.addStretch(1)
        button_row.addWidget(self.back_btn)
        button_row.addWidget(self.next_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.step_label)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(button_row)

        first = self._next_visible_after(None)
        if first is None:
            # Nothing to ask - a FOMOD that's really just a fixed file list.
            self.state = fomod_install.InstallState()
            self._finished_immediately = True
        else:
            self._finished_immediately = False
            self._show_step(first)

    # -- navigation -----------------------------------------------------

    @property
    def needs_no_input(self) -> bool:
        return self._finished_immediately

    def _next_visible_after(self, after: int | None) -> int | None:
        """The next step whose visibility condition currently passes.
        Recomputed each time, since the answer depends on choices already
        made."""
        visible = fomod_install.visible_steps(self.config, self.state)
        for index in visible:
            if not self.config.install_steps[index].groups:
                continue  # nothing to ask on this page
            if after is None or index > after:
                return index
        return None

    def _show_step(self, index: int) -> None:
        self._current = index
        fomod_install.apply_defaults(self.config, self.state, index)

        step = self.config.install_steps[index]
        position = len(self._history) + 1
        self.step_label.setText(f"Step {position}: {step.name}")
        self.back_btn.setEnabled(bool(self._history))
        self._rebuild_body()

    def _rebuild_body(self) -> None:
        # Guards against setChecked() below being mistaken for a click:
        # checking one radio makes Qt uncheck its siblings, which fires
        # their toggled signals mid-rebuild.
        self._rebuilding = True
        try:
            self._build_page()
        finally:
            self._rebuilding = False
        self._refresh_validity()

    def _build_page(self) -> None:
        # setParent(None) detaches the old page immediately; deleteLater on
        # its own only *schedules* destruction, which would leave the
        # previous page's widgets painted underneath the new one until the
        # event loop caught up. Its child QButtonGroups go with it.
        if self._page is not None:
            self._page.setParent(None)
            self._page.deleteLater()
            self._page = None

        assert self._current is not None
        step_index = self._current
        step = self.config.install_steps[step_index]
        # Includes this step's own choices: an option's Required/NotUsable
        # state routinely depends on a flag set by an earlier group on the
        # same page.
        flags = fomod_install.flags_for(self.config, self.state, up_to_step=step_index + 1)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setAlignment(Qt.AlignTop)

        for group_index, group in enumerate(step.groups):
            group_label = QLabel(f"{group.name}  ({_cardinality_hint(group.type)})")
            group_label.setProperty("role", "section")
            page_layout.addWidget(group_label)

            # Radios only for SelectExactlyOne. SelectAtMostOne is also
            # exclusive but has to allow *zero*, which a Qt radio group
            # can't express - so it gets checkboxes whose exclusivity is
            # enforced in the model instead (see _on_toggled).
            use_radio = group.type == GroupType.SELECT_EXACTLY_ONE
            button_group = QButtonGroup(page) if use_radio else None

            for plugin_index, plugin in enumerate(group.plugins):
                ptype = fomod_install.plugin_type(plugin, flags)
                key = (step_index, group_index, plugin_index)

                if use_radio:
                    button = QRadioButton(_option_label(plugin.name, ptype))
                    button_group.addButton(button)
                else:
                    button = QCheckBox(_option_label(plugin.name, ptype))

                # Forced states are written back to the model, not just the
                # widget, so what installs matches what's on screen after a
                # choice elsewhere on the page changes an option's type.
                if ptype == PluginType.NOT_USABLE:
                    self.state.select(key, False)
                elif ptype == PluginType.REQUIRED:
                    self.state.select(key, True)

                button.setChecked(self.state.is_selected(key))
                if ptype in (PluginType.NOT_USABLE, PluginType.REQUIRED):
                    button.setEnabled(False)

                button.toggled.connect(
                    lambda checked, k=key, exclusive=group.type.is_exclusive, si=step_index, gi=group_index: self._on_toggled(
                        k, checked, exclusive, si, gi
                    )
                )
                page_layout.addWidget(button)

                if plugin.description:
                    description = QLabel(plugin.description)
                    description.setWordWrap(True)
                    description.setIndent(24)
                    page_layout.addWidget(description)

        self._page = page
        self.body_layout.addWidget(page)
        # Reparenting into a layout hides a widget, and nothing shows it
        # again once the dialog itself is already visible - so a rebuilt
        # page would silently render blank without this.
        page.show()

    def _on_toggled(
        self, key, checked: bool, exclusive: bool, step_index: int, group_index: int
    ) -> None:
        if self._rebuilding:
            return  # setChecked() during a rebuild isn't a user choice
        if exclusive and checked:
            self.state.clear_group(step_index, group_index)
        self.state.select(key, checked)

        # A choice here can change what later steps show and which options
        # are usable, so drop anything chosen after this point rather than
        # carrying stale selections forward.
        for later in range(step_index + 1, len(self.config.install_steps)):
            self.state.clear_step(later)

        # Options elsewhere on this page may have just become required or
        # unavailable, so redraw it. Deferred, because this runs inside a
        # button's own toggled signal and the rebuild destroys that button.
        QTimer.singleShot(0, self._rebuild_body)
        self._refresh_validity()

    def _refresh_validity(self) -> None:
        assert self._current is not None
        step = self.config.install_steps[self._current]
        errors = [
            error
            for group_index, group in enumerate(step.groups)
            if (error := fomod_install.group_error(group, self._current, group_index, self.state))
        ]
        self.error_label.setText("\n".join(errors))
        self.next_btn.setEnabled(not errors)

        is_last = self._next_visible_after(self._current) is None
        self.next_btn.setText("Install" if is_last else "Next")

    def _advance(self) -> None:
        assert self._current is not None
        following = self._next_visible_after(self._current)
        if following is None:
            self.accept()
            return
        self._history.append(self._current)
        self._show_step(following)

    def _go_back(self) -> None:
        if not self._history:
            return
        previous = self._history.pop()
        self._show_step(previous)


def _cardinality_hint(group_type: GroupType) -> str:
    return {
        GroupType.SELECT_EXACTLY_ONE: "choose one",
        GroupType.SELECT_AT_MOST_ONE: "choose one, or none",
        GroupType.SELECT_AT_LEAST_ONE: "choose one or more",
        GroupType.SELECT_ANY: "choose any",
        GroupType.SELECT_ALL: "all included",
    }.get(group_type, "choose any")


def _option_label(name: str, ptype: PluginType) -> str:
    if ptype == PluginType.RECOMMENDED:
        return f"{name}  - recommended"
    if ptype == PluginType.REQUIRED:
        return f"{name}  - required"
    if ptype == PluginType.NOT_USABLE:
        return f"{name}  - not available with your other choices"
    if ptype == PluginType.COULD_BE_USABLE:
        return f"{name}  - may need something you don't have installed"
    return name
