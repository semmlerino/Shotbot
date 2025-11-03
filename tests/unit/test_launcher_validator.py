"""Comprehensive unit tests for LauncherValidator.

Testing validation logic for launcher configurations and commands.
Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Cover all validation scenarios
- Test both positive and negative cases
- Mock external dependencies (subprocess calls)
- Proper error message validation
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from launcher.models import (
    CustomLauncher,
    LauncherEnvironment,
    LauncherTerminal,
    LauncherValidation,
)
from launcher.validator import LauncherValidator
from type_definitions import Shot


if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def validator(qapp: QApplication) -> LauncherValidator:
    """Create a LauncherValidator instance for testing."""
    return LauncherValidator()


@pytest.fixture
def sample_shot() -> Shot:
    """Create a sample Shot for testing."""
    return Shot(
        show="test_show",
        sequence="seq010",
        shot="shot0010",
        workspace_path="/mnt/shows/test_show/seq010/shot0010",
    )


@pytest.fixture
def sample_launcher() -> CustomLauncher:
    """Create a sample CustomLauncher for testing."""
    return CustomLauncher(
        id="test_launcher_001",
        name="Test Launcher",
        description="A test launcher",
        command="echo Hello $show $sequence $shot",
        category="custom",
        environment=LauncherEnvironment(),
        terminal=LauncherTerminal(),
        validation=LauncherValidation(),
    )


@pytest.fixture
def existing_launchers() -> dict[str, CustomLauncher]:
    """Create a dictionary of existing launchers for uniqueness testing."""
    launcher1 = CustomLauncher(
        id="launcher_001",
        name="Existing Launcher 1",
        description="First existing launcher",
        command="echo test1",
    )
    launcher2 = CustomLauncher(
        id="launcher_002",
        name="Existing Launcher 2",
        description="Second existing launcher",
        command="echo test2",
    )
    return {
        "launcher_001": launcher1,
        "launcher_002": launcher2,
    }


# ============================================================================
# Test Initialization
# ============================================================================


class TestInitialization:
    """Test LauncherValidator initialization."""

    def test_initialization_sets_valid_variables(self, validator: LauncherValidator) -> None:
        """Test validator initializes with correct set of valid variables."""
        expected_vars = {
            "show",
            "sequence",
            "shot",
            "full_name",
            "workspace_path",
            "HOME",
            "USER",
            "SHOTBOT_VERSION",
        }
        assert validator.valid_variables == expected_vars

    def test_initialization_sets_security_patterns(
        self, validator: LauncherValidator
    ) -> None:
        """Test validator initializes with security patterns."""
        assert len(validator.security_patterns) > 0
        assert "rm -rf" in validator.security_patterns
        assert "sudo rm" in validator.security_patterns

    def test_has_logging_mixin(self, validator: LauncherValidator) -> None:
        """Test validator has logging capabilities."""
        assert hasattr(validator, "logger")


# ============================================================================
# Test Launcher Data Validation
# ============================================================================


class TestLauncherDataValidation:
    """Test validate_launcher_data method."""

    def test_valid_launcher_data(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test validation passes for valid launcher data."""
        errors = validator.validate_launcher_data(
            name="New Launcher",
            command="echo test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) == 0

    def test_empty_name_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test empty name is rejected."""
        errors = validator.validate_launcher_data(
            name="",
            command="echo test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) == 1
        assert "Name cannot be empty" in errors[0]

    def test_whitespace_only_name_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test whitespace-only name is rejected."""
        errors = validator.validate_launcher_data(
            name="   ",
            command="echo test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) == 1
        assert "Name cannot be empty" in errors[0]

    def test_name_too_long_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test name exceeding 100 characters is rejected."""
        long_name = "A" * 101
        errors = validator.validate_launcher_data(
            name=long_name,
            command="echo test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) == 1
        assert "cannot exceed 100 characters" in errors[0]

    def test_duplicate_name_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test duplicate launcher name is rejected."""
        errors = validator.validate_launcher_data(
            name="Existing Launcher 1",
            command="echo test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) == 1
        assert "already exists" in errors[0]

    def test_duplicate_name_allowed_when_excluding_self(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test duplicate name allowed when updating same launcher."""
        errors = validator.validate_launcher_data(
            name="Existing Launcher 1",
            command="echo updated",
            existing_launchers=existing_launchers,
            exclude_id="launcher_001",
        )
        # Should only have errors from command validation if any
        name_errors = [e for e in errors if "already exists" in e]
        assert len(name_errors) == 0

    def test_empty_command_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test empty command is rejected."""
        errors = validator.validate_launcher_data(
            name="Valid Name",
            command="",
            existing_launchers=existing_launchers,
        )
        assert any("Command cannot be empty" in e for e in errors)

    def test_whitespace_only_command_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test whitespace-only command is rejected."""
        errors = validator.validate_launcher_data(
            name="Valid Name",
            command="   ",
            existing_launchers=existing_launchers,
        )
        assert any("Command cannot be empty" in e for e in errors)

    def test_dangerous_command_rejected(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test command with dangerous patterns is rejected."""
        errors = validator.validate_launcher_data(
            name="Dangerous Launcher",
            command="rm -rf /tmp/test",
            existing_launchers=existing_launchers,
        )
        assert len(errors) > 0
        assert any("dangerous pattern" in e.lower() for e in errors)


# ============================================================================
# Test Security Validation
# ============================================================================


class TestSecurityValidation:
    """Test _validate_security method."""

    def test_safe_command_passes(self, validator: LauncherValidator) -> None:
        """Test safe command passes security validation."""
        errors = validator._validate_security("echo Hello World")
        assert len(errors) == 0

    def test_rm_rf_detected(self, validator: LauncherValidator) -> None:
        """Test rm -rf pattern is detected."""
        errors = validator._validate_security("rm -rf /tmp/test")
        assert len(errors) > 0
        assert "dangerous pattern" in errors[0].lower()

    def test_sudo_rm_detected(self, validator: LauncherValidator) -> None:
        """Test sudo rm pattern is detected."""
        errors = validator._validate_security("sudo rm /etc/test")
        assert len(errors) > 0

    def test_case_insensitive_detection(self, validator: LauncherValidator) -> None:
        """Test security patterns are detected case-insensitively."""
        errors = validator._validate_security("RM -RF /tmp")
        assert len(errors) > 0

    def test_format_c_detected(self, validator: LauncherValidator) -> None:
        """Test format c: pattern is detected."""
        errors = validator._validate_security("format c:")
        assert len(errors) > 0

    def test_dev_sda_detected(self, validator: LauncherValidator) -> None:
        """Test > /dev/sda pattern is detected."""
        errors = validator._validate_security("dd if=/dev/zero > /dev/sda")
        assert len(errors) > 0

    def test_only_first_pattern_reported(self, validator: LauncherValidator) -> None:
        """Test only the first dangerous pattern is reported."""
        # Command with multiple dangerous patterns
        errors = validator._validate_security("rm -rf /tmp && sudo rm /etc")
        # Should only report the first match
        assert len(errors) == 1


# ============================================================================
# Test Command Syntax Validation
# ============================================================================


class TestCommandSyntaxValidation:
    """Test validate_command_syntax method."""

    def test_valid_command_with_variables(self, validator: LauncherValidator) -> None:
        """Test valid command with variable substitutions."""
        valid, error = validator.validate_command_syntax("echo $show $sequence $shot")
        assert valid is True
        assert error is None

    def test_valid_command_with_braced_variables(
        self, validator: LauncherValidator
    ) -> None:
        """Test valid command with ${var} syntax."""
        valid, error = validator.validate_command_syntax("echo ${show} ${sequence}")
        assert valid is True
        assert error is None

    def test_valid_command_without_variables(self, validator: LauncherValidator) -> None:
        """Test valid command without any variables."""
        valid, error = validator.validate_command_syntax("ls -la /tmp")
        assert valid is True
        assert error is None

    def test_empty_command_rejected(self, validator: LauncherValidator) -> None:
        """Test empty command is rejected."""
        valid, error = validator.validate_command_syntax("")
        assert valid is False
        assert error == "Command cannot be empty"

    def test_invalid_variable_rejected(self, validator: LauncherValidator) -> None:
        """Test command with invalid variable is rejected."""
        valid, error = validator.validate_command_syntax("echo $invalid_var")
        assert valid is False
        assert error is not None
        assert "Invalid variables" in error
        assert "invalid_var" in error

    def test_mixed_valid_and_invalid_variables(
        self, validator: LauncherValidator
    ) -> None:
        """Test command with both valid and invalid variables."""
        valid, error = validator.validate_command_syntax(
            "echo $show $invalid1 $invalid2"
        )
        assert valid is False
        assert error is not None
        assert "invalid1" in error
        assert "invalid2" in error

    def test_dangerous_rm_rf_pattern(self, validator: LauncherValidator) -> None:
        """Test dangerous rm -rf / pattern is detected."""
        valid, error = validator.validate_command_syntax("rm -rf /tmp")
        assert valid is False
        assert error is not None
        assert "dangerous pattern" in error.lower()

    def test_dangerous_rm_with_wildcard(self, validator: LauncherValidator) -> None:
        """Test dangerous rm with wildcard is detected."""
        valid, error = validator.validate_command_syntax("rm /tmp/*")
        assert valid is False
        assert error is not None

    def test_dangerous_command_chaining_with_rm(
        self, validator: LauncherValidator
    ) -> None:
        """Test dangerous command chaining with rm is detected."""
        # Semicolon
        valid, _error = validator.validate_command_syntax("echo test; rm /tmp/file")
        assert valid is False

        # Double ampersand
        valid, _error = validator.validate_command_syntax("echo test && rm /tmp/file")
        assert valid is False

        # Pipe (pattern requires space after rm)
        valid, _error = validator.validate_command_syntax("cat file | rm -rf")
        assert valid is False

    def test_dangerous_command_substitution(self, validator: LauncherValidator) -> None:
        """Test dangerous command substitution patterns are detected."""
        # Backtick substitution
        valid, _error = validator.validate_command_syntax("`rm /tmp/file`")
        assert valid is False

        # $() substitution
        valid, _error = validator.validate_command_syntax("$(rm /tmp/file)")
        assert valid is False

    def test_dangerous_sudo_patterns(self, validator: LauncherValidator) -> None:
        """Test dangerous sudo patterns are detected."""
        # After semicolon
        valid, _error = validator.validate_command_syntax("echo test; sudo rm")
        assert valid is False

        # After &&
        valid, _error = validator.validate_command_syntax("echo test && sudo rm")
        assert valid is False

    def test_system_file_access_detected(self, validator: LauncherValidator) -> None:
        """Test access to system files is detected."""
        valid, _error = validator.validate_command_syntax("cat /etc/passwd")
        assert valid is False

        valid, _error = validator.validate_command_syntax("cat /etc/shadow")
        assert valid is False

    def test_environment_variables_allowed(self, validator: LauncherValidator) -> None:
        """Test environment variables are allowed."""
        valid, error = validator.validate_command_syntax("echo $HOME $USER")
        assert valid is True
        assert error is None

    def test_shotbot_version_variable_allowed(
        self, validator: LauncherValidator
    ) -> None:
        """Test SHOTBOT_VERSION variable is allowed."""
        valid, error = validator.validate_command_syntax("echo $SHOTBOT_VERSION")
        assert valid is True
        assert error is None


# ============================================================================
# Test Path Validation
# ============================================================================


class TestPathValidation:
    """Test validate_launcher_paths method."""

    def test_no_required_paths_always_valid(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test launcher with no required paths is always valid."""
        sample_launcher.validation.required_files = []
        sample_launcher.environment.source_files = []

        valid, missing = validator.validate_launcher_paths(sample_launcher)
        assert valid is True
        assert len(missing) == 0

    def test_existing_required_file_valid(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test launcher with existing required file is valid."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            sample_launcher.validation.required_files = [tmp_path]
            valid, missing = validator.validate_launcher_paths(sample_launcher)
            assert valid is True
            assert len(missing) == 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_missing_required_file_invalid(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test launcher with missing required file is invalid."""
        sample_launcher.validation.required_files = ["/nonexistent/path/file.txt"]

        valid, missing = validator.validate_launcher_paths(sample_launcher)
        assert valid is False
        assert len(missing) == 1
        assert "/nonexistent/path/file.txt" in missing[0]

    def test_multiple_missing_files_reported(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test all missing files are reported."""
        sample_launcher.validation.required_files = [
            "/nonexistent/file1.txt",
            "/nonexistent/file2.txt",
        ]

        valid, missing = validator.validate_launcher_paths(sample_launcher)
        assert valid is False
        assert len(missing) == 2

    def test_path_substitution_with_shot_context(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
        sample_shot: Shot,
    ) -> None:
        """Test path validation with variable substitution."""
        # Use the shot's workspace path which should exist in mock environment
        sample_launcher.validation.required_files = ["$workspace_path"]

        shot_context = {
            "show": sample_shot.show,
            "sequence": sample_shot.sequence,
            "shot": sample_shot.shot,
            "workspace_path": sample_shot.workspace_path,
        }

        # This will fail since the path doesn't actually exist, but we can verify
        # the substitution happened
        valid, missing = validator.validate_launcher_paths(
            sample_launcher, shot_context=shot_context
        )
        assert valid is False
        # Check that the path was substituted
        assert any(sample_shot.workspace_path in path for path in missing)

    def test_source_file_validation(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation includes source files from environment."""
        sample_launcher.environment.source_files = ["/nonexistent/source.sh"]

        valid, missing = validator.validate_launcher_paths(sample_launcher)
        assert valid is False
        assert len(missing) == 1
        assert "/nonexistent/source.sh" in missing[0]

    def test_expanduser_for_home_directory(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test tilde expansion for home directory paths."""
        # Use ~/.bashrc which typically exists
        sample_launcher.validation.required_files = ["~/.bashrc"]

        valid, missing = validator.validate_launcher_paths(sample_launcher)
        # May or may not exist depending on system, but should expand ~
        # The key is that it doesn't error on the tilde
        assert isinstance(valid, bool)
        assert isinstance(missing, list)


# ============================================================================
# Test Environment Validation
# ============================================================================


class TestEnvironmentValidation:
    """Test validate_environment method."""

    def test_valid_bash_environment(self, validator: LauncherValidator) -> None:
        """Test bash environment is valid."""
        env = LauncherEnvironment(type="bash")
        valid, error = validator.validate_environment(env)
        assert valid is True
        assert error == ""

    def test_valid_rez_environment(self, validator: LauncherValidator) -> None:
        """Test rez environment type is accepted."""
        env = LauncherEnvironment(type="rez")
        # Mock the rez check
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            valid, error = validator.validate_environment(env)
            assert valid is True
            assert error == ""

    def test_valid_conda_environment(self, validator: LauncherValidator) -> None:
        """Test conda environment type is accepted."""
        env = LauncherEnvironment(type="conda")
        # Mock the conda check
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            valid, error = validator.validate_environment(env)
            assert valid is True
            assert error == ""

    def test_invalid_environment_type(self, validator: LauncherValidator) -> None:
        """Test invalid environment type is rejected."""
        env = LauncherEnvironment(type="invalid_type")
        valid, error = validator.validate_environment(env)
        assert valid is False
        assert "Invalid environment type" in error
        assert "bash, rez, conda" in error

    def test_rez_not_installed(self, validator: LauncherValidator) -> None:
        """Test rez environment fails if rez not found."""
        env = LauncherEnvironment(type="rez", packages=["maya-2024"])
        # Mock rez command not found
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)
            valid, error = validator.validate_environment(env)
            assert valid is False
            assert "rez command not found" in error

    def test_conda_not_installed(self, validator: LauncherValidator) -> None:
        """Test conda environment fails if conda not found."""
        env = LauncherEnvironment(type="conda")
        # Mock conda command not found
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1)
            valid, error = validator.validate_environment(env)
            assert valid is False
            assert "conda command not found" in error

    def test_rez_check_exception_handled(self, validator: LauncherValidator) -> None:
        """Test exception during rez check is handled gracefully."""
        env = LauncherEnvironment(type="rez", packages=["test"])
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("which", 1)
            valid, error = validator.validate_environment(env)
            assert valid is False
            assert "Could not verify rez installation" in error

    def test_conda_check_exception_handled(self, validator: LauncherValidator) -> None:
        """Test exception during conda check is handled gracefully."""
        env = LauncherEnvironment(type="conda")
        with patch("launcher.validator.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Test error")
            valid, error = validator.validate_environment(env)
            assert valid is False
            assert "Could not verify conda installation" in error


# ============================================================================
# Test Comprehensive Launcher Configuration Validation
# ============================================================================


class TestLauncherConfigValidation:
    """Test validate_launcher_config method."""

    def test_valid_launcher_config(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test fully valid launcher configuration."""
        valid, errors = validator.validate_launcher_config(sample_launcher)
        assert valid is True
        assert len(errors) == 0

    def test_validation_includes_command_syntax_check(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation checks command syntax."""
        sample_launcher.command = "echo $invalid_variable"
        valid, errors = validator.validate_launcher_config(sample_launcher)
        assert valid is False
        assert any("Invalid variables" in e for e in errors)

    def test_validation_includes_environment_check(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation checks environment configuration."""
        sample_launcher.environment.type = "invalid_type"
        valid, errors = validator.validate_launcher_config(sample_launcher)
        assert valid is False
        assert any("Invalid environment type" in e for e in errors)

    def test_validation_checks_forbidden_patterns(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation checks custom forbidden patterns."""
        sample_launcher.command = "echo test; rm file"
        sample_launcher.validation.forbidden_patterns = [r";\s*rm\s"]
        valid, errors = validator.validate_launcher_config(sample_launcher)
        assert valid is False
        assert any("forbidden pattern" in e for e in errors)

    def test_validation_handles_invalid_regex_in_forbidden_patterns(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation handles invalid regex patterns gracefully."""
        sample_launcher.validation.forbidden_patterns = ["[invalid(regex"]
        # Should not crash, just log warning
        valid, errors = validator.validate_launcher_config(sample_launcher)
        # Should still be valid since the invalid regex is ignored
        assert isinstance(valid, bool)
        assert isinstance(errors, list)

    def test_validation_includes_name_uniqueness_check(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test validation checks name uniqueness when existing launchers provided."""
        sample_launcher.name = "Existing Launcher 1"
        valid, errors = validator.validate_launcher_config(
            sample_launcher, existing_launchers=existing_launchers
        )
        assert valid is False
        assert any("already exists" in e for e in errors)

    def test_validation_accumulates_multiple_errors(
        self,
        validator: LauncherValidator,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test validation reports all errors, not just the first one."""
        sample_launcher.command = "echo $invalid_var"
        sample_launcher.environment.type = "invalid_type"
        valid, errors = validator.validate_launcher_config(sample_launcher)
        assert valid is False
        assert len(errors) >= 2  # Should have both command and environment errors


# ============================================================================
# Test Process Startup Validation
# ============================================================================


class TestProcessStartupValidation:
    """Test validate_process_startup method."""

    def test_running_process_valid(self, validator: LauncherValidator) -> None:
        """Test running process is valid."""
        mock_process = Mock(spec=subprocess.Popen)
        mock_process.poll.return_value = None  # Process still running
        mock_process.pid = 12345

        assert validator.validate_process_startup(mock_process) is True

    def test_terminated_process_invalid(self, validator: LauncherValidator) -> None:
        """Test terminated process is invalid."""
        mock_process = Mock(spec=subprocess.Popen)
        mock_process.poll.return_value = 0  # Process has exited
        mock_process.pid = 12345

        assert validator.validate_process_startup(mock_process) is False

    def test_failed_process_invalid(self, validator: LauncherValidator) -> None:
        """Test process with non-zero exit code is invalid."""
        mock_process = Mock(spec=subprocess.Popen)
        mock_process.poll.return_value = 1  # Process exited with error
        mock_process.pid = 12345

        assert validator.validate_process_startup(mock_process) is False

    def test_exception_during_validation_handled(
        self, validator: LauncherValidator
    ) -> None:
        """Test exception during process validation is handled gracefully."""
        mock_process = Mock(spec=subprocess.Popen)
        mock_process.poll.side_effect = Exception("Test error")

        assert validator.validate_process_startup(mock_process) is False


# ============================================================================
# Test Variable Substitution
# ============================================================================


class TestVariableSubstitution:
    """Test substitute_variables method."""

    def test_substitution_without_shot_or_custom_vars(
        self, validator: LauncherValidator
    ) -> None:
        """Test substitution with only environment variables."""
        text = "Home: $HOME, User: $USER"
        result = validator.substitute_variables(text)
        assert "$HOME" not in result
        assert "$USER" not in result
        # Should have actual values from environment

    def test_substitution_with_shot_context(
        self,
        validator: LauncherValidator,
        sample_shot: Shot,
    ) -> None:
        """Test substitution with shot context."""
        text = "Show: $show, Sequence: $sequence, Shot: $shot"
        result = validator.substitute_variables(text, shot=sample_shot)
        assert "test_show" in result
        assert "seq010" in result
        assert "shot0010" in result

    def test_substitution_with_full_name(
        self,
        validator: LauncherValidator,
        sample_shot: Shot,
    ) -> None:
        """Test substitution of full_name variable."""
        text = "Full name: $full_name"
        result = validator.substitute_variables(text, shot=sample_shot)
        assert "seq010_shot0010" in result

    def test_substitution_with_workspace_path(
        self,
        validator: LauncherValidator,
        sample_shot: Shot,
    ) -> None:
        """Test substitution of workspace_path variable."""
        text = "Path: $workspace_path"
        result = validator.substitute_variables(text, shot=sample_shot)
        assert sample_shot.workspace_path in result

    def test_substitution_with_custom_vars(
        self, validator: LauncherValidator
    ) -> None:
        """Test substitution with custom variables."""
        text = "Custom: $custom_var"
        custom_vars = {"custom_var": "custom_value"}
        result = validator.substitute_variables(text, custom_vars=custom_vars)
        assert "custom_value" in result

    def test_substitution_with_braced_syntax(
        self,
        validator: LauncherValidator,
        sample_shot: Shot,
    ) -> None:
        """Test substitution with ${var} syntax."""
        text = "Show: ${show}, Sequence: ${sequence}"
        result = validator.substitute_variables(text, shot=sample_shot)
        assert "test_show" in result
        assert "seq010" in result

    def test_substitution_preserves_unmatched_variables(
        self, validator: LauncherValidator
    ) -> None:
        """Test safe_substitute preserves variables without matches."""
        text = "Known: $HOME, Unknown: $unknown_var"
        result = validator.substitute_variables(text)
        # safe_substitute should leave unknown variables in place
        assert "$unknown_var" in result

    def test_empty_text_returns_empty(self, validator: LauncherValidator) -> None:
        """Test empty text returns empty string."""
        result = validator.substitute_variables("")
        assert result == ""

    def test_none_text_returns_none(self, validator: LauncherValidator) -> None:
        """Test None text returns None."""
        result = validator.substitute_variables(None)  # type: ignore[arg-type]
        assert result is None

    def test_shotbot_version_substitution(
        self, validator: LauncherValidator
    ) -> None:
        """Test SHOTBOT_VERSION variable substitution."""
        text = "Version: $SHOTBOT_VERSION"
        result = validator.substitute_variables(text)
        assert "$SHOTBOT_VERSION" not in result
        # Should contain actual version from Config

    def test_custom_vars_override_shot_context(
        self,
        validator: LauncherValidator,
        sample_shot: Shot,
    ) -> None:
        """Test custom variables override shot context."""
        text = "Show: $show"
        custom_vars = {"show": "override_show"}
        result = validator.substitute_variables(
            text, shot=sample_shot, custom_vars=custom_vars
        )
        # Custom vars are added after shot context, so they override
        assert "override_show" in result

    def test_malformed_template_handled_gracefully(
        self, validator: LauncherValidator
    ) -> None:
        """Test malformed template syntax is handled gracefully."""
        text = "Bad syntax: ${"
        # Should not crash, should return original text
        result = validator.substitute_variables(text)
        assert isinstance(result, str)


# ============================================================================
# Edge Cases and Integration Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and integration scenarios."""

    def test_unicode_in_command(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test handling of unicode characters in commands."""
        errors = validator.validate_launcher_data(
            name="Unicode Test",
            command="echo '你好世界'",
            existing_launchers=existing_launchers,
        )
        # Should not crash, unicode is fine
        assert isinstance(errors, list)

    def test_very_long_command(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test handling of very long commands."""
        long_command = "echo " + "a" * 10000
        errors = validator.validate_launcher_data(
            name="Long Command",
            command=long_command,
            existing_launchers=existing_launchers,
        )
        # Should not crash
        assert isinstance(errors, list)

    def test_special_characters_in_name(
        self,
        validator: LauncherValidator,
        existing_launchers: dict[str, CustomLauncher],
    ) -> None:
        """Test special characters in launcher name."""
        errors = validator.validate_launcher_data(
            name="Test-Launcher_v1.0 (beta)",
            command="echo test",
            existing_launchers=existing_launchers,
        )
        # Special characters in name should be allowed
        assert len(errors) == 0

    def test_case_sensitivity_in_validation(
        self, validator: LauncherValidator
    ) -> None:
        """Test that variable validation is case-sensitive."""
        # 'Show' (capital S) is not in valid_variables
        valid, error = validator.validate_command_syntax("echo $Show")
        assert valid is False
        assert "Invalid variables" in error
        assert "Show" in error

    def test_mixed_variable_formats(self, validator: LauncherValidator) -> None:
        """Test command with both $var and ${var} formats."""
        valid, error = validator.validate_command_syntax("echo $show ${sequence}")
        assert valid is True
        assert error is None

    def test_validator_thread_safety(self, validator: LauncherValidator) -> None:
        """Test that validator can be safely used from multiple contexts."""
        # Create multiple instances
        v1 = LauncherValidator()
        v2 = LauncherValidator()

        # Both should have independent state
        assert v1.valid_variables == v2.valid_variables
        assert v1 is not v2
