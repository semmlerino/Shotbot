"""Unit tests for launcher panel components following UNIFIED_TESTING_GUIDE.

This test suite validates launcher panel behavior using:
- Real Qt components and signals (not mocked)
- Behavior testing, not implementation details
- Test doubles only at system boundaries
- Factory fixtures for flexible test data

Tests cover:
- AppLauncherSection widget functionality
- LauncherPanel widget functionality
- Signal emission and handling
- State management and UI updates
- Integration with shot context
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QPushButton

# Local application imports
from launcher_panel import AppConfig, AppLauncherSection, CheckboxConfig, LauncherPanel
from shot_model import Shot


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

pytestmark = [pytest.mark.unit, pytest.mark.qt]


# =============================================================================
# FACTORY FIXTURES (Modern Best Practice)
# =============================================================================


@pytest.fixture
def make_app_config() -> Callable[..., AppConfig]:
    """Factory fixture for creating AppConfig objects."""

    def _make(
        name: str = "test_app",
        command: str = "test_command",
        icon: str = "🧪",
        color: str = "#2b3e50",
        tooltip: str = "Test application",
        shortcut: str = "T",
        checkboxes: list[CheckboxConfig] | None = None,
    ) -> AppConfig:
        return AppConfig(
            name=name,
            command=command,
            icon=icon,
            color=color,
            tooltip=tooltip,
            shortcut=shortcut,
            checkboxes=checkboxes,
        )

    return _make


@pytest.fixture
def make_checkbox_config() -> Callable[..., CheckboxConfig]:
    """Factory fixture for creating CheckboxConfig objects."""

    def _make(
        label: str = "Test Option",
        tooltip: str = "Test tooltip",
        key: str = "test_option",
        default: bool = False,
    ) -> CheckboxConfig:
        return CheckboxConfig(
            label=label,
            tooltip=tooltip,
            key=key,
            default=default,
        )

    return _make


@pytest.fixture
def make_shot() -> Callable[..., Shot]:
    """Factory fixture for creating Shot objects."""

    def _make(
        show: str = "test_show",
        sequence: str = "test_seq",
        shot: str = "0010",
        workspace_path: str = "/test/path",
    ) -> Shot:
        return Shot(show, sequence, shot, workspace_path)

    return _make


# =============================================================================
# APPLAUNCHER SECTION TESTS
# =============================================================================


class TestAppLauncherSection:
    """Test AppLauncherSection widget behavior."""

    def test_initialization_basic(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test basic section initialization."""
        config = make_app_config(name="nuke", icon="🎨", color="#5d4d2b")

        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Test initialization state
        assert section.config == config
        assert section.is_expanded is True
        assert section.launch_button is not None
        assert section.launch_button.text() == "Launch nuke"
        assert not section.launch_button.isEnabled()  # Disabled until shot selected

    def test_initialization_with_checkboxes(
        self,
        qtbot: QtBot,
        make_app_config: Callable[..., AppConfig],
        make_checkbox_config: Callable[..., CheckboxConfig],
    ) -> None:
        """Test section initialization with checkboxes."""
        checkbox_configs = [
            make_checkbox_config(label="Option 1", key="opt1", default=True),
            make_checkbox_config(label="Option 2", key="opt2", default=False),
        ]
        config = make_app_config(checkboxes=checkbox_configs)

        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Test checkboxes are created
        assert len(section.checkboxes) == 2
        assert "opt1" in section.checkboxes
        assert "opt2" in section.checkboxes

        # Test initial states
        assert section.checkboxes["opt1"].isChecked() is True
        assert section.checkboxes["opt2"].isChecked() is False

    def test_launch_signal_emission(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test launch_requested signal emission."""
        config = make_app_config(name="maya")
        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Enable button for testing
        section.set_enabled(True)

        # Set up signal spy
        spy = QSignalSpy(section.launch_requested)

        # Trigger button click
        qtbot.mouseClick(section.launch_button, Qt.MouseButton.LeftButton)

        # Verify signal emission
        assert spy.count() == 1
        assert spy.at(0)[0] == "maya"

    def test_enable_disable_functionality(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test enable/disable button functionality."""
        config = make_app_config()
        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Initially disabled
        assert not section.launch_button.isEnabled()

        # Enable
        section.set_enabled(True)
        assert section.launch_button.isEnabled()

        # Disable again
        section.set_enabled(False)
        assert not section.launch_button.isEnabled()

    def test_expand_collapse_functionality(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test expand/collapse behavior."""
        config = make_app_config()
        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)
        section.show()  # Ensure widget is shown for visibility tests
        qtbot.waitExposed(section)

        # Initially expanded
        assert section.is_expanded is True
        # Note: isVisible() may be false if parent isn't shown, test the state instead
        assert section.expand_button.arrowType() == Qt.ArrowType.DownArrow

        # Collapse
        qtbot.mouseClick(section.expand_button, Qt.MouseButton.LeftButton)

        assert section.is_expanded is False
        assert section.expand_button.arrowType() == Qt.ArrowType.RightArrow

        # Expand again
        qtbot.mouseClick(section.expand_button, Qt.MouseButton.LeftButton)

        assert section.is_expanded is True
        assert section.expand_button.arrowType() == Qt.ArrowType.DownArrow

    def test_checkbox_state_retrieval(
        self,
        qtbot: QtBot,
        make_app_config: Callable[..., AppConfig],
        make_checkbox_config: Callable[..., CheckboxConfig],
    ) -> None:
        """Test checkbox state retrieval."""
        checkbox_configs = [
            make_checkbox_config(key="option_a", default=True),
            make_checkbox_config(key="option_b", default=False),
        ]
        config = make_app_config(checkboxes=checkbox_configs)
        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Test initial states
        states = section.get_checkbox_states()
        assert states["option_a"] is True
        assert states["option_b"] is False

        # Change states and test again
        section.checkboxes["option_a"].setChecked(False)
        section.checkboxes["option_b"].setChecked(True)

        states = section.get_checkbox_states()
        assert states["option_a"] is False
        assert states["option_b"] is True

    def test_color_manipulation(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test color lightening and darkening methods."""
        config = make_app_config(
            color="#808080"
        )  # Gray - can be lightened and darkened
        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Test color lightening with a color that can be lightened
        lightened = section._lighten_color("#808080")
        assert lightened != "#808080"
        assert lightened.startswith("#")

        # Test color darkening
        darkened = section._darken_color("#808080")
        assert darkened != "#808080"
        assert darkened.startswith("#")

        # Test with already bright color (won't change much when lightened)
        bright_result = section._lighten_color("#ff0000")
        assert bright_result.startswith("#")  # Should still be valid format

        # Test with invalid color
        assert section._lighten_color("invalid") == "invalid"
        assert section._darken_color("invalid") == "invalid"


# =============================================================================
# LAUNCHER PANEL TESTS
# =============================================================================


class TestLauncherPanel:
    """Test LauncherPanel widget behavior."""

    def test_initialization(self, qtbot: QtBot) -> None:
        """Test basic panel initialization."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Test initialization state
        assert panel.app_sections is not None
        assert panel.custom_launcher_buttons is not None
        assert panel._current_shot is None
        assert panel.group_box is not None
        assert panel.info_label is not None

    def test_app_sections_created(self, qtbot: QtBot) -> None:
        """Test that all app sections are created correctly."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Test expected apps are present
        expected_apps = ["3de", "nuke", "maya", "rv", "publish"]
        for app_name in expected_apps:
            assert app_name in panel.app_sections
            section = panel.app_sections[app_name]
            assert isinstance(section, AppLauncherSection)
            assert section.config.name == app_name

    def test_app_launch_signal_propagation(self, qtbot: QtBot) -> None:
        """Test that app launch signals are properly propagated."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Enable sections for testing
        panel.set_shot(Shot("test", "seq", "0010", "/test/path"))

        # Set up signal spy for panel's signal
        spy = QSignalSpy(panel.app_launch_requested)

        # Trigger launch from a section
        nuke_section = panel.app_sections["nuke"]
        qtbot.mouseClick(nuke_section.launch_button, Qt.MouseButton.LeftButton)

        # Verify signal propagation
        assert spy.count() == 1
        assert spy.at(0)[0] == "nuke"

    def test_shot_context_management(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test shot context setting and UI updates."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        shot = make_shot(show="test_show", sequence="seq01", shot="0020")

        # Initially no shot
        assert panel._current_shot is None
        assert "Select a shot" in panel.info_label.text()
        for section in panel.app_sections.values():
            assert not section.launch_button.isEnabled()

        # Set shot
        panel.set_shot(shot)

        assert panel._current_shot == shot
        assert "test_show/seq01/0020" in panel.info_label.text()
        for section in panel.app_sections.values():
            assert section.launch_button.isEnabled()

        # Clear shot
        panel.set_shot(None)

        assert panel._current_shot is None
        assert "Select a shot" in panel.info_label.text()
        for section in panel.app_sections.values():
            assert not section.launch_button.isEnabled()

    def test_checkbox_state_access(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test accessing checkbox states from specific apps."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Test getting checkbox state for nuke (which has checkboxes)
        nuke_raw_plate = panel.get_checkbox_state("nuke", "include_raw_plate")

        # Should get default value (False)
        assert nuke_raw_plate is False

        # Test getting state for non-existent app/key
        assert panel.get_checkbox_state("nonexistent", "key") is False
        assert panel.get_checkbox_state("nuke", "nonexistent") is False

    def test_custom_launcher_management(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test custom launcher CRUD operations."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        shot = make_shot()
        panel.set_shot(shot)

        # Initially no custom launchers
        assert len(panel.custom_launcher_buttons) == 0

        # Add custom launcher
        panel.add_custom_launcher("test_launcher", "Test Launcher")

        assert len(panel.custom_launcher_buttons) == 1
        assert "test_launcher" in panel.custom_launcher_buttons
        button = panel.custom_launcher_buttons["test_launcher"]
        assert isinstance(button, QPushButton)
        assert button.text() == "Test Launcher"
        assert button.isEnabled()  # Enabled because shot is set

        # Test signal emission from custom launcher
        spy = QSignalSpy(panel.custom_launcher_requested)
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert spy.count() == 1
        assert spy.at(0)[0] == "test_launcher"

        # Remove custom launcher
        panel.remove_custom_launcher("test_launcher")
        assert len(panel.custom_launcher_buttons) == 0

        # Test removing non-existent launcher (should not crash)
        panel.remove_custom_launcher("nonexistent")

    def test_update_custom_launchers(self, qtbot: QtBot) -> None:
        """Test batch updating custom launchers."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Add initial launcher
        panel.add_custom_launcher("old_launcher", "Old Launcher")
        assert len(panel.custom_launcher_buttons) == 1

        # Update with new set
        new_launchers = [
            ("launcher_1", "Launcher 1"),
            ("launcher_2", "Launcher 2"),
        ]
        panel.update_custom_launchers(new_launchers)

        # Verify old one is removed and new ones added
        assert len(panel.custom_launcher_buttons) == 2
        assert "old_launcher" not in panel.custom_launcher_buttons
        assert "launcher_1" in panel.custom_launcher_buttons
        assert "launcher_2" in panel.custom_launcher_buttons


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestLauncherPanelIntegration:
    """Test launcher panel integration scenarios."""

    @pytest.mark.integration
    def test_end_to_end_workflow(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test complete workflow from shot selection to app launch."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Set up signal spies
        app_launch_spy = QSignalSpy(panel.app_launch_requested)
        QSignalSpy(panel.custom_launcher_requested)

        # 1. Select shot
        shot = make_shot(show="big_project", sequence="epic_seq", shot="1337")
        panel.set_shot(shot)

        # 2. Configure checkboxes
        nuke_section = panel.app_sections["nuke"]
        nuke_section.checkboxes["include_raw_plate"].setChecked(True)

        # 3. Launch nuke with options
        qtbot.mouseClick(nuke_section.launch_button, Qt.MouseButton.LeftButton)

        # 4. Verify results
        assert app_launch_spy.count() == 1
        assert app_launch_spy.at(0)[0] == "nuke"

        # Verify checkbox state is accessible
        assert panel.get_checkbox_state("nuke", "include_raw_plate") is True

    @pytest.mark.integration
    def test_multiple_app_sections_interaction(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test interaction between multiple app sections."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        shot = make_shot()
        panel.set_shot(shot)

        # Set up spy
        spy = QSignalSpy(panel.app_launch_requested)

        # Launch different apps in sequence
        for app_name in ["3de", "maya", "rv"]:
            section = panel.app_sections[app_name]
            qtbot.mouseClick(section.launch_button, Qt.MouseButton.LeftButton)

        # Verify all launches were captured
        assert spy.count() == 3
        launched_apps = [spy.at(i)[0] for i in range(3)]
        assert launched_apps == ["3de", "maya", "rv"]

    @pytest.mark.integration
    def test_section_state_independence(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test that sections maintain independent state."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        shot = make_shot()
        panel.set_shot(shot)

        # Collapse one section
        section_3de = panel.app_sections["3de"]
        qtbot.mouseClick(section_3de.expand_button, Qt.MouseButton.LeftButton)

        # Verify only that section is collapsed
        assert section_3de.is_expanded is False
        for app_name, section in panel.app_sections.items():
            if app_name != "3de":
                assert section.is_expanded is True

    @pytest.mark.slow
    def test_performance_with_many_operations(
        self, qtbot: QtBot, make_shot: Callable[..., Shot]
    ) -> None:
        """Test panel performance with many rapid operations."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        shot = make_shot()

        # Rapidly set/unset shot many times
        for i in range(100):
            panel.set_shot(shot if i % 2 == 0 else None)

        # Verify final state is correct
        panel.set_shot(shot)
        for section in panel.app_sections.values():
            assert section.launch_button.isEnabled()


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestLauncherPanelErrorHandling:
    """Test error handling and edge cases."""

    def test_missing_config_properties(self, qtbot: QtBot) -> None:
        """Test handling of incomplete AppConfig objects."""
        # Create minimal config
        minimal_config = AppConfig(name="minimal", command="cmd")

        section = AppLauncherSection(minimal_config, parent=None)
        qtbot.addWidget(section)

        # Should handle gracefully with defaults
        assert section.config.icon == ""
        assert section.config.color == "#2b3e50"
        assert section.config.checkboxes is None

    def test_empty_checkbox_list(
        self, qtbot: QtBot, make_app_config: Callable[..., AppConfig]
    ) -> None:
        """Test behavior with empty checkbox list."""
        config = make_app_config(checkboxes=[])

        section = AppLauncherSection(config, parent=None)
        qtbot.addWidget(section)

        # Should handle empty list gracefully
        assert len(section.checkboxes) == 0
        states = section.get_checkbox_states()
        assert states == {}

    def test_invalid_shot_context(self, qtbot: QtBot) -> None:
        """Test handling of various shot context values."""
        panel = LauncherPanel(parent=None)
        qtbot.addWidget(panel)

        # Test None shot (should be handled gracefully)
        panel.set_shot(None)
        assert panel._current_shot is None

        # Test setting shot multiple times
        shot1 = Shot("show1", "seq1", "001", "/path1")
        shot2 = Shot("show2", "seq2", "002", "/path2")

        panel.set_shot(shot1)
        assert panel._current_shot == shot1

        panel.set_shot(shot2)
        assert panel._current_shot == shot2
