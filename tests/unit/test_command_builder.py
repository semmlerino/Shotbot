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
from unittest.mock import MagicMock

import pytest

from config import Config
from launch.command_builder import (
    add_logging,
    apply_nuke_environment_fixes,
    build_workspace_command,
    get_nuke_fix_summary,
    validate_path,
    wrap_for_background,
    wrap_with_rez,
)


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
        result = validate_path(path)
        # shlex.quote only adds quotes when needed (spaces/special chars)
        # For simple paths, it returns as-is
        assert result == "/home/user/project/file.txt"

    def test_valid_path_with_spaces(self) -> None:
        """Test validation of path with spaces."""
        path = "/home/user/My Documents/file.txt"
        result = validate_path(path)
        # shlex.quote adds single quotes and escapes internal quotes
        assert "My Documents" in result

    def test_valid_path_with_single_quote(self) -> None:
        """Test validation of path with single quote (properly escaped)."""
        path = "/home/user/It's a file.txt"
        result = validate_path(path)
        # shlex.quote should escape the single quote
        assert result == "'/home/user/It'\"'\"'s a file.txt'"

    @pytest.mark.parametrize(
        ("path", "match_pattern"),
        [
            ("/home/user/file.txt; rm -rf /", r"dangerous character.*;"),
            ("/home/user/file.txt && malicious", r"dangerous character.*&&"),
            ("/home/user/file.txt || malicious", r"dangerous character.*\|\|"),
            ("/home/user/file.txt | cat", r"dangerous character.*\|"),
            ("/home/user/file.txt > /tmp/output", r"dangerous character.*>"),
            ("/home/user/file.txt < /tmp/input", r"dangerous character.*<"),
            ("/home/user/file.txt >> /tmp/log", r"dangerous character.*>>"),
            ("/home/user/`malicious`.txt", r"dangerous character.*`"),
            ("/home/user/$(malicious).txt", r"dangerous character.*\$\("),
            ("/home/user/file.txt\nmalicious", "dangerous character"),
            ("/home/user/file.txt\rmalicious", "dangerous character"),
            ("/home/user/${MALICIOUS}.txt", r"dangerous character.*\$\{"),
            ("/home/user/$((malicious)).txt", r"dangerous character.*\$\(\("),
        ],
    )
    def test_dangerous_characters_rejected(self, path: str, match_pattern: str) -> None:
        """Test rejection of paths containing dangerous shell characters."""
        with pytest.raises(ValueError, match=match_pattern):
            validate_path(path)

    @pytest.mark.parametrize(
        ("path", "dot_pattern"),
        [
            pytest.param(
                "/home/user/project/../file.txt", "..", id="dotdot_normalizes"
            ),
            pytest.param("/home/user/./file.txt", "/./", id="dot_normalizes"),
        ],
    )
    def test_path_with_dots_normalizes_safely(
        self, path: str, dot_pattern: str
    ) -> None:
        """Test that paths with . or .. normalize correctly (VFX pipeline use case)."""
        result = validate_path(path)
        assert "file.txt" in result
        assert dot_pattern not in result
        assert "/home/user/file.txt" in result or "'/home/user/file.txt'" in result

    def test_path_with_dots_in_dirname_allowed(self) -> None:
        """Test that paths with dots in directory names are allowed (e.g., v2.5)."""
        path = "/projects/v2.5/scenes/shot.nk"
        result = validate_path(path)
        assert "v2.5" in result
        assert "shot.nk" in result

    def test_empty_path_rejected(self) -> None:
        """Test that empty paths are rejected."""
        with pytest.raises(ValueError, match="empty"):
            validate_path("")

    def test_validate_path_safe_path_unchanged(self) -> None:
        """validate_path handles safe paths without modification."""
        safe_path = validate_path("/shows/myshow/shots/sq010/sh0010")
        assert safe_path == "/shows/myshow/shots/sq010/sh0010"

    def test_validate_path_with_spaces_does_not_crash(self) -> None:
        """validate_path handles paths with spaces and returns a valid result."""
        space_path = validate_path("/shows/my show/shots/sq010/sh0010")
        assert space_path is not None


class TestWorkspaceCommand:
    """Tests for workspace command building."""

    def test_workspace_command_simple(self) -> None:
        """Test building workspace command with simple paths."""
        workspace = "'/workspace/path'"
        app_command = "nuke"
        result = build_workspace_command(workspace, app_command)
        assert result == "ws '/workspace/path' && nuke"

    def test_workspace_command_with_env_fixes(self) -> None:
        """Test building workspace command with environment fixes."""
        workspace = "'/workspace/path'"
        app_command = "NUKE_CRASH_REPORTS=0 && nuke"
        result = build_workspace_command(workspace, app_command)
        assert result == "ws '/workspace/path' && NUKE_CRASH_REPORTS=0 && nuke"


