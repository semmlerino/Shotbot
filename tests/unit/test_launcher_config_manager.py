"""Unit tests for launcher/config_manager.py.

Tests for LauncherConfigManager which handles persistence of custom launcher
configurations to JSON files.

Following UNIFIED_TESTING_V2.MD best practices:
- Test behavior, not implementation
- Cover initialization, loading, saving, and error handling
- Test round-trip serialization/deserialization
- Use tmp_path fixture for file operations
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from launcher.config_manager import CONFIG_DIR_ENV_VAR, LauncherConfigManager
from launcher.models import CustomLauncher


pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def config_manager(tmp_path: Path) -> LauncherConfigManager:
    """Create a config manager with a temporary directory."""
    return LauncherConfigManager(config_dir=tmp_path)


@pytest.fixture
def sample_launcher() -> CustomLauncher:
    """Create a sample launcher for testing."""
    return CustomLauncher(
        id="test-launcher-1",
        name="Test Launcher",
        command="echo {shot_name}",
        description="A test launcher",
        category="test",
    )


@pytest.fixture
def sample_launcher_dict() -> dict[str, Any]:
    """Create sample launcher data as dictionary.

    This matches the minimal format saved by LauncherConfigManager.
    Note: 'parameters' field is NOT included as CustomLauncher doesn't accept it
    directly - parameters are handled via LauncherParameter objects.
    """
    return {
        "name": "Test Launcher",
        "command": "echo {shot_name}",
        "description": "A test launcher",
        "category": "test",
        "environment": {
            "type": "bash",
            "packages": [],
            "source_files": [],
            "command_prefix": None,
        },
        "terminal": {
            "required": False,
            "persist": False,
            "title": None,
        },
        "validation": {
            "check_executable": True,
            "required_files": [],
            "forbidden_patterns": [],
            "working_directory": None,
            "resolve_paths": False,
        },
    }


# ============================================================================
# Test Initialization
# ============================================================================


class TestConfigManagerInitialization:
    """Test LauncherConfigManager initialization."""

    def test_init_with_explicit_config_dir(self, tmp_path: Path) -> None:
        """Test initialization with explicit config directory."""
        manager = LauncherConfigManager(config_dir=tmp_path)
        assert manager.config_dir == tmp_path
        assert manager.config_file == tmp_path / "custom_launchers.json"

    def test_init_creates_config_directory(self, tmp_path: Path) -> None:
        """Test that initialization creates the config directory if it doesn't exist."""
        config_dir = tmp_path / "new_config_dir"
        assert not config_dir.exists()

        manager = LauncherConfigManager(config_dir=config_dir)
        assert config_dir.exists()
        assert manager.config_dir == config_dir

    def test_init_with_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test initialization with environment variable override."""
        env_dir = tmp_path / "env_config"
        monkeypatch.setenv(CONFIG_DIR_ENV_VAR, str(env_dir))

        manager = LauncherConfigManager()  # No explicit config_dir
        assert manager.config_dir == env_dir
        assert env_dir.exists()

    def test_init_with_home_dir_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test initialization defaults to ~/.shotbot."""
        # Remove env var if set
        monkeypatch.delenv(CONFIG_DIR_ENV_VAR, raising=False)
        # Mock home directory
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        manager = LauncherConfigManager()
        assert manager.config_dir == tmp_path / ".shotbot"


# ============================================================================
# Test Loading Launchers
# ============================================================================


