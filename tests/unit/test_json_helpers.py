"""Unit tests for JSON loading and validation helpers.

Tests for managers._json_helpers.load_validated_json() function.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

# Local application imports
from managers._json_helpers import load_validated_json


pytestmark = [pytest.mark.unit]


@pytest.fixture
def test_logger() -> logging.Logger:
    """Create a test logger."""
    return logging.getLogger("test_json_helpers")


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create temporary cache directory."""
    path = tmp_path / "test_cache"
    path.mkdir()
    return path


class TestLoadValidatedJsonDictType:
    """Tests for loading and validating dict type."""

    def test_load_valid_dict(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading a valid JSON dict returns the dict."""
        json_file = cache_dir / "data.json"
        data = {"key1": "value1", "key2": "value2"}
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, dict, {}, test_logger)

        assert result == data
        assert isinstance(result, dict)

    def test_load_valid_dict_with_nested_structure(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading a dict with nested structures preserves structure."""
        json_file = cache_dir / "data.json"
        data = {
            "key1": "value1",
            "nested": {"inner": "value"},
            "list": [1, 2, 3],
        }
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, dict, {}, test_logger)

        assert result == data

    def test_load_empty_dict(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading an empty dict works correctly."""
        json_file = cache_dir / "data.json"
        data = {}
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, dict, {}, test_logger)

        assert result == {}
        assert isinstance(result, dict)


class TestLoadValidatedJsonListType:
    """Tests for loading and validating list type."""

    def test_load_valid_list(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading a valid JSON list returns the list."""
        json_file = cache_dir / "data.json"
        data = ["item1", "item2", "item3"]
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, list, [], test_logger)

        assert result == data
        assert isinstance(result, list)

    def test_load_valid_list_with_mixed_types(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading a list with mixed types preserves data."""
        json_file = cache_dir / "data.json"
        data = [1, "string", {"key": "value"}, [1, 2, 3], True, None]
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, list, [], test_logger)

        assert result == data

    def test_load_empty_list(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Loading an empty list works correctly."""
        json_file = cache_dir / "data.json"
        data = []
        json_file.write_text(json.dumps(data))

        result = load_validated_json(json_file, list, [], test_logger)

        assert result == []
        assert isinstance(result, list)


class TestLoadValidatedJsonMissingFile:
    """Tests for handling missing files."""

    def test_missing_file_returns_default(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Missing file returns default value."""
        json_file = cache_dir / "nonexistent.json"

        default = {"default": "value"}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default

    def test_missing_file_with_empty_default(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Missing file with empty default returns empty."""
        json_file = cache_dir / "nonexistent.json"

        result = load_validated_json(json_file, dict, {}, test_logger)

        assert result == {}

    def test_missing_file_with_list_default(
        self, cache_dir: Path, test_logger: logging.Logger
    ) -> None:
        """Missing file with list default returns list."""
        json_file = cache_dir / "nonexistent.json"

        default = ["default", "list"]
        result = load_validated_json(json_file, list, default, test_logger)

        assert result == default


class TestLoadValidatedJsonInvalidJson:
    """Tests for handling invalid JSON."""

    def test_invalid_json_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Invalid JSON file returns default and logs error."""
        json_file = cache_dir / "bad.json"
        json_file.write_text("{ invalid json")

        default = {"default": "value"}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default

        # Verify error was logged
        assert "Failed to load" in caplog.text
        assert str(json_file) in caplog.text

    def test_empty_file_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Empty file returns default and logs error."""
        json_file = cache_dir / "empty.json"
        json_file.write_text("")

        default = {"default": "value"}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default
        assert "Failed to load" in caplog.text

    def test_json_parse_error_with_list_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """JSON decode error with list default returns list and logs."""
        json_file = cache_dir / "bad.json"
        json_file.write_text("[invalid, json,")

        default = []
        result = load_validated_json(json_file, list, default, test_logger)

        assert result == default
        assert "Failed to load" in caplog.text


class TestLoadValidatedJsonWrongType:
    """Tests for type validation."""

    def test_dict_when_list_expected_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Dict in file when list expected returns default and logs."""
        json_file = cache_dir / "data.json"
        data = {"key": "value"}
        json_file.write_text(json.dumps(data))

        default = []
        result = load_validated_json(json_file, list, default, test_logger)

        assert result == default
        assert "Expected list in" in caplog.text
        assert "got dict" in caplog.text

    def test_list_when_dict_expected_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """List in file when dict expected returns default and logs."""
        json_file = cache_dir / "data.json"
        data = ["item1", "item2"]
        json_file.write_text(json.dumps(data))

        default = {}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default
        assert "Expected dict in" in caplog.text
        assert "got list" in caplog.text

    def test_string_when_dict_expected_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """String in file when dict expected returns default and logs."""
        json_file = cache_dir / "data.json"
        json_file.write_text('"just a string"')

        default = {}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default
        assert "Expected dict in" in caplog.text
        assert "got str" in caplog.text

    def test_number_when_list_expected_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Number in file when list expected returns default and logs."""
        json_file = cache_dir / "data.json"
        json_file.write_text("42")

        default = []
        result = load_validated_json(json_file, list, default, test_logger)

        assert result == default
        assert "Expected list in" in caplog.text
        assert "got int" in caplog.text

    def test_null_when_dict_expected_returns_default(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """null in file when dict expected returns default and logs."""
        json_file = cache_dir / "data.json"
        json_file.write_text("null")

        default = {}
        result = load_validated_json(json_file, dict, default, test_logger)

        assert result == default
        assert "Expected dict in" in caplog.text
        assert "got NoneType" in caplog.text


class TestLoadValidatedJsonLogging:
    """Tests for error logging behavior."""

    def test_error_includes_file_path(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Error log includes the file path."""
        json_file = cache_dir / "data.json"
        json_file.write_text("{ bad json")

        load_validated_json(json_file, dict, {}, test_logger)

        assert str(json_file) in caplog.text

    def test_type_error_includes_expected_and_actual_types(
        self,
        cache_dir: Path,
        test_logger: logging.Logger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Type error log includes both expected and actual types."""
        json_file = cache_dir / "data.json"
        json_file.write_text('["list", "data"]')

        load_validated_json(json_file, dict, {}, test_logger)

        assert "dict" in caplog.text
        assert "list" in caplog.text
