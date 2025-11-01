"""Tests for LauncherManager business logic layer.

Note: These unit tests mock the subprocess layer and test the launcher manager's
high-level logic. The actual process execution (using LauncherWorker with DEVNULL
for all apps) is not tested here. All applications are now treated uniformly as
GUI apps with proper process isolation.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject

from launcher_manager import (
    CustomLauncher,
    LauncherConfig,
    LauncherEnvironment,
    LauncherManager,
    LauncherTerminal,
    LauncherValidation,
)
from shot_model import Shot


class TestCustomLauncher(unittest.TestCase):
    """Test CustomLauncher data class."""

    def test_launcher_creation(self):
        """Test basic launcher creation."""
        launcher = CustomLauncher(
            id="test-id",
            name="Test Launcher",
            description="Test description",
            command="echo hello",
        )

        self.assertEqual(launcher.id, "test-id")
        self.assertEqual(launcher.name, "Test Launcher")
        self.assertEqual(launcher.command, "echo hello")
        self.assertEqual(launcher.category, "custom")
        self.assertIsInstance(launcher.environment, LauncherEnvironment)
        self.assertIsInstance(launcher.terminal, LauncherTerminal)
        self.assertIsInstance(launcher.validation, LauncherValidation)

    def test_launcher_serialization(self):
        """Test launcher to/from dict conversion."""
        launcher = CustomLauncher(
            id="test-id",
            name="Test Launcher",
            description="Test description",
            command="echo hello",
            variables={"var1": "value1"},
        )

        # Test to_dict
        data = launcher.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["name"], "Test Launcher")
        self.assertEqual(data["command"], "echo hello")
        self.assertEqual(data["variables"]["var1"], "value1")

        # Test from_dict
        restored = CustomLauncher.from_dict(data)
        self.assertEqual(restored.name, launcher.name)
        self.assertEqual(restored.command, launcher.command)
        self.assertEqual(restored.variables, launcher.variables)


class TestLauncherConfig(unittest.TestCase):
    """Test LauncherConfig persistence layer."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.config = LauncherConfig()
        self.config.config_dir = Path(self.test_dir)
        self.config.config_file = self.config.config_dir / "custom_launchers.json"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_config_dir_creation(self):
        """Test configuration directory creation."""
        self.assertTrue(self.config.config_dir.exists())

    def test_empty_config_load(self):
        """Test loading when no config file exists."""
        launchers = self.config.load_launchers()
        self.assertEqual(launchers, {})

    def test_save_and_load_launchers(self):
        """Test saving and loading launchers."""
        # Create test launchers
        launcher1 = CustomLauncher(
            id="launcher1",
            name="Test Launcher 1",
            description="First test launcher",
            command="echo test1",
        )
        launcher2 = CustomLauncher(
            id="launcher2",
            name="Test Launcher 2",
            description="Second test launcher",
            command="echo test2",
            category="testing",
        )

        launchers = {"launcher1": launcher1, "launcher2": launcher2}

        # Save launchers
        success = self.config.save_launchers(launchers)
        self.assertTrue(success)
        self.assertTrue(self.config.config_file.exists())

        # Load launchers
        loaded_launchers = self.config.load_launchers()
        self.assertEqual(len(loaded_launchers), 2)
        self.assertIn("launcher1", loaded_launchers)
        self.assertIn("launcher2", loaded_launchers)

        # Verify data
        loaded1 = loaded_launchers["launcher1"]
        self.assertEqual(loaded1.name, "Test Launcher 1")
        self.assertEqual(loaded1.command, "echo test1")
        self.assertEqual(loaded1.category, "custom")

        loaded2 = loaded_launchers["launcher2"]
        self.assertEqual(loaded2.name, "Test Launcher 2")
        self.assertEqual(loaded2.category, "testing")

    def test_invalid_json_handling(self):
        """Test handling of invalid JSON config."""
        # Create invalid JSON file
        with open(self.config.config_file, "w") as f:
            f.write("invalid json content")

        launchers = self.config.load_launchers()
        self.assertEqual(launchers, {})


