"""Unit tests for finder_utils module."""

from __future__ import annotations

# Third-party imports
import pytest

# Local application imports
from discovery.finder_utils import sanitize_username


class TestSanitizeUsername:
    """Test username sanitization functionality."""

    @pytest.mark.parametrize(
        ("username", "expected"),
        [
            ("john_doe", "john_doe"),
            ("user123", "user123"),
            ("test-user", "test-user"),
            ("UPPERCASE", "UPPERCASE"),
        ],
        ids=["underscore", "alphanumeric", "hyphen", "uppercase"],
    )
    def test_valid_usernames(self, username: str, expected: str) -> None:
        """Test that valid usernames pass through unchanged."""
        assert sanitize_username(username) == expected

    @pytest.mark.parametrize(
        ("username", "expected"),
        [
            ("user/../etc", "useretc"),
            ("./user", "user"),
            ("user\\system", "usersystem"),
            ("user/admin", "useradmin"),
        ],
        ids=["parent_dir", "current_dir", "backslash", "forward_slash"],
    )
    def test_path_traversal_removal(self, username: str, expected: str) -> None:
        """Test that path traversal characters are removed."""
        assert sanitize_username(username) == expected

    @pytest.mark.parametrize(
        ("username", "error_match"),
        [
            ("...", "Invalid username after sanitization"),
            ("", "Invalid username after sanitization"),
            ("user@domain", "Username contains invalid characters"),
            ("user!name", "Username contains invalid characters"),
        ],
        ids=["dots_only", "empty_string", "at_symbol", "exclamation"],
    )
    def test_invalid_usernames_raise_error(
        self, username: str, error_match: str
    ) -> None:
        """Test that invalid usernames raise ValueError."""
        with pytest.raises(ValueError, match=error_match):
            sanitize_username(username)

    def test_edge_cases(self) -> None:
        """Test edge cases for username sanitization."""
        # Single character usernames
        assert sanitize_username("a") == "a"
        assert sanitize_username("1") == "1"

        # Usernames with multiple hyphens/underscores
        assert sanitize_username("user__name") == "user__name"
        assert sanitize_username("test--user") == "test--user"
