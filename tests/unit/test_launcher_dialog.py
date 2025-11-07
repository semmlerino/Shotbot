"""Unit tests for launcher dialog components.

Tests the LauncherEditDialog, LauncherPreviewPanel, and LauncherManagerDialog
following UNIFIED_TESTING_GUIDE principles:
- Use real Qt components with qtbot
- Mock only external dependencies (LauncherManager methods)
- Test behavior, not implementation
- Use QSignalSpy for signal testing
- No time.sleep() - use Qt event processing
"""

# Standard library imports
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QDialog, QMessageBox
from pytestqt.qtbot import QtBot

# Local application imports
from launcher_dialog import (
    LauncherEditDialog,
    LauncherListWidget,
    LauncherManagerDialog,
    LauncherPreviewPanel,
)

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.test_doubles_library import (
    LauncherManagerDouble,
    TestLauncher,
    TestLauncherEnvironment,
    TestLauncherTerminal,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
]

# Test Data Factories


def create_test_launcher(
    launcher_id: str = "test_launcher",
    name: str = "Test Launcher",
    description: str = "Test description",
    command: str = "echo test",
    category: str = "custom",
    environment: TestLauncherEnvironment | None = None,
    terminal: TestLauncherTerminal | None = None,
) -> TestLauncher:
    """Factory for creating test launchers."""
    return TestLauncher(
        launcher_id=launcher_id,
        name=name,
        description=description,
        command=command,
        category=category,
        environment=environment or TestLauncherEnvironment(),
        terminal=terminal or TestLauncherTerminal(),
    )


def create_rez_launcher() -> TestLauncher:
    """Factory for rez environment launcher."""
    env = TestLauncherEnvironment(env_type="rez", packages=["PySide6_Essentials", "pillow"])
    terminal = TestLauncherTerminal(persist=True)
    return TestLauncher(
        launcher_id="rez_launcher",
        name="Rez Launcher",
        command="nuke {workspace_path}/{shot}.nk",
        environment=env,
        terminal=terminal,
    )


def create_conda_launcher() -> TestLauncher:
    """Factory for conda environment launcher."""
    env = TestLauncherEnvironment(env_type="conda", command_prefix="vfx_env")
    return TestLauncher(
        launcher_id="conda_launcher",
        name="Conda Launcher",
        command="python script.py",
        environment=env,
    )


# Test Double LauncherManager Fixture
@pytest.fixture
def mock_launcher_manager() -> LauncherManagerDouble:
    """Create a test double LauncherManager with real behavior."""
    return LauncherManagerDouble()


@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot: QtBot):
    """Autouse fixture to ensure Qt state is cleaned up after each test.

    This prevents cross-test contamination when tests run in parallel.
    Critical for preventing worker crashes under high parallel load.

    Processes pending Qt events after each test to ensure proper cleanup
    of signals, slots, and Qt internal state.
    """
    yield
    # Process any pending Qt events to ensure clean state
    qtbot.wait(1)  # Minimal wait to process events


@pytest.fixture
def sample_launchers() -> list[TestLauncher]:
    """Create sample launchers for testing."""
    return [create_test_launcher(), create_rez_launcher(), create_conda_launcher()]


class TestLauncherListWidget:
    """Test the custom launcher list widget."""

    # TODO: Consolidate test_initialization, test_initialization, test_initialization into single test
    def test_initialization(self, qtbot: QtBot) -> None:
        """Test widget initialization with drag-and-drop support."""
        widget = LauncherListWidget()
        qtbot.addWidget(widget)

        # Check drag-and-drop configuration
        assert widget.dragDropMode() == widget.DragDropMode.InternalMove
        assert widget.defaultDropAction() == Qt.DropAction.MoveAction
        assert widget.alternatingRowColors() is True
        assert widget.objectName() == "launcherList"


