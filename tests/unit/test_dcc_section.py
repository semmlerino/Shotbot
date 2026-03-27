"""Tests for DCCSection widget."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt


# Qt tests must be grouped for parallel execution
pytestmark = [pytest.mark.unit, pytest.mark.qt]

from dcc.dcc_config import DEFAULT_DCC_CONFIGS, CheckboxConfig, DCCConfig
from dcc.dcc_section_file import FileDCCSection
from dcc.dcc_section_rv import RVSection, create_dcc_section
from dcc.scene_file import FileType, SceneFile
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


@pytest.fixture
def config_with_files() -> DCCConfig:
    """Create config for a file-based DCC."""
    return DCCConfig(
        name="test_dcc",
        display_name="Test DCC",
        color="#333333",
        shortcut="T",
        file_type=FileType.THREEDE,
    )


@pytest.fixture
def sample_scene_files() -> list:
    """Create sample scene files for testing."""
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
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)

        assert "3DEqualizer" in section._name_label.text()

    def test_no_shortcut_badge_in_header(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Section header no longer displays shortcut badge (removed for cleaner UI)."""
        section = FileDCCSection(threede_config)
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
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)

        assert not section._launch_btn.isEnabled()


class TestDCCSectionLaunch:
    """Tests for launch functionality."""

    def test_launch_emits_signal_with_options(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Launch button click emits signal with options."""
        section = FileDCCSection(threede_config)
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
        section = FileDCCSection(threede_config)
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

    def test_checkboxes_state(self, qtbot: QtBot, nuke_config: DCCConfig) -> None:
        """Checkboxes are created with correct defaults and states are readable."""
        section = FileDCCSection(nuke_config)
        qtbot.addWidget(section)

        # Checkboxes exist
        assert "open_latest_scene" in section._checkboxes
        assert "create_new_file" in section._checkboxes

        # Defaults match config
        assert section._checkboxes["open_latest_scene"].isChecked()
        assert not section._checkboxes["create_new_file"].isChecked()

        # get_checkbox_states and get_options both reflect same state
        states = section.get_checkbox_states()
        assert states["open_latest_scene"] is True
        assert states["create_new_file"] is False

        options = section.get_options()
        assert "open_latest_scene" in options
        assert "create_new_file" in options


class TestDCCSectionPlateSelector:
    """Tests for plate selector functionality."""

    def test_plate_selector_initial_state(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Plate selector exists but is disabled until plates are set."""
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)

        assert section._plate_selector is not None
        assert not section._plate_selector.isEnabled()

    def test_set_available_plates_and_get_selected(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Setting plates enables selector and allows reading selection; get_options includes plate."""
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_available_plates(["FG01", "BG01"])

        assert section._plate_selector.isEnabled()
        assert section._plate_selector.count() == 2

        section._plate_selector.setCurrentIndex(0)
        assert section.get_selected_plate() == "FG01"

        options = section.get_options()
        assert options["selected_plate"] == "FG01"


class TestDCCSectionVersionInfo:
    """Tests for version info display."""

    @pytest.mark.parametrize(
        ("version", "age", "expect_visible", "expect_texts"),
        [
            pytest.param("v005", "21m ago", True, ["v005", "21m"], id="with_age"),
            pytest.param("v005", None, True, ["v005"], id="without_age"),
            pytest.param(None, None, False, [], id="none_hidden"),
        ],
    )
    def test_set_version_info(
        self,
        qtbot: QtBot,
        threede_config: DCCConfig,
        version: str | None,
        age: str | None,
        expect_visible: bool,
        expect_texts: list[str],
    ) -> None:
        """Version label visibility and content matches arguments."""
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        if age is not None:
            section.set_version_info(version, age)
        else:
            section.set_version_info(version)
        process_qt_events()

        assert section._version_label.isVisible() == expect_visible
        for text in expect_texts:
            assert text in section._version_label.text()


class TestDCCSectionEnableDisable:
    """Tests for enable/disable functionality."""

    def test_set_enabled(self, qtbot: QtBot, threede_config: DCCConfig) -> None:
        """Can enable/disable the section."""
        section = FileDCCSection(threede_config)
        qtbot.addWidget(section)

        section.set_enabled(True)
        assert section._launch_btn.isEnabled()

        section.set_enabled(False)
        assert not section._launch_btn.isEnabled()

    def test_enabled_state_preserved_during_launch(
        self, qtbot: QtBot, threede_config: DCCConfig
    ) -> None:
        """Enabled state restored after launch completes."""
        section = FileDCCSection(threede_config)
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

    def test_files_section_creation_and_population(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Files section initializes, populates table, and updates header count."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        # Section created with file table
        assert section._dcc_file_table is not None
        assert section._dcc_file_table._file_table is not None

        # Set files populates table and updates header
        section.set_files(sample_scene_files)
        process_qt_events()

        assert section._dcc_file_table._file_model.rowCount() == 2
        header_text = section._dcc_file_table._files_header_btn.text()
        assert "2" in header_text

    def test_get_selected_file_returns_latest(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """get_selected_file returns the selected (latest) file."""
        section = FileDCCSection(config_with_files)
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
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)

        selected = section.get_selected_file()
        assert selected is None

    def test_file_selected_signal_emitted(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """file_selected signal emitted when file is clicked."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Click the second row in the table
        with qtbot.waitSignal(section.file_selected, timeout=1000):
            index = section._dcc_file_table._file_model.index(1, 0)
            section._dcc_file_table._file_table.clicked.emit(index)
            process_qt_events()

    def test_default_configs_create_correct_types(self, qtbot: QtBot) -> None:
        """3DE, Maya, Nuke create FileDCCSection; RV creates RVSection."""
        for config in DEFAULT_DCC_CONFIGS:
            section = create_dcc_section(config)
            qtbot.addWidget(section)
            if config.name == "rv":
                assert isinstance(section, RVSection)
            else:
                assert isinstance(section, FileDCCSection)


class TestDCCSectionFileDoubleClick:
    """Tests for double-click file opening functionality."""

    def test_double_click_all_outcomes(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking a file emits launch_requested, emits file_selected, and updates selected file."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Double-click the first row — verify launch_requested emitted with correct app name
        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            index = section._dcc_file_table._file_model.index(0, 0)
            section._dcc_file_table._file_table.doubleClicked.emit(index)
            process_qt_events()

        app_name, _options = blocker.args
        assert app_name == "test_dcc"

        # Double-click the second row — verify file_selected emitted with correct file
        with qtbot.waitSignal(section.file_selected, timeout=1000) as blocker:
            index = section._dcc_file_table._file_model.index(1, 0)
            section._dcc_file_table._file_table.doubleClicked.emit(index)
            process_qt_events()

        selected_file = blocker.args[0]
        assert selected_file.version == 3

        # Verify selected file state was updated
        assert section.get_selected_file() is not None
        assert section.get_selected_file().version == 3

    def test_double_click_invalid_index_does_nothing(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Double-clicking invalid index does not emit signals."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        # Store initial state
        initial_selected = section.get_selected_file()

        # Double-click invalid row index
        from PySide6.QtCore import QModelIndex

        invalid_index = QModelIndex()  # Invalid index
        section._dcc_file_table.on_file_double_clicked(invalid_index)
        process_qt_events()

        # State should be unchanged
        assert section.get_selected_file() == initial_selected


class TestDCCSectionFileContextMenu:
    """Tests for file context menu functionality."""

    def test_context_menu_policy_set(
        self, qtbot: QtBot, config_with_files: DCCConfig
    ) -> None:
        """File table has custom context menu policy."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)

        assert (
            section._dcc_file_table._file_table.contextMenuPolicy()
            == Qt.ContextMenuPolicy.CustomContextMenu
        )

    def test_launch_file_emits_and_updates_selection(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Launching a file emits launch_requested and updates selection state."""
        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.show()
        process_qt_events()

        section.set_files(sample_scene_files)
        process_qt_events()

        file = sample_scene_files[0]

        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            section._dcc_file_table.launch_file(file)
            process_qt_events()

        app_name, _options = blocker.args
        assert app_name == "test_dcc"

        selected = section.get_selected_file()
        assert selected == file

    def test_context_menu_on_invalid_index_does_nothing(
        self, qtbot: QtBot, config_with_files: DCCConfig, sample_scene_files: list
    ) -> None:
        """Context menu request on empty area does nothing (no crash)."""
        section = FileDCCSection(config_with_files)
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
        section._dcc_file_table.show_file_context_menu(invalid_pos)
        process_qt_events()


class TestDCCSectionFileCopyPath:
    """Tests for copy file path functionality."""

    @pytest.fixture
    def sample_scene_file(self):
        """Create a sample scene file for testing."""
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
        """Copy file path sets clipboard text to file path."""
        from PySide6.QtWidgets import QApplication

        section = FileDCCSection(config_with_files)
        qtbot.addWidget(section)
        section.show()
        process_qt_events()

        section._dcc_file_table.copy_file_path(sample_scene_file)
        process_qt_events()

        clipboard = QApplication.clipboard()
        assert clipboard.text() == "/path/to/scene_v005.3de"


class TestRVSection:
    """Tests for RVSection widget."""

    @pytest.fixture
    def rv_config(self) -> DCCConfig:
        """Get the RV config from DEFAULT_DCC_CONFIGS."""
        return next(c for c in DEFAULT_DCC_CONFIGS if c.name == "rv")

    def test_rv_section_instantiation(self, qtbot: QtBot, rv_config: DCCConfig) -> None:
        """RVSection creates a sequence table unconditionally."""
        section = RVSection(rv_config)
        qtbot.addWidget(section)

        assert section._dcc_sequence_table is not None

    def test_rv_section_no_file_table(self, qtbot: QtBot, rv_config: DCCConfig) -> None:
        """RVSection does not have a _dcc_file_table attribute."""
        section = RVSection(rv_config)
        qtbot.addWidget(section)

        assert not hasattr(section, "_dcc_file_table")

    def test_rv_launch_requested_signal(
        self, qtbot: QtBot, rv_config: DCCConfig
    ) -> None:
        """Clicking the RV launch button emits launch_requested."""
        section = RVSection(rv_config)
        qtbot.addWidget(section)
        section.set_enabled(True)
        section.set_expanded(True)
        section.show()
        process_qt_events()

        with qtbot.waitSignal(section.launch_requested, timeout=1000) as blocker:
            qtbot.mouseClick(section._launch_btn, Qt.MouseButton.LeftButton)
            process_qt_events()

        app_name, _options = blocker.args
        assert app_name == "rv"


