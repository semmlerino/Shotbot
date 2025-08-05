"""Tests for terminal_launcher.py"""

from unittest.mock import Mock, patch

from PySide6.QtCore import QObject

from terminal_launcher import Launcher, LaunchResult, TerminalLauncher


class TestLauncher:
    """Test the Launcher dataclass."""

    def test_launcher_creation(self):
        """Test basic launcher creation."""
        launcher = Launcher(
            name="Test Launcher",
            command="echo 'hello world'",
            description="A test launcher",
            category="test",
        )

        assert launcher.name == "Test Launcher"
        assert launcher.command == "echo 'hello world'"
        assert launcher.description == "A test launcher"
        assert launcher.category == "test"
        assert launcher.working_directory is None
        assert launcher.environment_vars is None
        assert launcher.terminal_title is None
        assert launcher.terminal_geometry is None
        assert launcher.persist_terminal is False
        assert launcher.timeout_seconds == 30
        assert launcher.validate_command is True

    def test_launcher_with_optional_params(self):
        """Test launcher with optional parameters."""
        env_vars = {"TEST_VAR": "test_value"}
        launcher = Launcher(
            name="Advanced Launcher",
            command="my_command",
            working_directory="/tmp",
            environment_vars=env_vars,
            terminal_title="Test Terminal",
            terminal_geometry="80x24+100+100",
            persist_terminal=True,
            timeout_seconds=60,
            validate_command=False,
        )

        assert launcher.working_directory == "/tmp"
        assert launcher.environment_vars == env_vars
        assert launcher.terminal_title == "Test Terminal"
        assert launcher.terminal_geometry == "80x24+100+100"
        assert launcher.persist_terminal is True
        assert launcher.timeout_seconds == 60
        assert launcher.validate_command is False


class TestLaunchResult:
    """Test the LaunchResult dataclass."""

    def test_launch_result_success(self):
        """Test successful launch result."""
        result = LaunchResult(
            success=True,
            command="echo test",
            process_id=12345,
            terminal_type="gnome-terminal",
        )

        assert result.success is True
        assert result.command == "echo test"
        assert result.process_id == 12345
        assert result.error_message == ""
        assert result.terminal_type == "gnome-terminal"

    def test_launch_result_failure(self):
        """Test failed launch result."""
        result = LaunchResult(
            success=False, command="invalid_command", error_message="Command not found"
        )

        assert result.success is False
        assert result.command == "invalid_command"
        assert result.process_id is None
        assert result.error_message == "Command not found"
        assert result.terminal_type == ""


