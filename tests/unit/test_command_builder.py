"""Tests for CommandBuilder component.

This test suite provides comprehensive coverage of command building:
- Path validation and security
- Workspace command wrapping
- Rez environment wrapping
- Nuke environment fixes
- Logging redirection
- Full command assembly
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from launch.command_builder import CommandBuilder


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object with default settings."""
    config = MagicMock(spec=Config)
    config.NUKE_SKIP_PROBLEMATIC_PLUGINS = True
    config.NUKE_OCIO_FALLBACK_CONFIG = "/path/to/ocio/config.ocio"
    return config


class TestPathValidation:
    """Tests for path validation and security."""

    def test_valid_simple_path(self) -> None:
        """Test validation of simple path without special characters."""
        path = "/home/user/project/file.txt"
        result = CommandBuilder.validate_path(path)
        # shlex.quote only adds quotes when needed (spaces/special chars)
        # For simple paths, it returns as-is
        assert result == "/home/user/project/file.txt"

    def test_valid_path_with_spaces(self) -> None:
        """Test validation of path with spaces."""
        path = "/home/user/My Documents/file.txt"
        result = CommandBuilder.validate_path(path)
        # shlex.quote adds single quotes and escapes internal quotes
        assert "My Documents" in result

    def test_valid_path_with_single_quote(self) -> None:
        """Test validation of path with single quote (properly escaped)."""
        path = "/home/user/It's a file.txt"
        result = CommandBuilder.validate_path(path)
        # shlex.quote should escape the single quote
        assert result == "'/home/user/It'\"'\"'s a file.txt'"

    def test_command_separator_semicolon_rejected(self) -> None:
        """Test rejection of path with semicolon (command separator)."""
        path = "/home/user/file.txt; rm -rf /"
        with pytest.raises(ValueError, match=r"dangerous character.*;"):
            CommandBuilder.validate_path(path)

    def test_command_separator_and_rejected(self) -> None:
        """Test rejection of path with && (AND operator)."""
        path = "/home/user/file.txt && malicious"
        with pytest.raises(ValueError, match=r"dangerous character.*&&"):
            CommandBuilder.validate_path(path)

    def test_command_separator_or_rejected(self) -> None:
        """Test rejection of path with || (OR operator)."""
        path = "/home/user/file.txt || malicious"
        with pytest.raises(ValueError, match=r"dangerous character.*\|\|"):
            CommandBuilder.validate_path(path)

    def test_command_separator_pipe_rejected(self) -> None:
        """Test rejection of path with | (pipe)."""
        path = "/home/user/file.txt | cat"
        with pytest.raises(ValueError, match=r"dangerous character.*\|"):
            CommandBuilder.validate_path(path)

    def test_output_redirection_rejected(self) -> None:
        """Test rejection of path with > (output redirection)."""
        path = "/home/user/file.txt > /tmp/output"
        with pytest.raises(ValueError, match=r"dangerous character.*>"):
            CommandBuilder.validate_path(path)

    def test_input_redirection_rejected(self) -> None:
        """Test rejection of path with < (input redirection)."""
        path = "/home/user/file.txt < /tmp/input"
        with pytest.raises(ValueError, match=r"dangerous character.*<"):
            CommandBuilder.validate_path(path)

    def test_append_redirection_rejected(self) -> None:
        """Test rejection of path with >> (append redirection)."""
        path = "/home/user/file.txt >> /tmp/log"
        with pytest.raises(ValueError, match=r"dangerous character.*>>"):
            CommandBuilder.validate_path(path)

    def test_command_substitution_backtick_rejected(self) -> None:
        """Test rejection of path with backtick (command substitution)."""
        path = "/home/user/`malicious`.txt"
        with pytest.raises(ValueError, match=r"dangerous character.*`"):
            CommandBuilder.validate_path(path)

    def test_command_substitution_dollar_paren_rejected(self) -> None:
        """Test rejection of path with $( (command substitution)."""
        path = "/home/user/$(malicious).txt"
        with pytest.raises(ValueError, match=r"dangerous character.*\$\("):
            CommandBuilder.validate_path(path)

    def test_newline_rejected(self) -> None:
        """Test rejection of path with newline character."""
        path = "/home/user/file.txt\nmalicious"
        with pytest.raises(ValueError, match="dangerous character"):
            CommandBuilder.validate_path(path)

    def test_carriage_return_rejected(self) -> None:
        """Test rejection of path with carriage return character."""
        path = "/home/user/file.txt\rmalicious"
        with pytest.raises(ValueError, match="dangerous character"):
            CommandBuilder.validate_path(path)

    def test_variable_expansion_rejected(self) -> None:
        """Test rejection of path with ${ (variable expansion)."""
        path = "/home/user/${MALICIOUS}.txt"
        with pytest.raises(ValueError, match=r"dangerous character.*\$\{"):
            CommandBuilder.validate_path(path)

    def test_arithmetic_expansion_rejected(self) -> None:
        """Test rejection of path with $(( (arithmetic expansion)."""
        path = "/home/user/$((malicious)).txt"
        with pytest.raises(ValueError, match=r"dangerous character.*\$\(\("):
            CommandBuilder.validate_path(path)

    def test_path_with_dotdot_normalizes_safely(self) -> None:
        """Test that paths with .. normalize correctly (VFX pipeline use case)."""
        # VFX pipelines often have paths like /mnt/project/../archive
        # These should normalize safely to /mnt/archive
        path = "/home/user/project/../file.txt"
        result = CommandBuilder.validate_path(path)
        # Path is normalized (.. is resolved)
        assert "file.txt" in result
        assert ".." not in result  # .. is resolved by normalization
        # shlex.quote adds quotes only if needed (e.g., for spaces)
        # Simple paths like /home/user/file.txt don't need quotes
        assert "/home/user/file.txt" in result or "'/home/user/file.txt'" in result

    def test_path_with_dot_normalizes_safely(self) -> None:
        """Test that paths with . normalize correctly."""
        path = "/home/user/./file.txt"
        result = CommandBuilder.validate_path(path)
        assert "file.txt" in result
        # shlex.quote adds quotes only if needed
        assert "/home/user/file.txt" in result or "'/home/user/file.txt'" in result

    def test_path_with_dots_in_dirname_allowed(self) -> None:
        """Test that paths with dots in directory names are allowed (e.g., v2.5)."""
        path = "/projects/v2.5/scenes/shot.nk"
        result = CommandBuilder.validate_path(path)
        assert "v2.5" in result
        assert "shot.nk" in result

    def test_empty_path_rejected(self) -> None:
        """Test that empty paths are rejected."""
        with pytest.raises(ValueError, match="empty"):
            CommandBuilder.validate_path("")

    def test_path_resolve_uses_strict_false(self) -> None:
        """Test that path resolution uses strict=False for NFS safety.

        Using strict=False prevents Path.resolve() from hanging on stale NFS mounts
        or inaccessible paths. The path is resolved lexically without accessing the
        filesystem for parts that don't exist.
        """
        # Non-existent path should still resolve without error
        # (strict=False means it won't try to access the filesystem)
        nonexistent_path = "/nonexistent/path/to/file.txt"
        result = CommandBuilder.validate_path(nonexistent_path)
        # Should return the normalized path without error
        assert "file.txt" in result
        assert nonexistent_path in result or f"'{nonexistent_path}'" in result