class TestLauncherManager(unittest.TestCase):
    """Test LauncherManager business logic."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()

        # Mock the config to use test directory
        with patch("launcher_manager.LauncherConfig") as mock_config_class:
            mock_config = Mock()
            mock_config.load_launchers.return_value = {}
            mock_config.save_launchers.return_value = True
            mock_config_class.return_value = mock_config

            self.manager = LauncherManager()
            self.manager.config = mock_config

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_manager_initialization(self):
        """Test manager initialization."""
        self.assertIsInstance(self.manager, QObject)
        self.assertEqual(len(self.manager._launchers), 0)

    def test_create_launcher_success(self):
        """Test successful launcher creation."""
        # Connect signal to capture emissions
        signals_received = []
        self.manager.launcher_added.connect(
            lambda x: signals_received.append(("added", x))
        )
        self.manager.launchers_changed.connect(
            lambda: signals_received.append(("changed",))
        )

        launcher_id = self.manager.create_launcher(
            name="Test Launcher", command="echo hello", description="Test description"
        )

        self.assertIsNotNone(launcher_id)
        self.assertIn(launcher_id, self.manager._launchers)

        launcher = self.manager._launchers[launcher_id]
        self.assertEqual(launcher.name, "Test Launcher")
        self.assertEqual(launcher.command, "echo hello")
        self.assertEqual(launcher.description, "Test description")

        # Check signals were emitted
        self.assertEqual(len(signals_received), 2)
        self.assertIn(("added", launcher_id), signals_received)
        self.assertIn(("changed",), signals_received)

    def test_create_launcher_validation_errors(self):
        """Test launcher creation with validation errors."""
        # Connect error signal
        errors_received = []
        self.manager.validation_error.connect(
            lambda field, msg: errors_received.append((field, msg))
        )

        # Test empty name
        launcher_id = self.manager.create_launcher(name="", command="echo hello")
        self.assertIsNone(launcher_id)
        self.assertTrue(
            any("Name cannot be empty" in msg for _, msg in errors_received)
        )

        # Clear errors
        errors_received.clear()

        # Test empty command
        launcher_id = self.manager.create_launcher(name="Test", command="")
        self.assertIsNone(launcher_id)
        self.assertTrue(
            any("Command cannot be empty" in msg for _, msg in errors_received)
        )

    def test_create_launcher_duplicate_name(self):
        """Test launcher creation with duplicate name."""
        # Create first launcher
        launcher_id1 = self.manager.create_launcher(
            name="Test Launcher", command="echo 1"
        )
        self.assertIsNotNone(launcher_id1)

        # Connect error signal
        errors_received = []
        self.manager.validation_error.connect(
            lambda field, msg: errors_received.append((field, msg))
        )

        # Try to create second launcher with same name
        launcher_id2 = self.manager.create_launcher(
            name="Test Launcher", command="echo 2"
        )
        self.assertIsNone(launcher_id2)
        self.assertTrue(any("already exists" in msg for _, msg in errors_received))

    def test_security_validation(self):
        """Test security validation of commands."""
        errors_received = []
        self.manager.validation_error.connect(
            lambda field, msg: errors_received.append((field, msg))
        )

        # Test dangerous command
        launcher_id = self.manager.create_launcher(name="Dangerous", command="rm -rf /")
        self.assertIsNone(launcher_id)
        self.assertTrue(
            any("dangerous pattern" in msg.lower() for _, msg in errors_received)
        )

    def test_update_launcher(self):
        """Test launcher updating."""
        # Create launcher
        launcher_id = self.manager.create_launcher(
            name="Original Name", command="echo original"
        )
        self.assertIsNotNone(launcher_id)

        # Connect signals
        signals_received = []
        self.manager.launcher_updated.connect(
            lambda x: signals_received.append(("updated", x))
        )
        self.manager.launchers_changed.connect(
            lambda: signals_received.append(("changed",))
        )

        # Update launcher
        success = self.manager.update_launcher(
            launcher_id,
            name="Updated Name",
            command="echo updated",
            description="Updated description",
        )
        self.assertTrue(success)

        # Verify updates
        launcher = self.manager._launchers[launcher_id]
        self.assertEqual(launcher.name, "Updated Name")
        self.assertEqual(launcher.command, "echo updated")
        self.assertEqual(launcher.description, "Updated description")

        # Check signals
        self.assertEqual(len(signals_received), 2)
        self.assertIn(("updated", launcher_id), signals_received)
        self.assertIn(("changed",), signals_received)

    def test_update_nonexistent_launcher(self):
        """Test updating non-existent launcher."""
        errors_received = []
        self.manager.validation_error.connect(
            lambda field, msg: errors_received.append((field, msg))
        )

        success = self.manager.update_launcher("nonexistent", name="New Name")
        self.assertFalse(success)
        self.assertTrue(any("not found" in msg for _, msg in errors_received))

    def test_delete_launcher(self):
        """Test launcher deletion."""
        # Create launcher
        launcher_id = self.manager.create_launcher(
            name="To Delete", command="echo delete"
        )
        self.assertIsNotNone(launcher_id)

        # Connect signals
        signals_received = []
        self.manager.launcher_deleted.connect(
            lambda x: signals_received.append(("deleted", x))
        )
        self.manager.launchers_changed.connect(
            lambda: signals_received.append(("changed",))
        )

        # Delete launcher
        success = self.manager.delete_launcher(launcher_id)
        self.assertTrue(success)

        # Verify deletion
        self.assertNotIn(launcher_id, self.manager._launchers)

        # Check signals
        self.assertEqual(len(signals_received), 2)
        self.assertIn(("deleted", launcher_id), signals_received)
        self.assertIn(("changed",), signals_received)

    def test_get_launcher(self):
        """Test launcher retrieval."""
        # Create launcher
        launcher_id = self.manager.create_launcher(name="Test Get", command="echo get")
        self.assertIsNotNone(launcher_id)

        # Get launcher
        launcher = self.manager.get_launcher(launcher_id)
        self.assertIsNotNone(launcher)
        self.assertEqual(launcher.name, "Test Get")

        # Get non-existent launcher
        nonexistent = self.manager.get_launcher("nonexistent")
        self.assertIsNone(nonexistent)

    def test_list_launchers(self):
        """Test launcher listing."""
        # Create launchers with different categories
        self.manager.create_launcher(
            name="Launcher 1", command="echo 1", category="cat1"
        )
        self.manager.create_launcher(
            name="Launcher 2", command="echo 2", category="cat2"
        )
        self.manager.create_launcher(
            name="Launcher 3", command="echo 3", category="cat1"
        )

        # List all launchers
        all_launchers = self.manager.list_launchers()
        self.assertEqual(len(all_launchers), 3)

        # List by category
        cat1_launchers = self.manager.list_launchers(category="cat1")
        self.assertEqual(len(cat1_launchers), 2)

        cat2_launchers = self.manager.list_launchers(category="cat2")
        self.assertEqual(len(cat2_launchers), 1)

    def test_get_categories(self):
        """Test category listing."""
        # Initially no categories
        categories = self.manager.get_categories()
        self.assertEqual(categories, [])

        # Create launchers with categories
        self.manager.create_launcher(name="L1", command="echo 1", category="alpha")
        self.manager.create_launcher(name="L2", command="echo 2", category="beta")
        self.manager.create_launcher(name="L3", command="echo 3", category="alpha")

        categories = self.manager.get_categories()
        self.assertEqual(sorted(categories), ["alpha", "beta"])

    def test_variable_substitution(self):
        """Test variable substitution functionality."""
        # Test basic substitution
        result = self.manager._substitute_variables(
            "Hello $name!", custom_vars={"name": "World"}
        )
        self.assertEqual(result, "Hello World!")

        # Test shot context substitution
        shot = Shot(
            show="testshow",
            sequence="testseq",
            shot="001",
            workspace_path="/shows/testshow/shots/testseq/001",
        )

        result = self.manager._substitute_variables(
            "Shot: ${show}_${sequence}_$shot at $workspace_path", shot=shot
        )
        expected = "Shot: testshow_testseq_001 at /shows/testshow/shots/testseq/001"
        self.assertEqual(result, expected)

        # Test safe substitution with missing variables
        result = self.manager._substitute_variables(
            "Missing: $missing_var", custom_vars={"other": "value"}
        )
        self.assertEqual(result, "Missing: $missing_var")

    def test_execute_launcher(self):
        """Test launcher execution using worker thread."""
        # Create launcher
        launcher_id = self.manager.create_launcher(
            name="Test Execute",
            command="echo $message",
            variables={"message": "hello world"},
        )

        # Connect signals
        signals_received = []
        self.manager.execution_started.connect(
            lambda x: signals_received.append(("started", x))
        )
        self.manager.execution_finished.connect(
            lambda x, success: signals_received.append(("finished", x, success))
        )

        # Execute launcher (will use worker thread)
        with patch.object(
            self.manager, "_execute_with_worker", return_value=True
        ) as mock_worker:
            success = self.manager.execute_launcher(launcher_id)
            self.assertTrue(success)

            # Verify worker was called with correct arguments
            mock_worker.assert_called_once()
            args = mock_worker.call_args[0]
            self.assertEqual(args[0], launcher_id)
            self.assertEqual(args[1], "Test Execute")
            self.assertIn("echo hello world", args[2])

        # Check signal was emitted
        self.assertIn(("started", launcher_id), signals_received)

    @patch("os.chdir")
    @patch("os.getcwd")
    def test_execute_in_shot_context(self, mock_getcwd, mock_chdir):
        """Test launcher execution in shot context using worker thread."""
        # Setup mocks
        mock_getcwd.return_value = "/original/dir"

        # Create launcher
        launcher_id = self.manager.create_launcher(
            name="Shot Context Test", command="echo $full_name"
        )

        # Create shot
        shot = Shot(
            show="testshow",
            sequence="testseq",
            shot="001",
            workspace_path="/shows/testshow/shots/testseq/001",
        )

        # Mock workspace path validation and worker execution
        with patch(
            "launcher_manager.PathUtils.validate_path_exists", return_value=True
        ):
            with patch.object(
                self.manager, "_execute_with_worker", return_value=True
            ) as mock_worker:
                success = self.manager.execute_in_shot_context(launcher_id, shot)
                self.assertTrue(success)

                # Verify worker was called with correct arguments
                mock_worker.assert_called_once()
                args = mock_worker.call_args[0]
                self.assertEqual(args[0], launcher_id)
                self.assertEqual(args[1], "Shot Context Test")
                # Check that variable substitution happened
                self.assertIn("testseq_001", args[2])  # Variable substituted
                self.assertIn(
                    "ws /shows/testshow/shots/testseq/001", args[2]
                )  # ws command
                self.assertEqual(args[3], shot.workspace_path)  # Working directory

        # Verify directory change
        mock_chdir.assert_any_call(shot.workspace_path)
        mock_chdir.assert_any_call("/original/dir")  # Restored

    def test_dry_run_execution(self):
        """Test dry run execution."""
        launcher_id = self.manager.create_launcher(
            name="Dry Run Test", command="echo test"
        )

        # Execute with dry_run=True - should not actually execute
        with patch("subprocess.Popen") as mock_popen:
            success = self.manager.execute_launcher(launcher_id, dry_run=True)
            self.assertTrue(success)
            mock_popen.assert_not_called()

    def test_validate_launcher_paths(self):
        """Test launcher path validation."""
        # Create launcher with required files
        launcher_id = self.manager.create_launcher(
            name="Path Test",
            command="echo test",
            validation=LauncherValidation(
                check_executable=True, required_files=["/path/to/required/file.txt"]
            ),
        )

        # Mock path validation to return False (file doesn't exist)
        with patch(
            "launcher_manager.PathUtils.validate_path_exists", return_value=False
        ):
            errors = self.manager.validate_launcher_paths(launcher_id)
            self.assertTrue(len(errors) > 0)
            self.assertTrue(any("Required file not found" in error for error in errors))

    def test_reload_config(self):
        """Test configuration reloading."""
        # Mock successful reload
        with patch.object(self.manager, "_load_launchers") as mock_load:
            signals_received = []
            self.manager.launchers_changed.connect(
                lambda: signals_received.append("changed")
            )

            success = self.manager.reload_config()
            self.assertTrue(success)
            mock_load.assert_called_once()
            self.assertIn("changed", signals_received)


if __name__ == "__main__":
    unittest.main()
