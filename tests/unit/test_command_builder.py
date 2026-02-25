"""Tests for CommandBuilder component.

This test suite provides comprehensive coverage of command building:
- Path validation and security
- Workspace command wrapping
- Rez environment wrapping
- Nuke environment fixes
- Logging redirection
- Full command assembly
"""

import base64
import re
import shlex
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
        """Test that logging redirection is added successfully with pipefail."""
        mock_home.return_value = Path("/home/user")
        command = "nuke"

        result = CommandBuilder.add_logging(command)

        # Result should include pipefail for exit code preservation
        assert result.startswith("set -o pipefail; nuke 2>&1 | tee -a ")
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


class TestMayaCommandMustSurviveBashParsing:
    """Test that Maya commands must survive bash -ilc parsing.

    This is the core requirement: commands built by CommandLauncher must
    work when passed through ProcessExecutor's bash -ilc wrapper.

    The OLD implementation FAILS this test.
    The NEW implementation should PASS this test.
    """

    def test_command_base64_survives_bash_layer(self) -> None:
        """Command's base64 payload must survive bash -ilc parsing.

        This is what we NEED to work:
        1. Build a command with base64-encoded Python
        2. Wrap it in bash -ilc (as ProcessExecutor does)
        3. Parse what bash receives
        4. Extract and decode the base64
        5. Verify it matches the original

        CURRENTLY FAILS with old implementation (demonstrates the bug).
        Will PASS when we implement the env var approach.
        """
        # Import the real command launcher to test actual implementation
        from command_launcher import CommandLauncher

        # We need to test the launch_with_file method's Maya handling
        # For now, test the helper method if it exists, otherwise use old logic
        launcher = CommandLauncher.__new__(CommandLauncher)

        context_script = "print('hello')"
        file_path = "/shows/test/scene.ma"

        # Check if new helper method exists
        if hasattr(launcher, "_build_maya_context_command"):
            # NEW implementation
            command = launcher._build_maya_context_command("maya", file_path, context_script)
        else:
            # OLD implementation (this is what we're testing against)
            encoded = base64.b64encode(context_script.encode()).decode()
            mel_cmd = f'python "import base64; exec(base64.b64decode(\\"{encoded}\\").decode())"'
            command = f"maya -file {file_path} -c {shlex.quote(mel_cmd)}"

        # Wrap for bash -ilc (as ProcessExecutor does)
        wrapped = f"bash -ilc {shlex.quote(command)}"

        # Parse the wrapped command
        parts = shlex.split(wrapped)
        inner_command = parts[-1]

        # Parse the inner command
        inner_parts = shlex.split(inner_command)

        # Find the base64 content - could be in -c arg OR in env var export
        base64_found = False
        decoded_script = None

        # Check for env var approach (new)
        env_match = re.search(r"SHOTBOT_MAYA_SCRIPT=(\S+)", inner_command)
        if env_match:
            b64_value = env_match.group(1).rstrip(" &")
            try:
                decoded_script = base64.b64decode(b64_value).decode()
                base64_found = True
            except Exception:
                pass

        # Check for -c argument approach (old)
        if not base64_found:
            for i, part in enumerate(inner_parts):
                if part == "-c" and i + 1 < len(inner_parts):
                    c_arg = inner_parts[i + 1]
                    # Look for base64.b64decode("...") or base64.b64decode('...')
                    b64_match = re.search(r'base64\.b64decode\(["\']([^"\']+)["\']', c_arg)
                    if b64_match:
                        try:
                            decoded_script = base64.b64decode(b64_match.group(1)).decode()
                            base64_found = True
                        except Exception:
                            pass
                    break

        # The test requirement: base64 must decode to original script
        assert base64_found, (
            f"Could not find/decode base64 payload in command.\n"
            f"Original: {command}\n"
            f"Wrapped: {wrapped}\n"
            f"Inner parts: {inner_parts}"
        )
        assert decoded_script == context_script, (
            f"Base64 decoded to wrong value.\n"
            f"Expected: {context_script!r}\n"
            f"Got: {decoded_script!r}"
        )


class TestNewMayaCommandConstruction:
    """Tests for the NEW fixed implementation using environment variables.

    The fix: Move the base64-encoded script to an environment variable,
    and use only static code in the -c argument.
    """

    def _build_new_maya_command(self, file_path: str, context_script: str) -> str:
        """Build Maya command using the NEW env var approach."""
        encoded = base64.b64encode(context_script.encode()).decode()
        # Static bootstrap - reads from env var, no dynamic content in -c argument
        mel_bootstrap = (
            'python("import os,base64;'
            "s=os.environ.get('SHOTBOT_MAYA_SCRIPT','');"
            'exec(base64.b64decode(s).decode()) if s else None")'
        )
        return (
            f"export SHOTBOT_MAYA_SCRIPT={encoded} && "
            f"maya -file {file_path} -c {shlex.quote(mel_bootstrap)}"
        )

    def test_new_command_survives_bash_parsing(self) -> None:
        """NEW implementation: Command should survive bash -ilc parsing."""
        context_script = "print('hello')"
        file_path = "/shows/test/scene.ma"

        command = self._build_new_maya_command(file_path, context_script)

        # The new approach should survive shlex.split (simulates bash parsing)
        try:
            parts = shlex.split(command)
            # Should parse without error
            assert len(parts) > 0
        except ValueError as e:
            pytest.fail(f"New command failed shlex parsing: {e}")

    def test_new_command_has_static_c_argument(self) -> None:
        """NEW implementation: The -c argument should be static (no base64 payload)."""
        context_script = "print('hello')"
        encoded = base64.b64encode(context_script.encode()).decode()

        command = self._build_new_maya_command("/path/file.ma", context_script)

        # Extract the -c argument
        c_index = command.find(" -c ")
        assert c_index != -1
        c_arg = command[c_index + 4:]

        # The base64 payload should NOT be in the -c argument
        # It should only be in the env var export
        assert encoded not in c_arg, "Base64 should not be in -c argument"

        # But it should be in the env var export
        assert f"SHOTBOT_MAYA_SCRIPT={encoded}" in command

    def test_new_command_env_var_contains_valid_base64(self) -> None:
        """NEW implementation: SHOTBOT_MAYA_SCRIPT should contain valid base64."""
        context_script = "print('hello world')"

        command = self._build_new_maya_command("/path/file.ma", context_script)

        # Extract the env var value
        match = re.search(r"export SHOTBOT_MAYA_SCRIPT=(\S+)", command)
        assert match is not None

        b64_value = match.group(1).rstrip(" &")
        decoded = base64.b64decode(b64_value).decode()

        assert decoded == context_script

    def test_new_command_bootstrap_reads_env_var(self) -> None:
        """NEW implementation: Bootstrap should read SHOTBOT_MAYA_SCRIPT."""
        command = self._build_new_maya_command("/path/file.ma", "x=1")

        # The bootstrap code in -c should reference the env var
        assert "SHOTBOT_MAYA_SCRIPT" in command.split(" -c ")[1]
        assert "os.environ.get" in command