class TestRezWrapping:
    """Tests for Rez environment wrapping."""

    def test_rez_wrap_single_package(self) -> None:
        """Test wrapping command with single Rez package."""
        command = "nuke"
        packages = ["nuke"]
        result = wrap_with_rez(command, packages)
        # shlex.quote('nuke') returns 'nuke' (no quotes needed for simple strings)
        assert result == "rez env nuke -- bash -lc nuke"

    def test_rez_wrap_multiple_packages(self) -> None:
        """Test wrapping command with multiple Rez packages."""
        command = "nuke"
        packages = ["nuke", "nuke-plugins", "ocio"]
        result = wrap_with_rez(command, packages)
        assert result == "rez env nuke nuke-plugins ocio -- bash -lc nuke"

    def test_rez_wrap_preserves_complex_command(self) -> None:
        """Test that Rez wrapping preserves complex commands."""
        command = "NUKE_CRASH_REPORTS=0 && nuke"
        packages = ["nuke"]
        result = wrap_with_rez(command, packages)
        # shlex.quote() wraps complex commands with special chars in single quotes
        assert result == "rez env nuke -- bash -lc 'NUKE_CRASH_REPORTS=0 && nuke'"

    def test_rez_wrap_escapes_double_quotes(self) -> None:
        """Test that Rez wrapping properly escapes commands with double quotes.

        This is a critical security/correctness fix. Without proper escaping,
        commands like 'nuke -F "Template"' would break the shell parsing.
        """
        command = 'nuke -F "ShotBot Template"'
        packages = ["nuke"]
        result = wrap_with_rez(command, packages)
        # shlex.quote() wraps in single quotes to preserve internal double quotes
        assert result == "rez env nuke -- bash -lc 'nuke -F \"ShotBot Template\"'"

    def test_rez_wrap_escapes_single_quotes(self) -> None:
        """Test that Rez wrapping handles commands with single quotes."""
        command = 'nuke -m "It\'s working"'
        packages = ["nuke"]
        result = wrap_with_rez(command, packages)
        # shlex.quote() escapes single quotes inside the command
        assert "It" in result
        assert "working" in result

    def test_rez_wrap_handles_mixed_quotes_and_special_chars(self) -> None:
        """Test complex command with quotes, spaces, and special characters."""
        command = (
            'maya -command "loadPlugin(\'shotbot\')" -file "/path/with spaces/scene.ma"'
        )
        packages = ["maya"]
        result = wrap_with_rez(command, packages)
        # Verify the command is properly quoted
        assert "rez env maya -- bash -lc" in result
        # Verify command is preserved (exact format depends on shlex.quote implementation)
        assert "loadPlugin" in result
        assert "shotbot" in result


