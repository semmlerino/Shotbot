"""Tests for DCCSection widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from dcc_section import (
    DEFAULT_DCC_CONFIGS,
    CheckboxConfig,
    DCCConfig,
    DCCSection,
    get_default_config,
)
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def threede_config() -> DCCConfig:
    """Create 3DEqualizer config for testing."""
    return DCCConfig(
        name="3de",
        display_name="3DEqualizer",
        color="#2b4d6f",
        shortcut="3",
        tooltip="Launch 3DE for matchmove/tracking",
        checkboxes=[
            CheckboxConfig(
                label="Open latest 3DE scene",
                tooltip="Auto-open latest scene",
                key="open_latest_threede",
                default=True,
            )
        ],
    )


@pytest.fixture
def nuke_config() -> DCCConfig:
    """Create Nuke config for testing."""
    return DCCConfig(
        name="nuke",
        display_name="Nuke",
        color="#5d4d2b",
        shortcut="N",
        tooltip="Launch Nuke for compositing",
        checkboxes=[
            CheckboxConfig(
                label="Open latest scene",
                tooltip="Open latest Nuke script",
                key="open_latest_scene",
                default=True,
            ),
            CheckboxConfig(
                label="Create new file",
                tooltip="Always create new version",
                key="create_new_file",
                default=False,
            ),
        ],
    )


class TestDCCConfigDefaults:
    """Tests for default DCC configurations."""

    def test_default_configs_exist(self) -> None:
        """Default configurations include standard DCCs."""
        names = [c.name for c in DEFAULT_DCC_CONFIGS]
        assert "3de" in names
        assert "nuke" in names
        assert "maya" in names
        assert "rv" in names

    def test_get_default_config_found(self) -> None:
        """Can retrieve default config by name."""
        config = get_default_config("nuke")
        assert config is not None
        assert config.name == "nuke"
        assert config.display_name == "Nuke"

    def test_get_default_config_not_found(self) -> None:
        """Returns None for unknown config name."""
        config = get_default_config("unknown")
        assert config is None


class TestDCCSectionInit:
    """Tests for DCCSection initialization."""

    def test_default_state_collapsed(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Section is collapsed by default."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        assert not section.is_expanded()

    def test_displays_config_name(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Section displays the DCC display name."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        assert "3DEqualizer" in section._name_label.text()

    def test_no_shortcut_badge_in_header(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Section header no longer displays shortcut badge (removed for cleaner UI)."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        # Verify shortcut badge is NOT present in header (only in Quick Launch now)
        from PySide6.QtWidgets import QLabel

        found_shortcut_badge = False
        for child in section.findChildren(QLabel):
            # Check for standalone shortcut badge (just "3", not part of longer text)
            if child.text().strip() == "3":
                found_shortcut_badge = True
                break
        assert not found_shortcut_badge, "Shortcut badge should not be in DCC header"

    def test_launch_button_disabled_initially(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Launch button is disabled until enabled."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        assert not section._launch_btn.isEnabled()


class TestDCCSectionExpansion:
    """Tests for expand/collapse functionality."""

    def test_toggle_expansion(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Clicking expand button toggles expansion."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        # Initially collapsed
        assert not section.is_expanded()

        # Click to expand
        qtbot.mouseClick(section._expand_btn, Qt.MouseButton.LeftButton)
        process_qt_events()
        assert section.is_expanded()

        # Click to collapse
        qtbot.mouseClick(section._expand_btn, Qt.MouseButton.LeftButton)
        process_qt_events()
        assert not section.is_expanded()

    def test_set_expanded_programmatically(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can set expansion state programmatically."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_expanded(True)
        assert section.is_expanded()

        section.set_expanded(False)
        assert not section.is_expanded()

    def test_expanded_changed_signal_emitted(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Signal emitted when expansion state changes."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        with qtbot.waitSignal(section.expanded_changed, timeout=1000) as blocker:
            section.set_expanded(True)

        assert blocker.args == ["3de", True]

    def test_content_visibility_matches_expansion(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Content visibility matches expansion state."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        # Collapsed - content hidden
        assert not section._content.isVisible()

        # Expanded - content visible
        section.set_expanded(True)
        process_qt_events()
        assert section._content.isVisible()


class TestDCCSectionLaunch:
    """Tests for launch functionality."""

    def test_launch_emits_signal_with_options(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Launch button click emits signal with options."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

        app_name, options = blocker.args
        assert app_name == "3de"
        assert "open_latest_threede" in options

    def test_launch_button_disabled_during_launch(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Launch button temporarily disabled during launch."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        # Click launch
        qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
        process_qt_events()

        # Button should be disabled during launch
        assert not section._launch_btn.isEnabled()
        assert "Launching" in section._launch_btn.text()


class TestDCCSectionCheckboxes:
    """Tests for checkbox handling."""

    def test_checkboxes_created_from_config(
        self, qtbot: QtBot, nuke_config: DCCConfig
    ) -> None:
        """Checkboxes created based on config."""
        section = DCCSection(nuke_config)
        qtbot.addWidget(section)

        assert "open_latest_scene" in section._checkboxes
        assert "create_new_file" in section._checkboxes

    def test_checkbox_default_values(
        self, qtbot: QtBot, nuke_config: DCCConfig
    ) -> None:
        """Checkbox defaults match config."""
        section = DCCSection(nuke_config)
        qtbot.addWidget(section)

        # open_latest_scene default is True
        assert section._checkboxes["open_latest_scene"].isChecked()
        # create_new_file default is False
        assert not section._checkboxes["create_new_file"].isChecked()

    def test_get_checkbox_states(
        self, qtbot: QtBot, nuke_config: DCCConfig
    ) -> None:
        """Can retrieve current checkbox states."""
        section = DCCSection(nuke_config)
        qtbot.addWidget(section)

        states = section.get_checkbox_states()
        assert states["open_latest_scene"] is True
        assert states["create_new_file"] is False

    def test_get_options_includes_checkboxes(
        self, qtbot: QtBot, nuke_config: DCCConfig
    ) -> None:
        """get_options includes checkbox states."""
        section = DCCSection(nuke_config)
        qtbot.addWidget(section)

        options = section.get_options()
        assert "open_latest_scene" in options
        assert "create_new_file" in options


class TestDCCSectionPlateSelector:
    """Tests for plate selector functionality."""

    def test_plate_selector_exists_when_configured(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Plate selector created when has_plate_selector is True."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        assert section._plate_selector is not None

    def test_plate_selector_disabled_initially(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Plate selector disabled until plates are set."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        assert not section._plate_selector.isEnabled()

    def test_set_available_plates(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can set available plates."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_available_plates(["FG01", "BG01"])

        assert section._plate_selector.isEnabled()
        assert section._plate_selector.count() == 2

    def test_get_selected_plate(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can get currently selected plate."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_available_plates(["FG01", "BG01"])
        section._plate_selector.setCurrentIndex(0)

        assert section.get_selected_plate() == "FG01"

    def test_get_options_includes_plate(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """get_options includes selected plate."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_available_plates(["FG01"])
        section._plate_selector.setCurrentIndex(0)

        options = section.get_options()
        assert options["selected_plate"] == "FG01"

    def test_no_plate_selector_when_disabled(self, qtbot: QtBot) -> None:
        """No plate selector when has_plate_selector is False."""
        config = DCCConfig(
            name="test",
            display_name="Test",
            color="#333333",  # Must be 6-digit hex for color parsing
            shortcut="T",
            has_plate_selector=False,
        )
        section = DCCSection(config)
        qtbot.addWidget(section)

        assert section._plate_selector is None


class TestDCCSectionVersionInfo:
    """Tests for version info display."""

    def test_set_version_info(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can set version info."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section.set_version_info("v005", "21m ago")
        process_qt_events()

        assert section._version_label.isVisible()
        assert "v005" in section._version_label.text()
        assert "21m" in section._version_label.text()

    def test_version_info_hidden_when_none(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Version label hidden when version is None."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section.set_version_info(None)
        process_qt_events()

        assert not section._version_label.isVisible()

    def test_version_info_without_age(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can set version without age."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section.set_version_info("v005")
        process_qt_events()

        assert section._version_label.isVisible()
        assert "v005" in section._version_label.text()


class TestDCCSectionEnableDisable:
    """Tests for enable/disable functionality."""

    def test_set_enabled(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Can enable/disable the section."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_enabled(True)
        assert section._launch_btn.isEnabled()

        section.set_enabled(False)
        assert not section._launch_btn.isEnabled()

    def test_enabled_state_preserved_during_launch(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Enabled state restored after launch completes."""
        section = DCCSection(threede_config)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        # Click launch - button temporarily disabled
        qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
        process_qt_events()

        # Simulate reset after launch
        section._reset_button_state()

        # Should be re-enabled
        assert section._launch_btn.isEnabled()
