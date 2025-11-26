"""Tests for EnvironmentCommandBuilder."""

from __future__ import annotations

from launch.environment_builder import EnvironmentCommandBuilder
from launcher.models import LauncherEnvironment


class TestEnvironmentCommandBuilder:
    """Tests for EnvironmentCommandBuilder.build_command() method."""

    def test_plain_bash_passthrough(self) -> None:
        """Command with no env settings passes through unchanged."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment()
        assert builder.build_command("echo hello", env) == "echo hello"

    def test_bash_type_explicit(self) -> None:
        """Explicit bash type with no settings passes through."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="bash")
        assert builder.build_command("myapp", env) == "myapp"

    def test_source_files_single(self) -> None:
        """Single source file is sourced before command."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(source_files=["/path/env.sh"])
        result = builder.build_command("myapp", env)
        # shlex.quote only adds quotes when necessary (no spaces = no quotes)
        assert result == "source /path/env.sh && myapp"

    def test_source_files_multiple(self) -> None:
        """Multiple source files are chained with &&."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(source_files=["/a.sh", "/b.sh"])
        result = builder.build_command("myapp", env)
        assert result == "source /a.sh && source /b.sh && myapp"

    def test_source_files_with_spaces(self) -> None:
        """Source files with spaces are properly quoted."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(source_files=["/path/my env.sh"])
        result = builder.build_command("myapp", env)
        assert "source '/path/my env.sh'" in result

    def test_command_prefix_applied(self) -> None:
        """Command prefix is prepended."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(command_prefix="cd /workspace")
        result = builder.build_command("myapp", env)
        assert result == "cd /workspace && myapp"

    def test_command_prefix_env_var(self) -> None:
        """Command prefix can set environment variables."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(command_prefix="export FOO=bar")
        result = builder.build_command("myapp", env)
        assert result == "export FOO=bar && myapp"

    def test_rez_wrapping_single_package(self) -> None:
        """Rez environment wraps command with single package."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="rez", packages=["nuke-16"])
        result = builder.build_command("nuke", env)
        assert "rez env nuke-16 -- bash -ilc" in result
        # shlex.quote only adds quotes when necessary
        assert "nuke" in result

    def test_rez_wrapping_multiple_packages(self) -> None:
        """Rez environment wraps command with multiple packages."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="rez", packages=["nuke-16", "ocio-2.0"])
        result = builder.build_command("nuke", env)
        assert "rez env nuke-16 ocio-2.0 -- bash -ilc" in result

    def test_rez_without_packages_no_wrap(self) -> None:
        """Rez type with no packages does not wrap."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="rez", packages=[])
        result = builder.build_command("nuke", env)
        assert result == "nuke"
        assert "rez env" not in result

    def test_rez_with_complex_command(self) -> None:
        """Rez wrapping handles complex commands with special chars."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="rez", packages=["nuke"])
        result = builder.build_command("nuke --script 'test.nk'", env)
        assert "rez env nuke -- bash -ilc" in result
        # The entire command should be quoted
        assert "nuke --script" in result

    def test_combined_source_and_prefix(self) -> None:
        """Source files and prefix combine correctly."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(
            source_files=["/env.sh"],
            command_prefix="cd /work"
        )
        result = builder.build_command("myapp", env)
        # Order: source -> prefix -> command
        assert result == "source /env.sh && cd /work && myapp"

    def test_combined_all_settings(self) -> None:
        """All settings combine in correct order."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(
            type="rez",
            packages=["nuke"],
            source_files=["/env.sh"],
            command_prefix="export FOO=bar"
        )
        result = builder.build_command("nuke", env)
        # Order: source -> prefix -> rez-wrapped command
        assert "source /env.sh" in result
        assert "export FOO=bar" in result
        assert "rez env nuke" in result
        # Verify order
        source_pos = result.index("source")
        export_pos = result.index("export")
        rez_pos = result.index("rez")
        assert source_pos < export_pos < rez_pos

    def test_combined_source_prefix_bash(self) -> None:
        """Source and prefix with bash type (no rez)."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(
            type="bash",
            source_files=["/a.sh"],
            command_prefix="cd /tmp"
        )
        result = builder.build_command("myapp", env)
        assert result == "source /a.sh && cd /tmp && myapp"
        assert "rez" not in result

    def test_empty_environment(self) -> None:
        """Default empty environment passes command through."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment()
        result = builder.build_command("complex && command | pipe", env)
        assert result == "complex && command | pipe"

    def test_multicommand_preserved_without_rez(self) -> None:
        """Multi-command patterns preserved without rez wrapping."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="bash")
        result = builder.build_command("cd /tmp && echo hello", env)
        assert result == "cd /tmp && echo hello"

    def test_multicommand_quoted_in_rez(self) -> None:
        """Multi-command patterns are quoted when rez-wrapped."""
        builder = EnvironmentCommandBuilder()
        env = LauncherEnvironment(type="rez", packages=["python"])
        result = builder.build_command("cd /tmp && python app.py", env)
        # shlex.quote will escape the entire command
        assert "rez env python -- bash -ilc" in result
        assert "cd /tmp && python app.py" in result
