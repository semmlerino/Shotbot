"""Unit tests for launcher/repository.py.

Tests for LauncherRepository which provides CRUD operations for custom launchers
with persistence via LauncherConfigManager.

Following UNIFIED_TESTING_V2.MD best practices:
- Test behavior, not implementation
- Use test doubles for ConfigManager (test in isolation)
- Test CRUD operations, rollback on failure, and query methods
"""

from __future__ import annotations

import uuid

import pytest

from launcher.models import CustomLauncher
from launcher.repository import LauncherRepository


pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ============================================================================
# Test Doubles
# ============================================================================


class ConfigManagerDouble:
    """Test double for LauncherConfigManager.

    Provides in-memory storage instead of file-based persistence.
    Allows failure injection for testing error handling.
    """

    __test__ = False  # Prevent pytest from collecting as test class

    def __init__(self) -> None:
        self._launchers: dict[str, CustomLauncher] = {}
        self._load_count = 0
        self._save_count = 0
        self._should_fail_save = False
        self._should_fail_load = False

    def load_launchers(self) -> dict[str, CustomLauncher]:
        """Load launchers from in-memory storage."""
        self._load_count += 1
        if self._should_fail_load:
            return {}
        return dict(self._launchers)

    def save_launchers(self, launchers: dict[str, CustomLauncher]) -> bool:
        """Save launchers to in-memory storage."""
        self._save_count += 1
        if self._should_fail_save:
            return False
        self._launchers = dict(launchers)
        return True

    def set_failure_mode(
        self, load_fail: bool = False, save_fail: bool = False
    ) -> None:
        """Configure failure injection."""
        self._should_fail_load = load_fail
        self._should_fail_save = save_fail

    def get_stats(self) -> dict[str, int]:
        """Get operation statistics."""
        return {
            "load_count": self._load_count,
            "save_count": self._save_count,
        }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def config_manager_double() -> ConfigManagerDouble:
    """Create a ConfigManager test double."""
    return ConfigManagerDouble()


@pytest.fixture
def repository(
    config_manager_double: ConfigManagerDouble,
) -> LauncherRepository:
    """Create a repository with the test double config manager."""
    # Type ignore needed since we're using a test double
    return LauncherRepository(config_manager_double)  # type: ignore[arg-type]


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
def populated_repository(
    config_manager_double: ConfigManagerDouble,
) -> LauncherRepository:
    """Create a repository pre-populated with launchers."""
    # Pre-populate the config manager
    for i in range(3):
        launcher = CustomLauncher(
            id=f"launcher-{i}",
            name=f"Launcher {i}",
            command=f"command-{i}",
            description=f"Description {i}",
            category="test" if i < 2 else "other",
        )
        config_manager_double._launchers[launcher.id] = launcher

    return LauncherRepository(config_manager_double)  # type: ignore[arg-type]


# ============================================================================
# Test Initialization
# ============================================================================


class TestRepositoryInitialization:
    """Test LauncherRepository initialization."""

    def test_init_loads_launchers_from_config(
        self, config_manager_double: ConfigManagerDouble
    ) -> None:
        """Test that initialization loads launchers from config manager."""
        # Pre-populate config
        launcher = CustomLauncher(
            id="existing-1",
            name="Existing",
            command="cmd",
            description="",
            category="",
        )
        config_manager_double._launchers["existing-1"] = launcher

        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]

        assert repository.count() == 1
        assert repository.get("existing-1") is not None
        assert config_manager_double.get_stats()["load_count"] == 1

    def test_init_with_empty_config(
        self, config_manager_double: ConfigManagerDouble
    ) -> None:
        """Test initialization with no existing launchers."""
        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]
        assert repository.count() == 0


# ============================================================================
# Test Create Operation
# ============================================================================


