"""Tests for DCCAccordion widget."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from dcc_accordion import DCCAccordion
from dcc_section import DEFAULT_DCC_CONFIGS, DCCConfig, DCCSection
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def mock_shot() -> MagicMock:
    """Create a mock shot for testing."""
    shot = MagicMock()
    shot.full_name = "sq010_sh0010"
    shot.show = "myshow"
    shot.sequence = "sq010"
    shot.shot = "sh0010"
    return shot


class TestDCCAccordionInit:
    """Tests for DCCAccordion initialization."""

    def test_default_configs(self, qtbot: QtBot) -> None:
        """Uses default configs when none provided."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        # Should have sections for all default DCCs
        assert len(accordion._sections) == len(DEFAULT_DCC_CONFIGS)
        for config in DEFAULT_DCC_CONFIGS:
            assert config.name in accordion._sections

    def test_custom_configs(self, qtbot: QtBot) -> None:
        """Accepts custom configurations."""
        configs = [
            DCCConfig("app1", "App One", "#ff0000", "1"),
            DCCConfig("app2", "App Two", "#00ff00", "2"),
        ]
        accordion = DCCAccordion(configs=configs)
        qtbot.addWidget(accordion)

        assert len(accordion._sections) == 2
        assert "app1" in accordion._sections
        assert "app2" in accordion._sections

    def test_sections_disabled_initially(self, qtbot: QtBot) -> None:
        """All sections disabled until shot is set."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        for section in accordion._sections.values():
            assert not section._launch_btn.isEnabled()

    def test_parent_parameter(self, qtbot: QtBot) -> None:
        """Accepts parent parameter."""
        from PySide6.QtWidgets import QWidget

        parent = QWidget()
        accordion = DCCAccordion(parent=parent)
        qtbot.addWidget(parent)

        assert accordion.parent() is parent


class TestDCCAccordionShotHandling:
    """Tests for shot selection handling."""

    def test_set_shot_enables_sections(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Setting a shot enables all sections."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_shot(mock_shot)

        for section in accordion._sections.values():
            assert section._launch_btn.isEnabled()

    def test_clear_shot_disables_sections(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Clearing shot disables all sections."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_shot(mock_shot)
        accordion.set_shot(None)

        for section in accordion._sections.values():
            assert not section._launch_btn.isEnabled()

    def test_set_enabled_controls_all_sections(self, qtbot: QtBot) -> None:
        """set_enabled affects all sections."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_enabled(True)
        for section in accordion._sections.values():
            assert section._launch_btn.isEnabled()

        accordion.set_enabled(False)
        for section in accordion._sections.values():
            assert not section._launch_btn.isEnabled()


class TestDCCAccordionLaunchSignal:
    """Tests for launch signal emission."""

    def test_section_launch_emits_accordion_signal(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Section launch request is forwarded through accordion."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)
        accordion.set_shot(mock_shot)

        # Get the 3de section and expand it
        section = accordion._sections["3de"]
        section.set_expanded(True)
        accordion.show()
        process_qt_events()

        # Click launch on the section
        with qtbot.waitSignal(accordion.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

        app_name, options = blocker.args
        assert app_name == "3de"
        assert isinstance(options, dict)

    def test_different_sections_emit_correct_app_names(
        self, qtbot: QtBot, mock_shot: MagicMock
    ) -> None:
        """Each section emits its correct app name."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)
        accordion.set_shot(mock_shot)
        accordion.show()
        process_qt_events()

        # Test each section
        for app_name in ["3de", "nuke", "maya", "rv"]:
            section = accordion._sections[app_name]
            section.set_expanded(True)
            process_qt_events()

            with qtbot.waitSignal(accordion.launch_requested, timeout=1000) as blocker:
                qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
                process_qt_events()

            assert blocker.args[0] == app_name
            section.set_expanded(False)


class TestDCCAccordionExpansion:
    """Tests for expansion management."""

    def test_set_section_expanded(self, qtbot: QtBot) -> None:
        """Can expand specific section programmatically."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_section_expanded("nuke", True)
        assert accordion._sections["nuke"].is_expanded()

        accordion.set_section_expanded("nuke", False)
        assert not accordion._sections["nuke"].is_expanded()

    def test_expand_all(self, qtbot: QtBot) -> None:
        """Can expand all sections at once."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.expand_all()

        for section in accordion._sections.values():
            assert section.is_expanded()

    def test_collapse_all(self, qtbot: QtBot) -> None:
        """Can collapse all sections at once."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.expand_all()
        accordion.collapse_all()

        for section in accordion._sections.values():
            assert not section.is_expanded()

    def test_get_expanded_sections(self, qtbot: QtBot) -> None:
        """Can get list of expanded section names."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_section_expanded("3de", True)
        accordion.set_section_expanded("nuke", True)

        expanded = accordion.get_expanded_sections()
        assert "3de" in expanded
        assert "nuke" in expanded
        assert "maya" not in expanded

    def test_multiple_sections_can_be_expanded(self, qtbot: QtBot) -> None:
        """Multiple sections can be open simultaneously."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_section_expanded("3de", True)
        accordion.set_section_expanded("nuke", True)
        accordion.set_section_expanded("maya", True)

        assert accordion._sections["3de"].is_expanded()
        assert accordion._sections["nuke"].is_expanded()
        assert accordion._sections["maya"].is_expanded()


class TestDCCAccordionPlateSelector:
    """Tests for plate selector management."""

    def test_set_available_plates_updates_all_sections(self, qtbot: QtBot) -> None:
        """Plates are set on all sections."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        accordion.set_available_plates(["FG01", "BG01"])

        for section in accordion._sections.values():
            if section._plate_selector:
                assert section._plate_selector.count() == 2


class TestDCCAccordionVersionInfo:
    """Tests for version info management."""

    def test_set_version_info(self, qtbot: QtBot) -> None:
        """Can set version info for specific DCC."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)
        accordion.show()
        process_qt_events()

        accordion.set_version_info("3de", "v005", "21m ago")
        process_qt_events()

        section = accordion._sections["3de"]
        assert section._version_label.isVisible()
        assert "v005" in section._version_label.text()

    def test_clear_version_info(self, qtbot: QtBot) -> None:
        """Can clear all version info."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)
        accordion.show()
        process_qt_events()

        accordion.set_version_info("3de", "v005")
        accordion.set_version_info("nuke", "v012")
        accordion.clear_version_info()
        process_qt_events()

        for section in accordion._sections.values():
            assert not section._version_label.isVisible()


class TestDCCAccordionSectionAccess:
    """Tests for section access methods."""

    def test_get_section(self, qtbot: QtBot) -> None:
        """Can get section by app name."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        section = accordion.get_section("nuke")
        assert section is not None
        assert isinstance(section, DCCSection)
        assert section is accordion._sections["nuke"]

    def test_get_section_not_found(self, qtbot: QtBot) -> None:
        """Returns None for unknown section."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        section = accordion.get_section("unknown")
        assert section is None

    def test_get_options(self, qtbot: QtBot) -> None:
        """Can get options for specific DCC."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        options = accordion.get_options("nuke")
        assert options is not None
        assert "open_latest_scene" in options

    def test_get_options_not_found(self, qtbot: QtBot) -> None:
        """Returns None for unknown DCC."""
        accordion = DCCAccordion()
        qtbot.addWidget(accordion)

        options = accordion.get_options("unknown")
        assert options is None
