"""Tests for the standalone workspace validator."""
from __future__ import annotations

from pathlib import Path

from launch.workspace_validator import validate_workspace


class TestValidateWorkspace:
    """Tests for validate_workspace."""

    def test_valid_workspace(self, tmp_path: Path) -> None:
        """Valid directory returns None (no error)."""
        result = validate_workspace(str(tmp_path), "maya")
        assert result is None

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        """Non-existent path returns error message."""
        bad_path = str(tmp_path / "does_not_exist")
        result = validate_workspace(bad_path, "nuke")
        assert result is not None
        assert "does not exist" in result
        assert "nuke" in result

    def test_file_not_directory(self, tmp_path: Path) -> None:
        """File (not directory) returns error message."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        result = validate_workspace(str(file_path), "3de")
        assert result is not None
        assert "not a directory" in result

    def test_error_includes_app_name(self, tmp_path: Path) -> None:
        """Error messages include the application name."""
        bad_path = str(tmp_path / "missing")
        result = validate_workspace(bad_path, "maya")
        assert result is not None
        assert "maya" in result

    def test_valid_returns_none(self, tmp_path: Path) -> None:
        """Successful validation returns None, not empty string."""
        result = validate_workspace(str(tmp_path), "rv")
        assert result is None