class TestNukeEnvironmentFixes:
    """Tests for Nuke-specific environment fixes."""

    @pytest.mark.parametrize(
        ("skip_plugins", "ocio_config", "expected_present", "expected_absent"),
        [
            (
                True,
                "/path/to/config.ocio",
                [
                    "NUKE_PATH=$(",
                    "case",
                    "problematic_plugins",
                    "OCIO=/path/to/config.ocio",
                    "NUKE_CRASH_REPORTS=0",
                ],
                [],
            ),
            (
                False,
                "",
                ["NUKE_CRASH_REPORTS=0"],
                ["NUKE_PATH", "OCIO="],
            ),
            (
                True,
                "",
                ["NUKE_PATH=$(", "case", "problematic_plugins", "NUKE_CRASH_REPORTS=0"],
                ["OCIO="],
            ),
            (
                False,
                "/custom/ocio.ocio",
                ["OCIO=/custom/ocio.ocio", "NUKE_CRASH_REPORTS=0"],
                ["NUKE_PATH"],
            ),
        ],
        ids=[
            "all_fixes",
            "crash_reporting_only",
            "plugin_filtering_only",
            "ocio_fallback_only",
        ],
    )
    def test_nuke_environment_fixes(
        self,
        mock_config: MagicMock,
        skip_plugins: bool,
        ocio_config: str,
        expected_present: list[str],
        expected_absent: list[str],
    ) -> None:
        """Test apply_nuke_environment_fixes under different configuration combinations."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = skip_plugins
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ocio_config

        result = apply_nuke_environment_fixes("nuke", mock_config)

        for substring in expected_present:
            assert substring in result, f"Expected {substring!r} in result: {result!r}"
        for substring in expected_absent:
            assert substring not in result, (
                f"Did not expect {substring!r} in result: {result!r}"
            )
        assert result.endswith("&& nuke")

    def test_ocio_path_with_spaces(self, mock_config: MagicMock) -> None:
        """Test OCIO path with spaces is properly quoted."""
        command = "nuke"
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = False
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = "/path/with spaces/my config.ocio"

        result = apply_nuke_environment_fixes(command, mock_config)

        # Path with spaces must be properly quoted to prevent shell word splitting
        # shlex.quote adds single quotes around paths containing spaces
        assert "OCIO='/path/with spaces/my config.ocio'" in result

    @pytest.mark.parametrize(
        ("skip_plugins", "ocio_config", "expected_items", "expected_len"),
        [
            pytest.param(
                True,
                "/path/to/config.ocio",
                [
                    "runtime NUKE_PATH filtering",
                    "OCIO fallback",
                    "crash reporting disabled",
                ],
                3,
                id="all_enabled",
            ),
            pytest.param(
                False,
                "",
                ["crash reporting disabled"],
                1,
                id="minimal",
            ),
        ],
    )
    def test_fix_summary(
        self,
        mock_config: MagicMock,
        skip_plugins: bool,
        ocio_config: str,
        expected_items: list[str],
        expected_len: int,
    ) -> None:
        """Test fix summary under different configuration combinations."""
        mock_config.NUKE_SKIP_PROBLEMATIC_PLUGINS = skip_plugins
        mock_config.NUKE_OCIO_FALLBACK_CONFIG = ocio_config

        summary = get_nuke_fix_summary(mock_config)

        for item in expected_items:
            assert item in summary
        assert len(summary) == expected_len


class TestLoggingRedirection:
    """Tests for logging redirection."""

    def test_logging_added_successfully(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test that logging redirection is added successfully with pipefail."""
        monkeypatch.setattr("launch.command_builder.Path.home", lambda: tmp_path)
        command = "nuke"

        result = add_logging(command)

        # Result should include pipefail for exit code preservation
        assert result.startswith("set -o pipefail; nuke 2>&1 | tee -a ")
        assert ".shotbot/logs/dispatcher.out" in result
        assert str(tmp_path) in result

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(OSError("Permission denied"), id="oserror"),
            pytest.param(PermissionError("Access denied"), id="permission_error"),
        ],
    )
    def test_logging_graceful_degradation_on_mkdir_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception
    ) -> None:
        """Test graceful degradation when logging directory creation fails."""
        monkeypatch.setattr("launch.command_builder.Path.home", lambda: tmp_path)
        monkeypatch.setattr(
            Path, "mkdir", lambda *_a, **_kw: (_ for _ in ()).throw(exc)
        )
        command = "nuke"

        result = add_logging(command)

        assert result == "nuke"

    def test_logging_handles_spaces_in_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that logging handles spaces in log file path."""
        monkeypatch.setattr(
            "launch.command_builder.Path.home", lambda: Path("/home/user with spaces")
        )
        monkeypatch.setattr(Path, "mkdir", lambda *_a, **_kw: None)
        command = "nuke"

        result = add_logging(command)

        # Path should be quoted
        assert (
            "'/home/user with spaces" in result or '"/home/user with spaces' in result
        )


class TestBackgroundWrapping:
    """Tests for background process wrapping."""

    def test_wrap_for_background_simple_command(self) -> None:
        """Test wrapping a simple command for background execution."""
        result = wrap_for_background("nuke")
        assert result == "(nuke) & disown; exit"

    def test_wrap_for_background_complex_command(self) -> None:
        """Test wrapping a complex command with workspace and pipes."""
        command = "ws '/shows/test/shots/sq010/sh0010' && nuke 2>&1 | tee /tmp/log.txt"
        result = wrap_for_background(command)
        assert result == f"({command}) & disown; exit"


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
        # Test the maya_commands.build_maya_context_command function directly
        from commands import maya_commands

        context_script = "print('hello')"
        file_path = "/shows/test/scene.ma"

        # Call the underlying function directly
        command = maya_commands.build_maya_context_command(
            "maya", file_path, context_script
        )

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
            except Exception:  # noqa: BLE001
                pass

        # Check for -c argument approach (old)
        if not base64_found:
            for i, part in enumerate(inner_parts):
                if part == "-c" and i + 1 < len(inner_parts):
                    c_arg = inner_parts[i + 1]
                    # Look for base64.b64decode("...") or base64.b64decode('...')
                    b64_match = re.search(
                        r'base64\.b64decode\(["\']([^"\']+)["\']', c_arg
                    )
                    if b64_match:
                        try:
                            decoded_script = base64.b64decode(
                                b64_match.group(1)
                            ).decode()
                            base64_found = True
                        except Exception:  # noqa: BLE001
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
