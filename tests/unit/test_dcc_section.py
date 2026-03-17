"""Tests for DCCSection widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from dcc.dcc_section import (
    DEFAULT_DCC_CONFIGS,
    CheckboxConfig,
    DCCConfig,
    DCCSection,
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



class TestDCCSectionInit:
    """Tests for DCCSection initialization."""

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


class TestDCCSectionEmbeddedFiles:
    """Tests for embedded files sub-section functionality."""

    @pytest.fixture
    def config_with_files(self) -> DCCConfig:
        """Create config with embedded files section enabled."""
        from dcc.scene_file import FileType

        return DCCConfig(
            name="test_dcc",
            display_name="Test DCC",
            color="#333333",
            shortcut="T",
            has_files_section=True,
            file_type=FileType.THREEDE,
        )

    @pytest.fixture
    def config_without_files(self) -> DCCConfig:
        """Create config with embedded files section disabled."""
        return DCCConfig(
            name="test_dcc",
            display_name="Test DCC",
            color="#333333",
            shortcut="T",
            has_files_section=False,
            file_type=None,
        )

    @pytest.fixture
    def sample_scene_files(self) -> list:
        """Create sample scene files for testing."""
        from datetime import datetime
        from pathlib import Path

        from dcc.scene_file import FileType, SceneFile

        now = datetime.now()  # noqa: DTZ005 - Match production code's naive datetime
        return [
            SceneFile(
                path=Path("/path/to/scene_v005.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist1",
                version=5,
            ),
            SceneFile(
                path=Path("/path/to/scene_v003.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist2",
                version=3,
            ),
        ]

    def test_files_section_created_when_configured(
        self, qtbot: QtBot, config_with_files: DCCConfig
    ) -> None:
        """Files sub-section created when has_files_section is True."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)

        assert section._files_section is not None
        assert section._file_table is not None

    def test_no_files_section_when_disabled(
        self, qtbot: QtBot, config_without_files: DCCConfig
    ) -> None:
        """No files section when has_files_section is False."""
        section = DCCSection(config_without_files)
        qtbot.addWidget(section)

        assert section._files_section is None
        assert section._file_table is None

    def test_set_files_populates_table(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Setting files populates the file table."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)

        section.set_files(sample_scene_files)
        process_qt_events()

        assert section._file_model is not None
        assert section._file_model.rowCount() == 2

    def test_set_files_updates_header_count(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Setting files updates the section header count."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Header button should show file count
        assert section._files_header_btn is not None
        header_text = section._files_header_btn.text()
        assert "2" in header_text

    def test_get_selected_file_returns_latest(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """get_selected_file returns the selected (latest) file."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)

        section.set_files(sample_scene_files)
        process_qt_events()

        selected = section.get_selected_file()
        # First file in list (latest) should be selected by default
        assert selected is not None
        assert selected.version == 5

    def test_get_selected_file_none_when_empty(
        self, qtbot: QtBot, config_with_files: DCCConfig
    ) -> None:
        """get_selected_file returns None when no files."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)

        selected = section.get_selected_file()
        assert selected is None

    def test_file_selected_signal_emitted(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """file_selected signal emitted when file is clicked."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Click the second row in the table
        with qtbot.waitSignal(section.file_selected, timeout=1000):
            index = section._file_model.index(1, 0)
            section._file_table.clicked.emit(index)
            process_qt_events()

    def test_default_configs_have_files_section(self, qtbot: QtBot) -> None:
        """3DE, Maya, Nuke have files sections; RV does not."""
        for config in DEFAULT_DCC_CONFIGS:
            section = DCCSection(config)
            qtbot.addWidget(section)

            if config.name == "rv":
                assert section._files_section is None
            else:
                assert section._files_section is not None


class TestDCCSectionFileDoubleClick:
    """Tests for double-click file opening functionality."""

    @pytest.fixture
    def config_with_files(self) -> DCCConfig:
        """Create config with embedded files section enabled."""
        from dcc.scene_file import FileType

        return DCCConfig(
            name="test_dcc",
            display_name="Test DCC",
            color="#333333",
            shortcut="T",
            has_files_section=True,
            file_type=FileType.THREEDE,
        )

    @pytest.fixture
    def sample_scene_files(self) -> list:
        """Create sample scene files for testing."""
        from datetime import datetime
        from pathlib import Path

        from dcc.scene_file import FileType, SceneFile

        now = datetime.now()  # noqa: DTZ005 - Match production code's naive datetime
        return [
            SceneFile(
                path=Path("/path/to/scene_v005.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist1",
                version=5,
            ),
            SceneFile(
                path=Path("/path/to/scene_v003.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist2",
                version=3,
            ),
        ]

    def test_double_click_emits_launch_requested(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking a file emits launch_requested signal."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Double-click the first row
        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            index = section._file_model.index(0, 0)
            section._file_table.doubleClicked.emit(index)
            process_qt_events()

        app_name, _options = blocker.args
        assert app_name == "test_dcc"

    def test_double_click_emits_file_selected(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking a file also emits file_selected signal."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Double-click the second row
        with qtbot.waitSignal(section.file_selected, timeout=1000) as blocker:
            index = section._file_model.index(1, 0)
            section._file_table.doubleClicked.emit(index)
            process_qt_events()

        selected_file = blocker.args[0]
        assert selected_file.version == 3

    def test_double_click_updates_selected_file(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking updates _current_selected_file."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Double-click the second row (v003)
        index = section._file_model.index(1, 0)
        section._file_table.doubleClicked.emit(index)
        process_qt_events()

        assert section._current_selected_file is not None
        assert section._current_selected_file.version == 3

    def test_double_click_invalid_index_does_nothing(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking invalid index does not emit signals."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Store initial state
        initial_selected = section._current_selected_file

        # Double-click invalid row index
        from PySide6.QtCore import QModelIndex

        invalid_index = QModelIndex()  # Invalid index
        section._on_file_double_clicked(invalid_index)
        process_qt_events()

        # State should be unchanged
        assert section._current_selected_file == initial_selected


class TestDCCSectionFileContextMenu:
    """Tests for file context menu functionality."""

    @pytest.fixture
    def config_with_files(self) -> DCCConfig:
        """Create config with embedded files section enabled."""
        from dcc.scene_file import FileType

        return DCCConfig(
            name="test_dcc",
            display_name="Test DCC",
            color="#333333",
            shortcut="T",
            has_files_section=True,
            file_type=FileType.THREEDE,
        )

    @pytest.fixture
    def sample_scene_files(self) -> list:
        """Create sample scene files for testing."""
        from datetime import datetime
        from pathlib import Path

        from dcc.scene_file import FileType, SceneFile

        now = datetime.now()  # noqa: DTZ005 - Match production code's naive datetime
        return [
            SceneFile(
                path=Path("/path/to/scene_v005.3de"),
                file_type=FileType.THREEDE,
                modified_time=now,
                user="artist1",
                version=5,
            ),
        ]

    def test_context_menu_policy_set(
        self, qtbot: QtBot, config_with_files: DCCConfig
    ) -> None:
        """File table has custom context menu policy."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)

        assert section._file_table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    def test_launch_file_emits_launch_requested(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """_launch_file method emits launch_requested signal."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        file = sample_scene_files[0]

        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            section._launch_file(file)
            process_qt_events()

        app_name, _options = blocker.args
        assert app_name == "test_dcc"

    def test_launch_file_updates_selection(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """_launch_file updates selection state before launching."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        file = sample_scene_files[0]
        section._launch_file(file)
        process_qt_events()

        assert section._current_selected_file == file

    def test_context_menu_on_invalid_index_does_nothing(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Context menu request on empty area does nothing (no crash)."""
        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Request context menu at position that doesn't correspond to a row
        from PySide6.QtCore import QPoint

        # Use a point outside valid rows (large Y value)
        invalid_pos = QPoint(10, 9999)
        # This should not raise an exception
        section._show_file_context_menu(invalid_pos)
        process_qt_events()


class TestDCCSectionFileCopyPath:
    """Tests for copy file path functionality."""

    @pytest.fixture
    def config_with_files(self) -> DCCConfig:
        """Create config with embedded files section enabled."""
        from dcc.scene_file import FileType

        return DCCConfig(
            name="test_dcc",
            display_name="Test DCC",
            color="#333333",
            shortcut="T",
            has_files_section=True,
            file_type=FileType.THREEDE,
        )

    @pytest.fixture
    def sample_scene_file(self):
        """Create a sample scene file for testing."""
        from datetime import datetime
        from pathlib import Path

        from dcc.scene_file import FileType, SceneFile

        now = datetime.now()  # noqa: DTZ005 - Match production code's naive datetime
        return SceneFile(
            path=Path("/path/to/scene_v005.3de"),
            file_type=FileType.THREEDE,
            modified_time=now,
            user="artist1",
            version=5,
        )

    def test_copy_file_path_sets_clipboard(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_file
    ) -> None:
        """_copy_file_path sets clipboard text to file path."""
        from PySide6.QtWidgets import QApplication

        section = DCCSection(config_with_files)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section._copy_file_path(sample_scene_file)
        process_qt_events()

        clipboard = QApplication.clipboard()
        assert clipboard.text() == "/path/to/scene_v005.3de"