class TestLoadLaunchers:
    """Test loading launchers from configuration file."""

    def test_load_launchers_nonexistent_file(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test loading when config file doesn't exist returns empty dict."""
        result = config_manager.load_launchers()
        assert result == {}

    def test_load_launchers_empty_file(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test loading from empty file returns empty dict (handles gracefully)."""
        # Create empty config file
        config_manager.config_file.write_text("")

        result = config_manager.load_launchers()
        assert result == {}

    def test_load_launchers_valid_json(
        self, config_manager: LauncherConfigManager, sample_launcher_dict: dict[str, Any]
    ) -> None:
        """Test loading valid launcher data from JSON."""
        config_data = {
            "version": "1.0",
            "launchers": {
                "launcher-1": sample_launcher_dict,
            },
            "terminal_preferences": ["gnome-terminal"],
        }
        config_manager.config_file.write_text(json.dumps(config_data))

        result = config_manager.load_launchers()
        assert len(result) == 1
        assert "launcher-1" in result
        launcher = result["launcher-1"]
        assert launcher.name == "Test Launcher"
        assert launcher.command == "echo {shot_name}"
        assert launcher.id == "launcher-1"

    def test_load_launchers_multiple_launchers(
        self, config_manager: LauncherConfigManager, sample_launcher_dict: dict[str, Any]
    ) -> None:
        """Test loading multiple launchers."""
        launcher2_dict = sample_launcher_dict.copy()
        launcher2_dict["name"] = "Second Launcher"
        launcher2_dict["command"] = "python script.py"

        config_data = {
            "version": "1.0",
            "launchers": {
                "launcher-1": sample_launcher_dict,
                "launcher-2": launcher2_dict,
            },
            "terminal_preferences": [],
        }
        config_manager.config_file.write_text(json.dumps(config_data))

        result = config_manager.load_launchers()
        assert len(result) == 2
        assert "launcher-1" in result
        assert "launcher-2" in result
        assert result["launcher-1"].name == "Test Launcher"
        assert result["launcher-2"].name == "Second Launcher"

    def test_load_launchers_malformed_json(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test loading malformed JSON returns empty dict."""
        config_manager.config_file.write_text("{ invalid json }")

        result = config_manager.load_launchers()
        assert result == {}

    def test_load_launchers_missing_launchers_key(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test loading JSON without 'launchers' key returns empty dict."""
        config_data = {"version": "1.0"}
        config_manager.config_file.write_text(json.dumps(config_data))

        result = config_manager.load_launchers()
        assert result == {}

    def test_load_launchers_invalid_launchers_type(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test loading with invalid launchers data type returns empty dict."""
        config_data = {
            "version": "1.0",
            "launchers": ["not", "a", "dict"],  # Should be dict
        }
        config_manager.config_file.write_text(json.dumps(config_data))

        result = config_manager.load_launchers()
        assert result == {}


# ============================================================================
# Test Saving Launchers
# ============================================================================


class TestSaveLaunchers:
    """Test saving launchers to configuration file."""

    def test_save_launchers_creates_valid_json(
        self, config_manager: LauncherConfigManager, sample_launcher: CustomLauncher
    ) -> None:
        """Test that save creates valid JSON file."""
        launchers = {"test-launcher-1": sample_launcher}

        result = config_manager.save_launchers(launchers)
        assert result is True
        assert config_manager.config_file.exists()

        # Verify JSON is valid and parseable
        with config_manager.config_file.open() as f:
            data = json.load(f)
        assert "version" in data
        assert "launchers" in data
        assert "test-launcher-1" in data["launchers"]

    def test_save_launchers_includes_all_fields(
        self, config_manager: LauncherConfigManager, sample_launcher: CustomLauncher
    ) -> None:
        """Test that save includes all launcher fields."""
        launchers = {"test-launcher-1": sample_launcher}

        config_manager.save_launchers(launchers)

        with config_manager.config_file.open() as f:
            data = json.load(f)

        launcher_data = data["launchers"]["test-launcher-1"]
        assert launcher_data["name"] == "Test Launcher"
        assert launcher_data["command"] == "echo {shot_name}"
        assert launcher_data["description"] == "A test launcher"
        assert launcher_data["category"] == "test"
        # ID should NOT be in nested dict (it's the key)
        assert "id" not in launcher_data

    def test_save_launchers_empty_dict(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test saving empty launcher dict creates valid config."""
        result = config_manager.save_launchers({})
        assert result is True

        with config_manager.config_file.open() as f:
            data = json.load(f)
        assert data["launchers"] == {}

    def test_save_launchers_multiple_launchers(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test saving multiple launchers."""
        launcher1 = CustomLauncher(
            id="id-1",
            name="Launcher 1",
            command="cmd1",
            description="First",
            category="cat1",
        )
        launcher2 = CustomLauncher(
            id="id-2",
            name="Launcher 2",
            command="cmd2",
            description="Second",
            category="cat2",
        )
        launchers = {"id-1": launcher1, "id-2": launcher2}

        result = config_manager.save_launchers(launchers)
        assert result is True

        with config_manager.config_file.open() as f:
            data = json.load(f)
        assert len(data["launchers"]) == 2
        assert "id-1" in data["launchers"]
        assert "id-2" in data["launchers"]


# ============================================================================
# Test Round-Trip (Save and Load)
# ============================================================================


class TestRoundTrip:
    """Test save/load round-trip preserves launcher data."""

    def test_round_trip_preserves_exact_state(
        self, config_manager: LauncherConfigManager, sample_launcher: CustomLauncher
    ) -> None:
        """Test that save followed by load returns identical data."""
        original_launchers = {"test-launcher-1": sample_launcher}

        # Save
        save_result = config_manager.save_launchers(original_launchers)
        assert save_result is True

        # Load
        loaded_launchers = config_manager.load_launchers()

        assert len(loaded_launchers) == 1
        assert "test-launcher-1" in loaded_launchers

        loaded = loaded_launchers["test-launcher-1"]
        assert loaded.name == sample_launcher.name
        assert loaded.command == sample_launcher.command
        assert loaded.description == sample_launcher.description
        assert loaded.category == sample_launcher.category
        assert loaded.id == sample_launcher.id

    def test_round_trip_multiple_launchers(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test round-trip with multiple launchers."""
        launchers = {
            f"launcher-{i}": CustomLauncher(
                id=f"launcher-{i}",
                name=f"Launcher {i}",
                command=f"command {i}",
                description=f"Description {i}",
                category="test",
            )
            for i in range(5)
        }

        config_manager.save_launchers(launchers)
        loaded = config_manager.load_launchers()

        assert len(loaded) == 5
        for i in range(5):
            launcher_id = f"launcher-{i}"
            assert launcher_id in loaded
            assert loaded[launcher_id].name == f"Launcher {i}"


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_ensure_config_dir_handles_existing_dir(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test that _ensure_config_dir handles existing directory."""
        # Directory already exists from fixture
        assert config_manager.config_dir.exists()

        # Should not raise
        config_manager._ensure_config_dir()
        assert config_manager.config_dir.exists()

    def test_save_launchers_permission_error(
        self, tmp_path: Path, sample_launcher: CustomLauncher
    ) -> None:
        """Test save handles permission errors gracefully."""
        # Create a read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        manager = LauncherConfigManager(config_dir=readonly_dir)

        # Make directory read-only
        readonly_dir.chmod(0o444)

        try:
            result = manager.save_launchers({"id-1": sample_launcher})
            # Should return False on error, not raise
            assert result is False
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_load_handles_corrupt_launcher_data(
        self, config_manager: LauncherConfigManager
    ) -> None:
        """Test load handles corrupt launcher data gracefully."""
        # Valid JSON structure but invalid launcher data (missing required fields)
        config_data = {
            "version": "1.0",
            "launchers": {
                "bad-launcher": {
                    # Missing required fields
                    "some_field": "value",
                },
            },
        }
        config_manager.config_file.write_text(json.dumps(config_data))

        # Should return empty dict on error, not raise
        result = config_manager.load_launchers()
        assert result == {}