class TestCreateOperation:
    """Test launcher creation."""

    def test_create_adds_launcher_to_repository(
        self, repository: LauncherRepository, sample_launcher: CustomLauncher
    ) -> None:
        """Test that create adds launcher and persists."""
        result = repository.create(sample_launcher)

        assert result is True
        assert repository.count() == 1
        assert repository.get(sample_launcher.id) is not None

    def test_create_generates_id_if_missing(
        self, repository: LauncherRepository
    ) -> None:
        """Test that create generates ID if launcher has no ID."""
        launcher = CustomLauncher(
            id="",  # Empty ID
            name="No ID Launcher",
            command="cmd",
            description="",
            category="",
        )

        result = repository.create(launcher)

        assert result is True
        assert launcher.id != ""
        # Verify it's a valid UUID
        uuid.UUID(launcher.id)

    def test_create_rejects_duplicate_id(
        self, repository: LauncherRepository, sample_launcher: CustomLauncher
    ) -> None:
        """Test that create rejects launcher with existing ID."""
        repository.create(sample_launcher)

        duplicate = CustomLauncher(
            id=sample_launcher.id,  # Same ID
            name="Duplicate",
            command="cmd",
            description="",
            category="",
        )

        result = repository.create(duplicate)

        assert result is False
        assert repository.count() == 1  # Still only one

    def test_create_rolls_back_on_save_failure(
        self, config_manager_double: ConfigManagerDouble, sample_launcher: CustomLauncher
    ) -> None:
        """Test that create rolls back if save fails."""
        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]
        config_manager_double.set_failure_mode(save_fail=True)

        result = repository.create(sample_launcher)

        assert result is False
        assert repository.count() == 0  # Rollback occurred

    def test_create_persists_to_storage(
        self,
        repository: LauncherRepository,
        config_manager_double: ConfigManagerDouble,
        sample_launcher: CustomLauncher,
    ) -> None:
        """Test that create saves to config manager."""
        initial_save_count = config_manager_double.get_stats()["save_count"]

        repository.create(sample_launcher)

        assert config_manager_double.get_stats()["save_count"] == initial_save_count + 1
        assert sample_launcher.id in config_manager_double._launchers


# ============================================================================
# Test Update Operation
# ============================================================================


class TestUpdateOperation:
    """Test launcher update."""

    def test_update_modifies_existing_launcher(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that update modifies an existing launcher."""
        launcher = populated_repository.get("launcher-0")
        assert launcher is not None

        updated = CustomLauncher(
            id="launcher-0",
            name="Updated Name",
            command="updated-command",
            description="Updated",
            category="updated",
        )

        result = populated_repository.update(updated)

        assert result is True
        retrieved = populated_repository.get("launcher-0")
        assert retrieved is not None
        assert retrieved.name == "Updated Name"
        assert retrieved.command == "updated-command"

    def test_update_nonexistent_launcher_fails(
        self, repository: LauncherRepository
    ) -> None:
        """Test that update fails for non-existent launcher."""
        launcher = CustomLauncher(
            id="nonexistent",
            name="Ghost",
            command="cmd",
            description="",
            category="",
        )

        result = repository.update(launcher)

        assert result is False

    def test_update_rolls_back_on_save_failure(
        self, config_manager_double: ConfigManagerDouble
    ) -> None:
        """Test that update rolls back if save fails."""
        # Pre-populate
        original = CustomLauncher(
            id="launcher-1",
            name="Original",
            command="original-cmd",
            description="",
            category="",
        )
        config_manager_double._launchers["launcher-1"] = original

        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]
        config_manager_double.set_failure_mode(save_fail=True)

        updated = CustomLauncher(
            id="launcher-1",
            name="Updated",
            command="updated-cmd",
            description="",
            category="",
        )
        result = repository.update(updated)

        assert result is False
        # Original should be restored
        retrieved = repository.get("launcher-1")
        assert retrieved is not None
        assert retrieved.name == "Original"


# ============================================================================
# Test Delete Operation
# ============================================================================


class TestDeleteOperation:
    """Test launcher deletion."""

    def test_delete_removes_launcher(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that delete removes a launcher."""
        assert populated_repository.exists("launcher-0")

        result = populated_repository.delete("launcher-0")

        assert result is True
        assert not populated_repository.exists("launcher-0")
        assert populated_repository.count() == 2

    def test_delete_nonexistent_launcher_fails(
        self, repository: LauncherRepository
    ) -> None:
        """Test that delete fails for non-existent launcher."""
        result = repository.delete("nonexistent")
        assert result is False

    def test_delete_rolls_back_on_save_failure(
        self, config_manager_double: ConfigManagerDouble
    ) -> None:
        """Test that delete rolls back if save fails."""
        # Pre-populate
        launcher = CustomLauncher(
            id="launcher-1",
            name="To Delete",
            command="cmd",
            description="",
            category="",
        )
        config_manager_double._launchers["launcher-1"] = launcher

        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]
        config_manager_double.set_failure_mode(save_fail=True)

        result = repository.delete("launcher-1")

        assert result is False
        # Launcher should still exist (rollback)
        assert repository.exists("launcher-1")