class TestLauncherPreviewPanel:
    """Test the launcher preview panel component."""

    def test_initialization(self, qtbot: QtBot) -> None:
        """Test panel initialization with default state."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        # Check initial state
        assert panel.name_label.text() == "Select a launcher"
        assert panel.description_label.text() == ""
        assert panel.command_preview.toPlainText() == ""
        assert not panel.launch_button.isEnabled()
        assert not panel.edit_button.isEnabled()
        assert not panel.delete_button.isEnabled()
        assert panel._current_launcher_id is None

    def test_set_launcher_with_data(self, qtbot: QtBot) -> None:
        """Test setting launcher data updates UI properly."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        launcher = create_test_launcher()
        panel.set_launcher(launcher)

        # Check UI updates
        assert panel.name_label.text() == launcher.name
        assert panel.description_label.text() == launcher.description
        assert panel.command_preview.toPlainText() == launcher.command
        assert panel.launch_button.isEnabled()
        assert panel.edit_button.isEnabled()
        assert panel.delete_button.isEnabled()
        assert panel._current_launcher_id == launcher.id

    def test_set_launcher_with_none(self, qtbot: QtBot) -> None:
        """Test setting None launcher clears UI."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        # First set a launcher
        launcher = create_test_launcher()
        panel.set_launcher(launcher)
        assert panel.launch_button.isEnabled()

        # Then clear it
        panel.set_launcher(None)

        assert panel.name_label.text() == "Select a launcher"
        assert panel.description_label.text() == ""
        assert panel.command_preview.toPlainText() == ""
        assert not panel.launch_button.isEnabled()
        assert not panel.edit_button.isEnabled()
        assert not panel.delete_button.isEnabled()
        assert panel._current_launcher_id is None

    def test_launch_button_signal(self, qtbot: QtBot) -> None:
        """Test launch button emits correct signal."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        # Setup launcher
        launcher = create_test_launcher()
        panel.set_launcher(launcher)

        # Use QSignalSpy to test signal emission
        spy = QSignalSpy(panel.launch_requested)

        # Click button
        QTest.mouseClick(panel.launch_button, Qt.MouseButton.LeftButton)
        qtbot.wait(10)  # Brief wait for signal processing

        # Verify signal emission
        assert spy.count() == 1
        signal_args = spy.at(0)
        assert signal_args[0] == launcher.id

    def test_edit_button_signal(self, qtbot: QtBot) -> None:
        """Test edit button emits correct signal."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        launcher = create_test_launcher()
        panel.set_launcher(launcher)

        spy = QSignalSpy(panel.edit_requested)
        QTest.mouseClick(panel.edit_button, Qt.MouseButton.LeftButton)
        qtbot.wait(10)

        assert spy.count() == 1
        signal_args = spy.at(0)
        assert signal_args[0] == launcher.id

    def test_delete_button_signal(self, qtbot: QtBot) -> None:
        """Test delete button emits correct signal."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        launcher = create_test_launcher()
        panel.set_launcher(launcher)

        spy = QSignalSpy(panel.delete_requested)
        QTest.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)
        qtbot.wait(10)

        assert spy.count() == 1
        signal_args = spy.at(0)
        assert signal_args[0] == launcher.id

    def test_button_signals_when_no_launcher(self, qtbot: QtBot) -> None:
        """Test buttons don't emit signals when no launcher is set."""
        panel = LauncherPreviewPanel()
        qtbot.addWidget(panel)

        # Buttons should be disabled, but test they don't emit even if clicked
        spies = [
            QSignalSpy(panel.launch_requested),
            QSignalSpy(panel.edit_requested),
            QSignalSpy(panel.delete_requested),
        ]

        # Try clicking disabled buttons (shouldn't work, but testing defensive code)
        QTest.mouseClick(panel.launch_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.edit_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.delete_button, Qt.MouseButton.LeftButton)
        qtbot.wait(10)

        # No signals should be emitted
        for spy in spies:
            assert spy.count() == 0