class TestWorkspaceCommand:
    """Tests for workspace command building."""

    def test_workspace_command_simple(self) -> None:
        """Test building workspace command with simple paths."""
        workspace = "'/workspace/path'"
        app_command = "nuke"
        result = CommandBuilder.build_workspace_command(workspace, app_command)
        assert result == "ws '/workspace/path' && nuke"

    def test_workspace_command_with_env_fixes(self) -> None:
        """Test building workspace command with environment fixes."""
        workspace = "'/workspace/path'"
        app_command = "NUKE_CRASH_REPORTS=0 && nuke"
        result = CommandBuilder.build_workspace_command(workspace, app_command)
        assert result == "ws '/workspace/path' && NUKE_CRASH_REPORTS=0 && nuke"


class TestRezWrapping:
    """Tests for Rez environment wrapping."""

    def test_rez_wrap_single_package(self) -> None:
        """Test wrapping command with single Rez package."""
        command = "nuke"
        packages = ["nuke"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        # shlex.quote('nuke') returns 'nuke' (no quotes needed for simple strings)
        assert result == "rez env nuke -- bash -ilc nuke"

    def test_rez_wrap_multiple_packages(self) -> None:
        """Test wrapping command with multiple Rez packages."""
        command = "nuke"
        packages = ["nuke", "nuke-plugins", "ocio"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        assert result == "rez env nuke nuke-plugins ocio -- bash -ilc nuke"

    def test_rez_wrap_preserves_complex_command(self) -> None:
        """Test that Rez wrapping preserves complex commands."""
        command = "ws /workspace && NUKE_CRASH_REPORTS=0 && nuke"
        packages = ["nuke"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        # shlex.quote() wraps complex commands with special chars in single quotes
        assert result == "rez env nuke -- bash -ilc 'ws /workspace && NUKE_CRASH_REPORTS=0 && nuke'"

    def test_rez_wrap_escapes_double_quotes(self) -> None:
        """Test that Rez wrapping properly escapes commands with double quotes.

        This is a critical security/correctness fix. Without proper escaping,
        commands like 'nuke -F "Template"' would break the shell parsing.
        """
        command = 'nuke -F "ShotBot Template"'
        packages = ["nuke"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        # shlex.quote() wraps in single quotes to preserve internal double quotes
        assert result == "rez env nuke -- bash -ilc 'nuke -F \"ShotBot Template\"'"

    def test_rez_wrap_escapes_single_quotes(self) -> None:
        """Test that Rez wrapping handles commands with single quotes."""
        command = "nuke -m \"It's working\""
        packages = ["nuke"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        # shlex.quote() escapes single quotes inside the command
        assert "It" in result
        assert "working" in result

    def test_rez_wrap_handles_mixed_quotes_and_special_chars(self) -> None:
        """Test complex command with quotes, spaces, and special characters."""
        command = 'maya -command "loadPlugin(\'shotbot\')" -file "/path/with spaces/scene.ma"'
        packages = ["maya"]
        result = CommandBuilder.wrap_with_rez(command, packages)
        # Verify the command is properly quoted
        assert "rez env maya -- bash -ilc" in result
        # Verify command is preserved (exact format depends on shlex.quote implementation)
        assert "loadPlugin" in result
        assert "shotbot" in result


class TestNukeEnvironmentFixes:
    """Tests for Nuke-specific environment fixes."""

    def test_all_fixes_enabled(self, mock_config: MagicMock) -> None:
        """Test with all Nuke fixes enabled."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = True
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/path/to/config.ocio"

        result = CommandBuilder.apply_nuke_environment_fixes(command, mock_config)

        # Should contain NUKE_PATH filtering using case statement approach
        assert "NUKE_PATH=$(" in result
        assert "case" in result
        assert "problematic_plugins" in result

        # Should contain OCIO fallback (shlex.quote only adds quotes if needed)
        assert "OCIO=/path/to/config.ocio" in result

        # Should disable crash reports
        assert "NUKE_CRASH_REPORTS=0" in result

        # Original command should be at the end
        assert result.endswith("&& nuke")

    def test_only_crash_reporting_disabled(self, mock_config: MagicMock) -> None:
        """Test with only crash reporting disabled (minimal fixes)."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ""

        result = CommandBuilder.apply_nuke_environment_fixes(command, mock_config)

        # Should only contain crash reporting disable
        assert result == "NUKE_CRASH_REPORTS=0 && nuke"

    def test_plugin_filtering_only(self, mock_config: MagicMock) -> None:
        """Test with only plugin filtering enabled."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = True
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ""

        result = CommandBuilder.apply_nuke_environment_fixes(command, mock_config)

        # Should contain NUKE_PATH filtering (case statement approach) and crash reporting
        assert "NUKE_PATH=$(" in result
        assert "case" in result
        assert "problematic_plugins" in result
        assert "NUKE_CRASH_REPORTS=0" in result
        assert "OCIO=" not in result

    def test_ocio_fallback_only(self, mock_config: MagicMock) -> None:
        """Test with only OCIO fallback enabled."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/custom/ocio.ocio"

        result = CommandBuilder.apply_nuke_environment_fixes(command, mock_config)

        # Should contain OCIO (shlex.quote only adds quotes if needed)
        assert "OCIO=/custom/ocio.ocio" in result
        assert "NUKE_CRASH_REPORTS=0" in result
        assert "NUKE_PATH" not in result

    def test_ocio_path_with_spaces(self, mock_config: MagicMock) -> None:
        """Test OCIO path with spaces is properly quoted."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/path/with spaces/my config.ocio"

        result = CommandBuilder.apply_nuke_environment_fixes(command, mock_config)

        # Path with spaces must be properly quoted to prevent shell word splitting
        # shlex.quote adds single quotes around paths containing spaces
        assert "OCIO='/path/with spaces/my config.ocio'" in result

    def test_fix_summary_all_enabled(self, mock_config: MagicMock) -> None:
        """Test fix summary with all fixes enabled."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = True
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/path/to/config.ocio"

        summary = CommandBuilder.get_nuke_fix_summary(mock_config)

        assert "runtime NUKE_PATH filtering" in summary
        assert "OCIO fallback" in summary
        assert "crash reporting disabled" in summary
        assert len(summary) == 3

    def test_fix_summary_minimal(self, mock_config: MagicMock) -> None:
        """Test fix summary with minimal fixes."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ""

        summary = CommandBuilder.get_nuke_fix_summary(mock_config)

        assert "crash reporting disabled" in summary
        assert len(summary) == 1


class TestLoggingRedirection:
    """Tests for logging redirection."""

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.home")
    def test_logging_added_successfully(
        self, mock_home: MagicMock, mock_mkdir: MagicMock
    ) -> None:
        """Test that logging redirection is added successfully."""
        mock_home.return_value = Path("/home/user")
        command = "nuke"

        result = CommandBuilder.add_logging(command)

        assert result.startswith("nuke 2>&1 | tee -a ")
        assert ".shotbot/logs/dispatcher.out" in result
        mock_mkdir.assert_called_once()

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.home")
    def test_logging_graceful_degradation_on_oserror(
        self, mock_home: MagicMock, mock_mkdir: MagicMock
    ) -> None:
        """Test graceful degradation when logging directory creation fails."""
        mock_home.return_value = Path("/home/user")
        mock_mkdir.side_effect = OSError("Permission denied")
        command = "nuke"

        result = CommandBuilder.add_logging(command)

        # Should return original command without logging
        assert result == "nuke"

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.home")
    def test_logging_graceful_degradation_on_permission_error(
        self, mock_home: MagicMock, mock_mkdir: MagicMock
    ) -> None:
        """Test graceful degradation when permission is denied."""
        mock_home.return_value = Path("/home/user")
        mock_mkdir.side_effect = PermissionError("Access denied")
        command = "nuke"

        result = CommandBuilder.add_logging(command)

        # Should return original command without logging
        assert result == "nuke"

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.home")
    def test_logging_handles_spaces_in_path(
        self, mock_home: MagicMock, mock_mkdir: MagicMock
    ) -> None:
        """Test that logging handles spaces in log file path."""
        mock_home.return_value = Path("/home/user with spaces")
        command = "nuke"

        result = CommandBuilder.add_logging(command)

        # Path should be quoted
        assert "'/home/user with spaces" in result or '"/home/user with spaces' in result


class TestFullCommandAssembly:
    """Tests for full command assembly."""

    def test_minimal_command(self, mock_config: MagicMock) -> None:
        """Test building minimal command (app only)."""
        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace=None,
            config=mock_config,
            rez_packages=None,
            apply_nuke_fixes=False,
            add_logging_redirect=False,
        )
        assert result == "nuke"

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.home")
    def test_full_command_with_all_features(
        self,
        mock_home: MagicMock,
        mock_mkdir: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test building command with all features enabled."""
        mock_home.return_value = Path("/home/user")
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = True
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/path/to/config.ocio"

        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace="'/workspace/path'",
            config=mock_config,
            rez_packages=["nuke", "nuke-plugins"],
            apply_nuke_fixes=True,
            add_logging_redirect=True,
        )

        # Should contain all transformations in order:
        # 1. Nuke fixes
        assert "NUKE_PATH" in result or "NUKE_CRASH_REPORTS=0" in result

        # 2. Workspace (may be quoted differently by shlex.quote)
        assert "ws" in result
        assert "workspace/path" in result

        # 3. Rez wrapping
        assert "rez env nuke nuke-plugins -- bash -ilc" in result

        # 4. Logging
        assert "tee -a" in result

    def test_command_with_workspace_only(self, mock_config: MagicMock) -> None:
        """Test building command with workspace only."""
        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace="'/workspace/path'",
            config=mock_config,
            rez_packages=None,
            apply_nuke_fixes=False,
            add_logging_redirect=False,
        )
        assert result == "ws '/workspace/path' && nuke"

    def test_command_with_rez_only(self, mock_config: MagicMock) -> None:
        """Test building command with Rez only."""
        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace=None,
            config=mock_config,
            rez_packages=["nuke"],
            apply_nuke_fixes=False,
            add_logging_redirect=False,
        )
        # shlex.quote() doesn't add quotes for simple strings without special chars
        assert result == "rez env nuke -- bash -ilc nuke"

    def test_command_with_nuke_fixes_only(self, mock_config: MagicMock) -> None:
        """Test building command with Nuke fixes only."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ""

        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace=None,
            config=mock_config,
            rez_packages=None,
            apply_nuke_fixes=True,
            add_logging_redirect=False,
        )
        assert result == "NUKE_CRASH_REPORTS=0 && nuke"

    def test_transformation_order(self, mock_config: MagicMock) -> None:
        """Test that transformations are applied in correct order."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ""

        result = CommandBuilder.build_full_command(
            app_command="nuke",
            workspace="'/ws'",
            config=mock_config,
            rez_packages=["nuke"],
            apply_nuke_fixes=True,
            add_logging_redirect=False,
        )

        # Order should be: fixes -> workspace -> rez
        # shlex.quote() wraps complex commands with special chars in single quotes
        assert result.startswith("rez env nuke -- bash -ilc")
        # Then workspace
        assert "ws" in result
        assert "/ws" in result
        # Then original command with Nuke fixes
        assert "NUKE_CRASH_REPORTS=0" in result
        assert "nuke" in result


class TestBackgroundWrapping:
    """Tests for background process wrapping."""

    def test_wrap_for_background_simple_command(self) -> None:
        """Test wrapping a simple command for background execution."""
        result = CommandBuilder.wrap_for_background("nuke")
        assert result == "(nuke) & disown; exit"

    def test_wrap_for_background_complex_command(self) -> None:
        """Test wrapping a complex command with workspace and pipes."""
        command = "ws '/shows/test/shots/sq010/sh0010' && nuke 2>&1 | tee /tmp/log.txt"
        result = CommandBuilder.wrap_for_background(command)
        assert result == f"({command}) & disown; exit"

    def test_wrap_for_background_preserves_inner_command(self) -> None:
        """Test that the inner command is preserved exactly."""
        command = "echo 'test with spaces' && python script.py"
        result = CommandBuilder.wrap_for_background(command)
        # Should wrap in subshell without modifying the command
        assert command in result
        assert result.startswith("(")
        assert result.endswith(") & disown; exit")