# ============================================================================
# Test Query Operations
# ============================================================================


class TestQueryOperations:
    """Test launcher query methods."""

    def test_get_returns_launcher_by_id(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that get returns launcher by ID."""
        launcher = populated_repository.get("launcher-1")

        assert launcher is not None
        assert launcher.id == "launcher-1"
        assert launcher.name == "Launcher 1"

    def test_get_returns_none_for_missing_id(
        self, repository: LauncherRepository
    ) -> None:
        """Test that get returns None for missing ID."""
        result = repository.get("nonexistent")
        assert result is None

    def test_get_by_name_returns_launcher(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that get_by_name returns matching launcher."""
        launcher = populated_repository.get_by_name("Launcher 1")

        assert launcher is not None
        assert launcher.name == "Launcher 1"

    def test_get_by_name_returns_none_for_missing_name(
        self, repository: LauncherRepository
    ) -> None:
        """Test that get_by_name returns None for missing name."""
        result = repository.get_by_name("Nonexistent")
        assert result is None

    def test_list_all_returns_all_launchers(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that list_all returns all launchers."""
        launchers = populated_repository.list_all()

        assert len(launchers) == 3
        names = [launcher.name for launcher in launchers]
        assert "Launcher 0" in names
        assert "Launcher 1" in names
        assert "Launcher 2" in names

    def test_list_all_filters_by_category(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that list_all filters by category."""
        test_launchers = populated_repository.list_all(category="test")
        other_launchers = populated_repository.list_all(category="other")

        assert len(test_launchers) == 2
        assert len(other_launchers) == 1

    def test_list_all_returns_sorted_by_name(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that list_all returns launchers sorted by name."""
        launchers = populated_repository.list_all()

        names = [launcher.name for launcher in launchers]
        assert names == sorted(names, key=str.lower)

    def test_get_categories_returns_unique_categories(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that get_categories returns unique categories."""
        categories = populated_repository.get_categories()

        assert len(categories) == 2
        assert "test" in categories
        assert "other" in categories

    def test_exists_returns_true_for_existing_id(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that exists returns True for existing ID."""
        assert populated_repository.exists("launcher-0") is True

    def test_exists_returns_false_for_missing_id(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that exists returns False for missing ID."""
        assert populated_repository.exists("nonexistent") is False

    def test_count_returns_launcher_count(
        self, populated_repository: LauncherRepository
    ) -> None:
        """Test that count returns correct launcher count."""
        assert populated_repository.count() == 3


# ============================================================================
# Test Reload Operation
# ============================================================================


class TestReloadOperation:
    """Test launcher reload from storage."""

    def test_reload_refreshes_from_config(
        self, config_manager_double: ConfigManagerDouble
    ) -> None:
        """Test that reload refreshes launchers from config."""
        repository = LauncherRepository(config_manager_double)  # type: ignore[arg-type]
        assert repository.count() == 0

        # Add launcher directly to config (simulating external change)
        config_manager_double._launchers["external-1"] = CustomLauncher(
            id="external-1",
            name="External",
            command="cmd",
            description="",
            category="",
        )

        repository.reload()

        assert repository.count() == 1
        assert repository.get("external-1") is not None
