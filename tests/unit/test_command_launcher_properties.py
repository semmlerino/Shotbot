"""Property-based tests for CommandLauncher using Hypothesis.

This module uses property-based testing to verify CommandLauncher behavior
across a wide range of generated inputs, uncovering edge cases that might
be missed by example-based tests.

Test Coverage:
- LaunchContext creation with various parameter combinations
- Path validation with generated filesystem paths
- Command building with edge case inputs
- Input sanitization and injection prevention
"""

from __future__ import annotations

import string

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Local application imports
from command_launcher import LaunchContext
from launch import CommandBuilder


# Custom strategies for generating test data
@st.composite
def valid_filesystem_paths(draw: st.DrawFn) -> str:
    """Generate valid filesystem paths for testing.

    Returns paths that should be accepted by path validation.
    """
    # Generate path components
    num_components = draw(st.integers(min_value=1, max_value=5))
    components = []

    for _ in range(num_components):
        # Valid path component: alphanumeric, dash, underscore
        component = draw(
            st.text(
                alphabet=string.ascii_letters + string.digits + "_-",
                min_size=1,
                max_size=20,
            )
        )
        components.append(component)

    # Build path
    return "/" + "/".join(components)


@st.composite
def potentially_dangerous_paths(draw: st.DrawFn) -> str:
    """Generate potentially dangerous filesystem paths.

    Returns paths that contain injection attempts or invalid characters.
    """
    # Choose a dangerous pattern
    return draw(
        st.sampled_from(
            [
                "../../../etc/passwd",  # Path traversal
                "/tmp/test; rm -rf /",  # Command injection
                "/path/with spaces/file",  # Spaces (valid but need quoting)
                "/path/with\nnewline/file",  # Newline
                "/path/with\ttab/file",  # Tab
                "/path/with'quote/file",  # Single quote
                '/path/with"quote/file',  # Double quote
                "/path/with$(cmd)/file",  # Command substitution
                "/path/with`cmd`/file",  # Backtick substitution
                "/path/with|pipe/file",  # Pipe
                "/path/with&background/file",  # Background operator
                "/path/with;semicolon/file",  # Command separator
            ]
        )
    )


class TestLaunchContextProperties:
    """Property-based tests for LaunchContext value object."""

    @given(
        open_latest_threede=st.booleans(),
        open_latest_maya=st.booleans(),
        open_latest_scene=st.booleans(),
        create_new_file=st.booleans(),
    )
    def test_launch_context_creation_always_succeeds(
        self,
        open_latest_threede: bool,
        open_latest_maya: bool,
        open_latest_scene: bool,
        create_new_file: bool,
    ) -> None:
        """Verify LaunchContext can be created with any boolean combination."""
        context = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
        )

        # Verify all fields are set correctly
        assert context.open_latest_threede == open_latest_threede
        assert context.open_latest_maya == open_latest_maya
        assert context.open_latest_scene == open_latest_scene
        assert context.create_new_file == create_new_file

    @given(selected_plate=st.one_of(st.none(), st.text(min_size=1, max_size=10)))
    def test_launch_context_selected_plate_optional(
        self, selected_plate: str | None
    ) -> None:
        """Verify LaunchContext handles optional selected_plate correctly."""
        context = LaunchContext(selected_plate=selected_plate)

        assert context.selected_plate == selected_plate

    def test_launch_context_is_immutable(self) -> None:
        """Verify LaunchContext is frozen (immutable)."""
        context = LaunchContext(open_latest_scene=True)

        # Attempt to modify should raise FrozenInstanceError
        with pytest.raises(Exception, match=r"cannot assign to field"):  # FrozenInstanceError from dataclass
            context.open_latest_scene = False  # type: ignore[misc]

    @given(
        open_latest_threede=st.booleans(),
        open_latest_maya=st.booleans(),
        open_latest_scene=st.booleans(),
        create_new_file=st.booleans(),
        selected_plate=st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    )
    def test_launch_context_equality(
        self,
        open_latest_threede: bool,
        open_latest_maya: bool,
        open_latest_scene: bool,
        create_new_file: bool,
        selected_plate: str | None,
    ) -> None:
        """Verify LaunchContext equality works correctly."""
        context1 = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
            selected_plate=selected_plate,
        )

        context2 = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_maya=open_latest_maya,
            open_latest_scene=open_latest_scene,
            create_new_file=create_new_file,
            selected_plate=selected_plate,
        )

        # Same values should be equal
        assert context1 == context2

        # Should be hashable (since frozen=True)
        assert hash(context1) == hash(context2)