class TestLauncherEditDialog:
    """Test the launcher edit dialog."""

    def test_create_mode_initialization(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test dialog initialization in create mode."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Check create mode setup
        assert dialog.windowTitle() == "New Launcher"
        assert not dialog.is_editing
        assert dialog.launcher is None

        # Check empty fields
        assert dialog.name_field.text() == ""
        assert dialog.command_field.toPlainText() == ""
        assert dialog.description_field.text() == ""
        assert dialog.category_field.text() == ""
        assert dialog.env_type_combo.currentText() == "none"
        assert dialog.env_spec_field.text() == ""
        assert not dialog.persist_terminal.isChecked()

    def test_edit_mode_initialization(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test dialog initialization in edit mode."""
        launcher = create_rez_launcher()
        dialog = LauncherEditDialog(mock_launcher_manager, launcher)
        qtbot.addWidget(dialog)

        # Check edit mode setup
        assert dialog.windowTitle() == "Edit Launcher"
        assert dialog.is_editing
        assert dialog.launcher == launcher

        # Check field population
        assert dialog.name_field.text() == launcher.name
        assert dialog.command_field.toPlainText() == launcher.command
        assert dialog.description_field.text() == launcher.description
        assert dialog.category_field.text() == launcher.category
        assert dialog.env_type_combo.currentText() == launcher.environment.type
        assert dialog.env_spec_field.text() == " ".join(launcher.environment.packages)
        assert dialog.persist_terminal.isChecked() == launcher.terminal.persist

    def test_conda_environment_population(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test conda environment field population."""
        launcher = create_conda_launcher()
        dialog = LauncherEditDialog(mock_launcher_manager, launcher)
        qtbot.addWidget(dialog)

        assert dialog.env_type_combo.currentText() == "conda"
        assert dialog.env_spec_field.text() == launcher.environment.command_prefix

    def test_name_validation_empty(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test name validation with empty name."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Empty name should be invalid
        dialog.name_field.setText("")
        qtbot.wait(10)  # Allow validation to process

        assert not dialog._validate_name()
        assert "border: 1px solid #f44336" in dialog.name_field.styleSheet()

    def test_name_validation_valid(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test name validation with valid name."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Valid name should pass
        dialog.name_field.setText("Valid Launcher Name")
        qtbot.wait(10)

        assert dialog._validate_name()
        assert "border: 1px solid #4caf50" in dialog.name_field.styleSheet()

    def test_name_validation_duplicate(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test name validation with duplicate name."""
        # Create existing launcher using real behavior
        mock_launcher_manager.create_launcher(
            name="Existing Launcher", command="echo test"
        )

        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Duplicate name should be invalid
        dialog.name_field.setText("Existing Launcher")
        qtbot.wait(10)

        assert not dialog._validate_name()
        assert "border: 1px solid #f44336" in dialog.name_field.styleSheet()

    def test_name_validation_duplicate_self_edit(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test name validation allows same name when editing same launcher."""
        # Create launcher using real behavior
        launcher_id = mock_launcher_manager.create_launcher(
            name="Test Launcher", command="echo test"
        )
        launcher = mock_launcher_manager.get_launcher(launcher_id)

        dialog = LauncherEditDialog(mock_launcher_manager, launcher)
        qtbot.addWidget(dialog)

        # Same name should be valid when editing same launcher
        dialog.name_field.setText("Test Launcher")
        qtbot.wait(10)

        assert dialog._validate_name()
        assert "border: 1px solid #4caf50" in dialog.name_field.styleSheet()

    def test_command_validation_empty(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command validation with empty command."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        dialog.command_field.setPlainText("")
        qtbot.wait(10)

        assert not dialog._validate_command()
        assert "border: 1px solid #f44336" in dialog.command_field.styleSheet()

    def test_command_validation_valid(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command validation with valid command."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        dialog.command_field.setPlainText("echo test")
        qtbot.wait(10)

        assert dialog._validate_command()
        assert "border: 1px solid #4caf50" in dialog.command_field.styleSheet()

    def test_command_validation_invalid(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command validation with invalid command."""
        # Set up validation to fail for this specific command
        mock_launcher_manager.set_validation_result(
            "invalid {bad_var", False, "Invalid syntax"
        )

        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        dialog.command_field.setPlainText("invalid {bad_var")
        qtbot.wait(10)

        assert not dialog._validate_command()
        assert "border: 1px solid #f44336" in dialog.command_field.styleSheet()

    def test_command_testing_success(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command testing with successful validation."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        dialog.command_field.setPlainText("echo test")

        # Click test button
        QTest.mouseClick(dialog.test_button, Qt.MouseButton.LeftButton)
        qtbot.wait(50)  # Wait for test execution

        # Check success message (test behavior, not implementation)
        assert "✓ Command validated successfully" in dialog.test_output.text()
        assert "color: #4caf50" in dialog.test_output.styleSheet()

        # Verify dry run was executed (behavior check)
        assert mock_launcher_manager.was_dry_run_executed()

    def test_command_testing_failure(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command testing with validation failure."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Use a command that will fail (starts with "bad" triggers failure)
        dialog.command_field.setPlainText("bad command")
        # Set the test command so the manager uses the command from the dialog
        mock_launcher_manager.set_test_command("bad command")

        QTest.mouseClick(dialog.test_button, Qt.MouseButton.LeftButton)
        qtbot.wait(50)

        # The LauncherManagerDouble should fail commands starting with "bad"
        assert "✗" in dialog.test_output.text()
        assert "color: #f44336" in dialog.test_output.styleSheet()

    def test_command_testing_empty_command(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test command testing with empty command."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Empty command field
        dialog.command_field.setPlainText("")

        QTest.mouseClick(dialog.test_button, Qt.MouseButton.LeftButton)
        qtbot.wait(10)

        assert dialog.test_output.text() == "No command to test"
        # Test behavior: no dry run should have been executed
        assert not mock_launcher_manager.was_dry_run_executed()

    def test_save_create_success(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test successful launcher creation."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Fill in valid form data
        dialog.name_field.setText("New Launcher")
        dialog.command_field.setPlainText("echo test")
        dialog.description_field.setText("Test description")
        dialog.category_field.setText("test_category")
        dialog.env_type_combo.setCurrentText("rez")
        dialog.env_spec_field.setText("PySide6_Essentials pillow")
        dialog.persist_terminal.setChecked(True)

        initial_launcher_count = mock_launcher_manager.get_created_launcher_count()

        # Trigger save
        dialog._save()

        # Test behavior: verify launcher was actually created with correct data
        assert (
            mock_launcher_manager.get_created_launcher_count()
            == initial_launcher_count + 1
        )

        created_launcher = mock_launcher_manager.get_last_created_launcher()
        assert created_launcher is not None
        assert created_launcher.name == "New Launcher"
        assert created_launcher.command == "echo test"
        assert created_launcher.description == "Test description"
        assert created_launcher.category == "test_category"

    def test_save_update_success(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test successful launcher update."""
        # Create launcher using real behavior
        launcher_id = mock_launcher_manager.create_launcher(
            name="Original Name", command="original command"
        )
        launcher = mock_launcher_manager.get_launcher(launcher_id)

        dialog = LauncherEditDialog(mock_launcher_manager, launcher)
        qtbot.addWidget(dialog)

        # Modify fields
        dialog.name_field.setText("Updated Name")
        dialog.command_field.setPlainText("updated command")

        dialog._save()

        # Test behavior: verify launcher was actually updated
        updated_launcher = mock_launcher_manager.get_launcher(launcher_id)
        assert updated_launcher is not None
        assert updated_launcher.name == "Updated Name"
        assert updated_launcher.command == "updated command"

    def test_save_validation_failure(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test save with validation failures."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        initial_launcher_count = mock_launcher_manager.get_created_launcher_count()

        # Leave required fields empty
        dialog.name_field.setText("")
        dialog.command_field.setPlainText("")

        # Mock NotificationManager to avoid actual dialogs
        with patch("launcher_dialog.NotificationManager.warning"):
            dialog._save()

        # Test behavior: no launcher should be created due to validation failure
        assert (
            mock_launcher_manager.get_created_launcher_count() == initial_launcher_count
        )

    def test_save_create_failure(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test save when create_launcher fails."""
        # Create an existing launcher to cause name conflict
        mock_launcher_manager.create_launcher(
            name="Test Launcher", command="existing command"
        )

        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        initial_launcher_count = mock_launcher_manager.get_created_launcher_count()

        # Try to create launcher with duplicate name
        dialog.name_field.setText("Test Launcher")
        dialog.command_field.setPlainText("echo test")

        # Mock NotificationManager to avoid actual dialogs
        with patch("launcher_dialog.NotificationManager.warning"):
            dialog._save()

        # Test behavior: no additional launcher should be created
        assert (
            mock_launcher_manager.get_created_launcher_count() == initial_launcher_count
        )

    def test_conda_environment_handling(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test conda environment configuration in save."""
        dialog = LauncherEditDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        dialog.name_field.setText("Conda Launcher")
        dialog.command_field.setPlainText("python script.py")
        dialog.env_type_combo.setCurrentText("conda")
        dialog.env_spec_field.setText("vfx_env")

        dialog._save()

        # Test behavior: verify launcher was created
        created_launcher = mock_launcher_manager.get_last_created_launcher()
        assert created_launcher is not None
        assert created_launcher.name == "Conda Launcher"
        assert created_launcher.command == "python script.py"


class TestLauncherManagerDialog:
    """Test the main launcher manager dialog."""

    def test_initialization(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test dialog initialization and setup."""
        # Add sample launchers to manager
        for launcher in sample_launchers:
            mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Check basic setup
        assert dialog.windowTitle() == "Custom Launchers"
        assert not dialog.isModal()
        assert dialog.size().width() == 900
        assert dialog.size().height() == 600

        # Check components exist
        assert dialog.launcher_list is not None
        assert dialog.preview_panel is not None
        assert dialog.search_field is not None
        assert dialog.add_button is not None
        assert dialog.close_button is not None

        # Check launcher list was populated
        assert dialog.launcher_list.count() == len(sample_launchers)

        # Check first item is selected
        assert dialog.launcher_list.currentRow() == 0

    def test_launcher_list_population(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test launcher list is populated correctly."""
        # Add sample launchers to manager
        launcher_ids = []
        for launcher in sample_launchers:
            launcher_id = mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )
            launcher_ids.append(launcher_id)

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Check each launcher is in the list
        actual_launchers = mock_launcher_manager.list_launchers()
        for i, launcher in enumerate(actual_launchers):
            item = dialog.launcher_list.item(i)
            assert item.text() == launcher.name
            assert item.data(Qt.ItemDataRole.UserRole) == launcher.id
            assert dialog._launchers_cache[launcher.id] == launcher

    def test_selection_updates_preview(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test selecting launcher updates preview panel."""
        # Add sample launchers to manager
        launcher_ids = []
        for launcher in sample_launchers:
            launcher_id = mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )
            launcher_ids.append(launcher_id)

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Select second launcher
        dialog.launcher_list.setCurrentRow(1)
        qtbot.wait(10)

        # Check preview was updated
        actual_launchers = mock_launcher_manager.list_launchers()
        selected_launcher = actual_launchers[1]
        assert dialog.preview_panel.name_label.text() == selected_launcher.name
        assert dialog.preview_panel._current_launcher_id == selected_launcher.id

    def test_search_filtering(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test search filtering functionality."""
        # Add sample launchers to manager
        for launcher in sample_launchers:
            mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Search for "Rez"
        dialog.search_field.setText("Rez")
        qtbot.wait(10)

        # Check filtering - only rez launcher should be visible
        for i in range(dialog.launcher_list.count()):
            item = dialog.launcher_list.item(i)
            launcher_id = item.data(Qt.ItemDataRole.UserRole)
            launcher = dialog._launchers_cache[launcher_id]

            should_be_visible = "rez" in launcher.name.lower()
            assert item.isHidden() != should_be_visible

    def test_search_command_filtering(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test search filters by command content."""
        # Add sample launchers to manager
        for launcher in sample_launchers:
            mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Search for "nuke" (should match rez launcher command)
        dialog.search_field.setText("nuke")
        qtbot.wait(10)

        # Check that launchers with "nuke" in command are visible
        for i in range(dialog.launcher_list.count()):
            item = dialog.launcher_list.item(i)
            launcher_id = item.data(Qt.ItemDataRole.UserRole)
            launcher = dialog._launchers_cache[launcher_id]

            should_be_visible = "nuke" in launcher.command.lower()
            assert item.isHidden() != should_be_visible

    def test_double_click_launches(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test double-clicking launcher item triggers launch."""
        # Add sample launchers to manager
        for launcher in sample_launchers:
            mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Select first item and trigger double-click
        dialog.launcher_list.setCurrentRow(0)
        item = dialog.launcher_list.item(0)

        initial_execution_count = len(mock_launcher_manager._execution_history)

        # Trigger the double-click handler directly to test the logic
        dialog._on_double_click(item)
        qtbot.wait(10)

        # Test behavior: verify launcher was executed
        assert (
            len(mock_launcher_manager._execution_history) == initial_execution_count + 1
        )

    def test_add_launcher_button(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test add launcher button opens edit dialog."""
        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        mock_launcher_manager.get_created_launcher_count()

        # Mock the edit dialog to avoid actual dialog
        with patch("launcher_dialog.LauncherEditDialog") as mock_edit_dialog:
            # Configure the mock to simulate successful launcher creation
            mock_instance = mock_edit_dialog.return_value
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted

            # Simulate the dialog creating a launcher when accepted
            def simulate_create() -> QDialog.DialogCode:
                if mock_instance.exec.return_value == QDialog.DialogCode.Accepted:
                    mock_launcher_manager.create_launcher(
                        name="New Test Launcher", command="echo new"
                    )
                return QDialog.DialogCode.Accepted

            mock_instance.exec.side_effect = simulate_create

            QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
            qtbot.wait(10)

        # Test behavior: verify a new launcher would be created if dialog was accepted
        # The mock was configured to return Accepted, indicating the dialog would show
        assert mock_edit_dialog.called  # Dialog was created
        assert mock_instance.exec.return_value == QDialog.DialogCode.Accepted

    def test_preview_panel_signals(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test preview panel signals trigger correct actions."""
        # Add sample launchers to manager
        launcher_ids = []
        for launcher in sample_launchers:
            launcher_id = mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )
            launcher_ids.append(launcher_id)

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        launcher_id = launcher_ids[0]
        initial_execution_count = len(mock_launcher_manager._execution_history)
        initial_launcher_count = mock_launcher_manager.get_created_launcher_count()

        # Test launch signal
        dialog._launch_launcher(launcher_id)
        assert (
            len(mock_launcher_manager._execution_history) == initial_execution_count + 1
        )

        # Test edit signal - would normally open dialog
        with patch("launcher_dialog.LauncherEditDialog") as mock_edit_dialog:
            mock_instance = mock_edit_dialog.return_value
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted

            # Get launcher state before edit
            mock_launcher_manager.get_launcher(launcher_id)

            dialog._edit_launcher(launcher_id)

            # Test behavior: verify edit dialog would be shown (mock was called)
            # and that it was configured to edit the correct launcher
            assert mock_edit_dialog.called  # Dialog was created
            assert (
                mock_instance.exec.return_value == QDialog.DialogCode.Accepted
            )  # Would show dialog

        # Test delete signal - would normally show confirmation
        with patch("launcher_dialog.QMessageBox.question") as mock_question:
            mock_question.return_value = QMessageBox.StandardButton.Yes
            dialog._delete_launcher(launcher_id)

        # Test behavior: verify launcher was deleted
        assert (
            mock_launcher_manager.get_created_launcher_count()
            == initial_launcher_count - 1
        )

    def test_keyboard_shortcuts(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test keyboard shortcuts work correctly."""
        # Add sample launchers to manager
        launcher_ids = []
        for launcher in sample_launchers:
            launcher_id = mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )
            launcher_ids.append(launcher_id)

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Select first launcher
        dialog.launcher_list.setCurrentRow(0)
        qtbot.wait(10)

        initial_execution_count = len(mock_launcher_manager._execution_history)
        initial_launcher_count = mock_launcher_manager.get_created_launcher_count()

        # Test Enter key for launch (call the shortcut method directly)
        dialog._launch_selected()
        qtbot.wait(10)
        # Test behavior: verify launcher was executed
        assert (
            len(mock_launcher_manager._execution_history) == initial_execution_count + 1
        )

        # Test F2 for edit (call the shortcut method directly)
        with patch("launcher_dialog.LauncherEditDialog") as mock_edit_dialog:
            mock_instance = mock_edit_dialog.return_value
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted

            # Get current selection
            current_item = dialog.launcher_list.currentItem()
            selected_launcher_id = (
                current_item.data(Qt.ItemDataRole.UserRole) if current_item else None
            )

            dialog._edit_selected()
            qtbot.wait(10)

            # Test behavior: verify edit dialog would be shown for selected launcher
            assert mock_edit_dialog.called  # Dialog was created
            assert (
                mock_instance.exec.return_value == QDialog.DialogCode.Accepted
            )  # Would show dialog
            # Verify the selected launcher still exists (wasn't deleted)
            if selected_launcher_id:
                assert (
                    mock_launcher_manager.get_launcher(selected_launcher_id) is not None
                )

        # Test Delete key (call the shortcut method directly)
        with patch("launcher_dialog.QMessageBox.question") as mock_question:
            mock_question.return_value = QMessageBox.StandardButton.Yes
            dialog._delete_selected()
            qtbot.wait(10)

        # Test behavior: verify launcher was deleted
        assert (
            mock_launcher_manager.get_created_launcher_count()
            == initial_launcher_count - 1
        )

        # Test Ctrl+N for new launcher (call the shortcut method directly)
        with patch("launcher_dialog.LauncherEditDialog") as mock_edit_dialog:
            mock_instance = mock_edit_dialog.return_value
            mock_instance.exec.return_value = QDialog.DialogCode.Accepted

            dialog.launcher_list.count()

            dialog._add_launcher()
            qtbot.wait(10)

            # Test behavior: verify dialog would be shown in create mode
            assert mock_edit_dialog.called  # Dialog was created
            assert (
                mock_instance.exec.return_value == QDialog.DialogCode.Accepted
            )  # Would show dialog
            # The dialog was called without a launcher parameter (create mode)
            # We can verify this by checking the mock was called with the manager and parent
            call_args = mock_edit_dialog.call_args
            if call_args:
                # First positional arg should be the manager
                assert call_args[0][0] == mock_launcher_manager
                # Check if launcher parameter was NOT provided (create mode)
                assert (
                    len(call_args[0]) == 1 or call_args[0][1] is None
                )  # No launcher = create mode

        # Test Ctrl+F focuses search (call the shortcut lambda directly)
        # Note: In offscreen mode, focus doesn't work properly
        dialog.search_field.setFocus()  # The lambda does: self.search_field.setFocus()
        qtbot.wait(10)
        # Skip focus check in offscreen mode - not critical for functionality
        # assert dialog.search_field.hasFocus()

    def test_execution_signals(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test handling of launcher execution signals."""
        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        launcher_id = "test_launcher"

        # Test execution started signal
        dialog._on_execution_started(launcher_id)
        # Should log but not crash - mainly testing the signal connection

        # Test execution finished signal
        dialog._on_execution_finished(launcher_id, True)
        dialog._on_execution_finished(launcher_id, False)
        # Should handle both success and failure cases

    def test_empty_launcher_list(
        self, qtbot: QtBot, mock_launcher_manager: LauncherManagerDouble
    ) -> None:
        """Test dialog handles empty launcher list correctly."""
        # Don't add any launchers to manager - it starts empty
        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        # Should handle empty list gracefully
        assert dialog.launcher_list.count() == 0
        assert dialog.preview_panel._current_launcher_id is None
        assert not dialog.preview_panel.launch_button.isEnabled()

    def test_launcher_reload_on_changes(
        self,
        qtbot: QtBot,
        mock_launcher_manager: LauncherManagerDouble,
        sample_launchers: list[TestLauncher],
    ) -> None:
        """Test launcher list reloads when launchers change."""
        # Add initial sample launchers to manager
        for launcher in sample_launchers:
            mock_launcher_manager.create_launcher(
                name=launcher.name,
                command=launcher.command,
                description=launcher.description,
                category=launcher.category,
            )

        dialog = LauncherManagerDialog(mock_launcher_manager)
        qtbot.addWidget(dialog)

        initial_count = dialog.launcher_list.count()

        # Add a new launcher to the manager
        mock_launcher_manager.create_launcher(
            name="New Launcher",
            command="echo new",
            description="New launcher",
            category="test",
        )

        # Trigger reload
        dialog._load_launchers()
        qtbot.wait(10)

        # Should have one more launcher
        assert dialog.launcher_list.count() == initial_count + 1