class TestTerminalLauncher:
    """Test the TerminalLauncher class."""

    def test_inheritance(self):
        """Test that TerminalLauncher inherits from QObject."""
        launcher = TerminalLauncher()
        assert isinstance(launcher, QObject)

    @patch("platform.system")
    def test_platform_detection(self, mock_system):
        """Test platform detection."""
        mock_system.return_value = "Linux"
        launcher = TerminalLauncher()
        assert launcher._platform == "linux"

        mock_system.return_value = "Darwin"
        launcher = TerminalLauncher()
        assert launcher._platform == "darwin"

        mock_system.return_value = "Windows"
        launcher = TerminalLauncher()
        assert launcher._platform == "windows"

    @patch("shutil.which")
    @patch("platform.system")
    def test_linux_terminal_detection(self, mock_system, mock_which):
        """Test Linux terminal detection."""
        mock_system.return_value = "Linux"

        # Mock which to return paths for gnome-terminal and xterm
        def mock_which_side_effect(terminal):
            if terminal in ["gnome-terminal", "xterm"]:
                return f"/usr/bin/{terminal}"
            return None

        mock_which.side_effect = mock_which_side_effect

        launcher = TerminalLauncher()

        assert "gnome-terminal" in launcher._detected_terminals
        assert "xterm" in launcher._detected_terminals
        assert launcher._preferred_terminal == "gnome-terminal"

    @patch("os.path.exists")
    @patch("platform.system")
    def test_macos_terminal_detection(self, mock_system, mock_exists):
        """Test macOS terminal detection."""
        mock_system.return_value = "Darwin"

        # Mock Terminal.app exists
        def mock_exists_side_effect(path):
            return path == "/Applications/Terminal.app"

        mock_exists.side_effect = mock_exists_side_effect

        launcher = TerminalLauncher()

        assert "Terminal" in launcher._detected_terminals
        assert launcher._preferred_terminal == "Terminal"

    @patch("shutil.which")
    @patch("platform.system")
    def test_windows_terminal_detection(self, mock_system, mock_which):
        """Test Windows terminal detection."""
        mock_system.return_value = "Windows"

        def mock_which_side_effect(terminal):
            if terminal == "cmd.exe":
                return "C:\\Windows\\System32\\cmd.exe"
            return None

        mock_which.side_effect = mock_which_side_effect

        launcher = TerminalLauncher()

        assert "cmd.exe" in launcher._detected_terminals
        assert launcher._preferred_terminal == "cmd.exe"

    @patch("platform.system")
    def test_get_available_terminals(self, mock_system):
        """Test getting available terminals."""
        mock_system.return_value = "Linux"

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher = TerminalLauncher()
            launcher._detected_terminals = ["gnome-terminal", "xterm"]

            terminals = launcher.get_available_terminals()
            assert terminals == ["gnome-terminal", "xterm"]
            # Ensure we get a copy, not the original list
            assert terminals is not launcher._detected_terminals

    @patch("platform.system")
    def test_set_preferred_terminal(self, mock_system):
        """Test setting preferred terminal."""
        mock_system.return_value = "Linux"

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher = TerminalLauncher()
            launcher._detected_terminals = ["gnome-terminal", "xterm", "konsole"]
            launcher._preferred_terminal = "gnome-terminal"

            # Test setting valid terminal
            result = launcher.set_preferred_terminal("xterm")
            assert result is True
            assert launcher._preferred_terminal == "xterm"

            # Test setting invalid terminal
            result = launcher.set_preferred_terminal("invalid-terminal")
            assert result is False
            assert launcher._preferred_terminal == "xterm"  # Unchanged

    def test_substitute_variables(self):
        """Test variable substitution."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            # Test basic substitution
            result = launcher._substitute_variables(
                "echo '{user} is in {home}'",
                {"user": "testuser", "home": "/home/testuser"},
            )
            assert result == "echo 'testuser is in /home/testuser'"

            # Test built-in variables (user and home are auto-detected)
            result = launcher._substitute_variables("echo '{user} at {timestamp}'", {})
            assert "{user}" not in result
            assert "{timestamp}" not in result

            # Test missing variables (should remain unchanged)
            result = launcher._substitute_variables("echo '{missing_var}'", {})
            assert result == "echo '{missing_var}'"

    def test_validate_command(self):
        """Test command validation."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            # Test empty command
            result = launcher._validate_command("")
            assert result == "Empty command"

            # Test shell built-ins (should pass)
            result = launcher._validate_command("echo hello")
            assert result is None

            result = launcher._validate_command("cd /tmp")
            assert result is None

            # Test complex commands with pipes (should pass)
            result = launcher._validate_command("ls | grep test")
            assert result is None

            # Test non-existent executable
            with patch("shutil.which", return_value=None), patch(
                "os.path.isfile", return_value=False
            ):
                result = launcher._validate_command("nonexistent_command")
                assert "Executable not found" in result

            # Test existing executable
            with patch("shutil.which", return_value="/usr/bin/ls"):
                result = launcher._validate_command("ls -la")
                assert result is None

    @patch("subprocess.Popen")
    @patch("platform.system")
    def test_execute_in_terminal_success(self, mock_system, mock_popen):
        """Test successful terminal execution."""
        mock_system.return_value = "Linux"

        # Mock a successful process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher = TerminalLauncher()
            launcher._preferred_terminal = "gnome-terminal"

            with patch.object(
                launcher,
                "_build_terminal_command",
                return_value=["gnome-terminal", "--", "bash", "-i", "-c", "echo test"],
            ):
                result = launcher._execute_in_terminal("echo test")

                assert result.success is True
                assert result.command == "echo test"
                assert result.process_id == 12345
                assert result.terminal_type == "gnome-terminal"

    @patch("platform.system")
    def test_execute_in_terminal_no_terminal(self, mock_system):
        """Test terminal execution with no available terminal."""
        mock_system.return_value = "Linux"

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher = TerminalLauncher()
            launcher._preferred_terminal = None

            result = launcher._execute_in_terminal("echo test")

            assert result.success is False
            assert "No terminal emulator available" in result.error_message

    def test_build_gnome_terminal_command(self):
        """Test building gnome-terminal command."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            # Basic command
            result = launcher._build_gnome_terminal_command(
                "echo test", None, None, None
            )
            expected = ["gnome-terminal", "--", "bash", "-i", "-c", "echo test"]
            assert result == expected

            # With all options
            result = launcher._build_gnome_terminal_command(
                "echo test", "/tmp", "Test Title", "80x24+100+100"
            )
            expected = [
                "gnome-terminal",
                "--title",
                "Test Title",
                "--geometry",
                "80x24+100+100",
                "--working-directory",
                "/tmp",
                "--",
                "bash",
                "-i",
                "-c",
                "echo test",
            ]
            assert result == expected

    def test_build_xterm_command(self):
        """Test building xterm command."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            # Basic command
            result = launcher._build_xterm_command("echo test", None, None, None)
            expected = ["xterm", "-e", "bash", "-i", "-c", "echo test"]
            assert result == expected

            # With working directory (should be added to command)
            result = launcher._build_xterm_command(
                "echo test", "/tmp", "Test Title", "80x24+100+100"
            )
            expected = [
                "xterm",
                "-title",
                "Test Title",
                "-geometry",
                "80x24+100+100",
                "-e",
                "bash",
                "-i",
                "-c",
                "cd '/tmp' && echo test",
            ]
            assert result == expected

    def test_create_launcher_static_method(self):
        """Test static method for creating launchers."""
        launcher = TerminalLauncher.create_launcher(
            name="Test",
            command="echo test",
            description="A test",
            category="testing",
            persist_terminal=True,
        )

        assert isinstance(launcher, Launcher)
        assert launcher.name == "Test"
        assert launcher.command == "echo test"
        assert launcher.description == "A test"
        assert launcher.category == "testing"
        assert launcher.persist_terminal is True

    def test_create_shotbot_debug_launcher(self):
        """Test creating ShotBot debug launcher."""
        shotbot_path = "/path/to/shotbot.py"
        launcher = TerminalLauncher.create_shotbot_debug_launcher(shotbot_path)

        assert isinstance(launcher, Launcher)
        assert launcher.name == "ShotBot Debug"
        assert shotbot_path in launcher.command
        assert "rez env" in launcher.command
        assert "--debug" in launcher.command
        assert launcher.category == "debug"
        assert launcher.persist_terminal is True
        assert launcher.validate_command is False

    @patch("subprocess.Popen")
    @patch("platform.system")
    def test_execute_launcher_success(self, mock_system, mock_popen):
        """Test complete launcher execution."""
        mock_system.return_value = "Linux"

        # Mock successful process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher_obj = TerminalLauncher()
            launcher_obj._preferred_terminal = "gnome-terminal"

            # Create test launcher
            launcher = Launcher(
                name="Test Launcher",
                command="echo 'Hello {user}'",
                validate_command=False,  # Skip validation for test
            )

            # Mock the terminal command building
            with patch.object(
                launcher_obj,
                "_build_terminal_command",
                return_value=["gnome-terminal", "--", "bash", "-i", "-c", "echo test"],
            ):
                result = launcher_obj.execute_launcher(launcher, {"user": "testuser"})

                assert result.success is True
                assert result.process_id == 12345

    @patch("platform.system")
    def test_execute_launcher_validation_failure(self, mock_system):
        """Test launcher execution with validation failure."""
        mock_system.return_value = "Linux"

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher_obj = TerminalLauncher()

            # Create launcher with validation enabled
            launcher = Launcher(
                name="Test Launcher",
                command="nonexistent_command",
                validate_command=True,
            )

            # Mock validation to return error
            with patch.object(
                launcher_obj, "_validate_command", return_value="Command not found"
            ):
                result = launcher_obj.execute_launcher(launcher)

                assert result.success is False
                assert "Command not found" in result.error_message

    def test_get_timestamp(self):
        """Test timestamp generation."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            timestamp = launcher._get_timestamp()

            # Should be in format YYYY-MM-DD_HH-MM-SS
            assert len(timestamp) == 19
            assert timestamp[4] == "-"
            assert timestamp[7] == "-"
            assert timestamp[10] == "_"
            assert timestamp[13] == "-"
            assert timestamp[16] == "-"

    @patch("subprocess.Popen")
    @patch("platform.system")
    def test_signals_emitted(self, mock_system, mock_popen):
        """Test that signals are emitted correctly."""
        mock_system.return_value = "Linux"

        # Mock successful process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        with patch.object(TerminalLauncher, "_detect_available_terminals"):
            launcher_obj = TerminalLauncher()
            launcher_obj._preferred_terminal = "gnome-terminal"

            # Mock signal emission
            launcher_obj.launcher_executed = Mock()
            launcher_obj.launcher_failed = Mock()

            launcher = Launcher(
                name="Test Launcher", command="echo test", validate_command=False
            )

            with patch.object(
                launcher_obj,
                "_build_terminal_command",
                return_value=["gnome-terminal", "--", "bash", "-i", "-c", "echo test"],
            ):
                launcher_obj.execute_launcher(launcher)

                # Should emit success signal
                launcher_obj.launcher_executed.emit.assert_called_once()
                launcher_obj.launcher_failed.emit.assert_not_called()

                # Verify signal arguments
                args = launcher_obj.launcher_executed.emit.call_args[0]
                assert args[0] == "Test Launcher"  # launcher name
                assert args[1] == "echo test"  # command
                assert len(args[2]) == 19  # timestamp format

    @patch("platform.system")
    def test_unsupported_platform(self, mock_system):
        """Test behavior on unsupported platform."""
        mock_system.return_value = "UnknownOS"

        launcher = TerminalLauncher()

        # Should have no detected terminals
        assert len(launcher._detected_terminals) == 0
        assert launcher._preferred_terminal is None

    def test_terminal_command_building_edge_cases(self):
        """Test edge cases in terminal command building."""
        with patch("platform.system", return_value="Linux"), patch.object(
            TerminalLauncher, "_detect_available_terminals"
        ):
            launcher = TerminalLauncher()

            # Test with empty command
            result = launcher._build_gnome_terminal_command("", None, None, None)
            expected = ["gnome-terminal", "--", "bash", "-i", "-c", ""]
            assert result == expected

            # Test with special characters in title
            result = launcher._build_gnome_terminal_command(
                "echo test", None, "Title with spaces & symbols!", None
            )
            expected = [
                "gnome-terminal",
                "--title",
                "Title with spaces & symbols!",
                "--",
                "bash",
                "-i",
                "-c",
                "echo test",
            ]
            assert result == expected