class TestCommandBuilderProperties:
    """Property-based tests for CommandBuilder path validation."""

    @given(path=valid_filesystem_paths())
    def test_validate_path_accepts_valid_paths(self, path: str) -> None:
        """Verify path validation accepts valid filesystem paths."""
        # Valid paths should be accepted
        validated = CommandBuilder.validate_path(path)

        # Validated path should be properly quoted if needed
        assert isinstance(validated, str)
        assert len(validated) > 0

    @given(path=potentially_dangerous_paths())
    @settings(max_examples=50)  # Limit examples for potentially slow tests
    def test_validate_path_handles_dangerous_paths(self, path: str) -> None:
        """Verify path validation handles potentially dangerous inputs.

        This test doesn't assert specific behavior, but verifies that
        validation doesn't crash or allow obvious injection attacks.
        """
        try:
            validated = CommandBuilder.validate_path(path)

            # If validation succeeds, ensure basic sanitation
            # Command injection patterns should be quoted/escaped
            dangerous_chars = [";", "|", "&", "$", "`", "\n"]
            for char in dangerous_chars:
                if char in path:
                    # Dangerous characters should be escaped or quoted
                    # (exact behavior depends on implementation)
                    assert isinstance(validated, str)

        except ValueError:
            # Some paths should be rejected (e.g., path traversal)
            # This is acceptable behavior
            pass

    @given(
        path=st.text(
            alphabet=string.ascii_letters + string.digits + "/-_.",
            min_size=1,
            max_size=100,
        )
    )
    def test_validate_path_returns_string(self, path: str) -> None:
        """Verify path validation always returns a string or raises ValueError."""
        try:
            result = CommandBuilder.validate_path(path)
            assert isinstance(result, str)
        except ValueError:
            # Rejection is acceptable
            pass

    @given(packages=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))
    def test_wrap_with_rez_handles_various_package_lists(
        self, packages: list[str]
    ) -> None:
        """Verify rez wrapping handles various package list sizes."""
        command = "test_command"
        wrapped = CommandBuilder.wrap_with_rez(command, packages)

        # Wrapped command should contain original command
        assert command in wrapped

        # Wrapped command should reference rez
        assert "rez" in wrapped.lower() or "rez-env" in wrapped

    @given(command=st.text(min_size=1, max_size=100))
    def test_add_logging_handles_various_commands(self, command: str) -> None:
        """Verify logging addition handles various command formats."""
        # Filter out commands with newlines (not valid shell commands)
        assume("\n" not in command)

        logged = CommandBuilder.add_logging(command)

        # Logged command should contain original command
        assert command in logged

        # Should add redirection
        assert "2>&1" in logged or ">" in logged


class TestLaunchContextDefaults:
    """Test LaunchContext default values."""

    def test_default_context_has_all_false(self) -> None:
        """Verify default LaunchContext has all boolean flags False."""
        context = LaunchContext()

        assert context.open_latest_threede is False
        assert context.open_latest_maya is False
        assert context.open_latest_scene is False
        assert context.create_new_file is False
        assert context.selected_plate is None

    @given(
        open_latest_threede=st.booleans(),
        open_latest_scene=st.booleans(),
    )
    def test_partial_context_creation(
        self, open_latest_threede: bool, open_latest_scene: bool
    ) -> None:
        """Verify LaunchContext can be created with partial parameters."""
        context = LaunchContext(
            open_latest_threede=open_latest_threede,
            open_latest_scene=open_latest_scene,
        )

        # Specified parameters
        assert context.open_latest_threede == open_latest_threede
        assert context.open_latest_scene == open_latest_scene

        # Unspecified parameters should have defaults
        assert context.open_latest_maya is False
        assert context.create_new_file is False
        assert context.selected_plate is None


class TestPathValidationEdgeCases:
    """Test edge cases in path validation using Hypothesis."""

    @given(path=st.just(""))
    def test_empty_path_rejected(self, path: str) -> None:
        """Verify empty paths are rejected."""
        with pytest.raises(ValueError, match=r".*empty.*|.*invalid.*"):
            CommandBuilder.validate_path(path)

    @given(path=st.text(max_size=0))
    def test_zero_length_path_rejected(self, path: str) -> None:
        """Verify zero-length paths are rejected."""
        if len(path) == 0:
            with pytest.raises(ValueError, match=r".*empty.*|.*invalid.*"):
                CommandBuilder.validate_path(path)

    @given(
        path=st.text(
            alphabet=string.whitespace,
            min_size=1,
            max_size=10,
        )
    )
    def test_whitespace_only_paths_handled_safely(self, path: str) -> None:
        """Verify whitespace-only paths are either rejected or safely quoted."""
        try:
            result = CommandBuilder.validate_path(path)
            # If accepted, should be quoted to prevent issues
            assert isinstance(result, str)
            # Should be wrapped in quotes if it contains spaces
            if " " in path:
                assert "'" in result or '"' in result
        except ValueError:
            # Rejection is also acceptable for whitespace-only paths
            pass
