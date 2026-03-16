"""Unit tests for BaseShotModel - base class for all shot models.

Following UNIFIED_TESTING_GUIDE best practices:
- Test behavior, not implementation
- Use real components (CacheManager with tmp_path)
- Use QSignalSpy for signal testing
- Test doubles for system boundaries (ProcessPoolManager)
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QSignalSpy

from base_shot_model import BaseShotModel
from config import Config
from type_definitions import RefreshResult, Shot


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.fast,
]


# Concrete implementation for testing abstract base class
class ConcreteTestModel(BaseShotModel):
    """Minimal concrete implementation for testing BaseShotModel."""

    def __init__(
        self, cache_manager: object | None = None, load_cache: bool = True
    ) -> None:
        super().__init__(cache_manager, load_cache)
        self._load_result = RefreshResult(success=True, has_changes=False)
        self._refresh_result = RefreshResult(success=True, has_changes=False)

    def load_shots(self) -> RefreshResult:
        """Implement abstract method for testing."""
        return self._load_result

    def refresh_strategy(self) -> RefreshResult:
        """Implement abstract method for testing."""
        # Simulate simple refresh that doesn't change shots
        return self._refresh_result


class TestBaseShotModelInitialization:
    """Test BaseShotModel initialization behavior."""

    def test_initialization_loads_cache_by_default(
        self, shot_cache: object
    ) -> None:
        """Test that load_cache=True loads from cache."""
        # Pre-populate cache
        test_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]
        shot_cache.cache_shots(test_shots)

        # Create model with cache loading enabled
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=True)

        # Should have loaded shots from cache
        assert len(model.shots) == 2
        assert model.shots[0].shot == "0010"
        assert model.shots[1].shot == "0020"

    def test_initialization_without_cache_loading(
        self, shot_cache: object
    ) -> None:
        """Test load_cache=False skips cache."""
        # Pre-populate cache
        test_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        ]
        shot_cache.cache_shots(test_shots)

        # Create model with cache loading disabled
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        # Should NOT have loaded from cache
        assert len(model.shots) == 0


class TestCacheLoading:
    """Test cache loading behavior."""

    def test_load_from_cache_success(self, shot_cache: object) -> None:
        """Test successful cache loading."""
        test_shots = [
            Shot("SHOW1", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0010"),
            Shot("SHOW1", "seq01", "0020", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0020"),
        ]
        shot_cache.cache_shots(test_shots)

        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        # Test signal emission
        spy = QSignalSpy(model.shots_loaded)

        # Load from cache
        result = model._load_from_cache()

        assert result is True
        assert len(model.shots) == 2
        assert spy.count() == 1
        assert len(spy.at(0)[0]) == 2  # Signal emitted with 2 shots

    def test_load_from_cache_empty(self, shot_cache: object) -> None:
        """Test cache loading when cache is empty."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        result = model._load_from_cache()

        assert result is False
        assert len(model.shots) == 0

    def test_cache_metrics_tracking(self, shot_cache: object) -> None:
        """Test that cache hits/misses are tracked."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        # Initial state
        metrics = model.get_performance_metrics()
        assert metrics["cache_hits"] == 0
        assert metrics["cache_misses"] == 0

        # Miss (no cache)
        model._load_from_cache()
        metrics = model.get_performance_metrics()
        assert metrics["cache_misses"] == 1

        # Hit (with cache)
        test_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        ]
        shot_cache.cache_shots(test_shots)
        model._load_from_cache()
        metrics = model.get_performance_metrics()
        assert metrics["cache_hits"] == 1
        assert metrics["cache_hit_rate"] == 0.5  # 1 hit, 1 miss


class TestChangeDetection:
    """Test shot change detection logic."""

    def test_check_for_changes_no_change(self, shot_cache: object) -> None:
        """Test when shot list hasn't changed."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]
        model.shots = shots

        # Same shots
        has_changes = model._check_for_changes(shots)
        assert has_changes is False

    def test_check_for_changes_added_shot(self, shot_cache: object) -> None:
        """Test when shot is added."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
        ]

        new_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]

        has_changes = model._check_for_changes(new_shots)
        assert has_changes is True

    def test_check_for_changes_removed_shot(self, shot_cache: object) -> None:
        """Test when shot is removed."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]

        new_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
        ]

        has_changes = model._check_for_changes(new_shots)
        assert has_changes is True

    def test_check_for_changes_workspace_path_change(
        self, shot_cache: object
    ) -> None:
        """Test when workspace path changes."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
        ]

        new_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01_new/seq01_0010"),
        ]

        has_changes = model._check_for_changes(new_shots)
        assert has_changes is True


class TestShotManagement:
    """Test shot management methods."""

    def test_get_shots(self, shot_cache: object) -> None:
        """Test get_shots returns current shots."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        test_shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        ]
        model.shots = test_shots

        assert model.get_shots() == test_shots

    def test_get_shot_count(self, shot_cache: object) -> None:
        """Test get_shot_count returns correct count."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        assert model.get_shot_count() == 0

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]

        assert model.get_shot_count() == 2

    def test_find_shot_by_name_found(self, shot_cache: object) -> None:
        """Test finding shot by full name."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        shot1 = Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        shot2 = Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020")
        model.shots = [shot1, shot2]

        found = model.find_shot_by_name("seq01_0020")
        assert found is shot2

    def test_find_shot_by_name_not_found(self, shot_cache: object) -> None:
        """Test finding non-existent shot."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010")
        ]

        found = model.find_shot_by_name("nonexistent")
        assert found is None


class TestFiltering:
    """Test show and text filtering."""

    def test_show_filter(self, shot_cache: object) -> None:
        """Test show filtering."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("SHOW1", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0010"),
            Shot("SHOW1", "seq01", "0020", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0020"),
            Shot("SHOW2", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW2/shots/seq01/seq01_0010"),
        ]

        # No filter
        assert len(model.get_filtered_shots()) == 3

        # Filter by SHOW1
        model.set_show_filter("SHOW1")
        assert model.get_show_filter() == "SHOW1"
        filtered = model.get_filtered_shots()
        assert len(filtered) == 2
        assert all(s.show == "SHOW1" for s in filtered)

        # Clear filter
        model.set_show_filter(None)
        assert len(model.get_filtered_shots()) == 3

    def test_text_filter(self, shot_cache: object) -> None:
        """Test text filtering."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
            Shot("TEST", "seq02", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq02/seq02_0010"),
        ]

        # No filter
        assert len(model.get_filtered_shots()) == 3

        # Filter by "seq01"
        model.set_text_filter("seq01")
        assert model.get_text_filter() == "seq01"
        filtered = model.get_filtered_shots()
        assert len(filtered) == 2
        assert all("seq01" in s.full_name for s in filtered)

        # Case-insensitive
        model.set_text_filter("SEQ01")
        filtered = model.get_filtered_shots()
        assert len(filtered) == 2

    def test_combined_filters(self, shot_cache: object) -> None:
        """Test combining show and text filters."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("SHOW1", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0010"),
            Shot("SHOW1", "seq02", "0020", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq02/seq02_0020"),
            Shot("SHOW2", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW2/shots/seq01/seq01_0010"),
        ]

        # Both filters
        model.set_show_filter("SHOW1")
        model.set_text_filter("seq01")

        filtered = model.get_filtered_shots()
        assert len(filtered) == 1
        assert filtered[0].show == "SHOW1"
        assert "seq01" in filtered[0].full_name


class TestPerformanceMetrics:
    """Test performance metrics tracking."""

    def test_get_performance_metrics(self, shot_cache: object) -> None:
        """Test performance metrics returns correct data."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("TEST", "seq01", "0010", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0010"),
            Shot("TEST", "seq01", "0020", f"{Config.SHOWS_ROOT}/TEST/shots/seq01/seq01_0020"),
        ]

        metrics = model.get_performance_metrics()

        assert metrics["total_shots"] == 2
        assert metrics["total_refreshes"] == 0
        assert metrics["cache_hit_rate"] >= 0.0
        assert "cache_hits" in metrics
        assert "cache_misses" in metrics

    def test_refresh_increments_counter(self, shot_cache: object) -> None:
        """Test refresh_shots increments counter."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        assert model.get_performance_metrics()["total_refreshes"] == 0

        model.refresh_shots()
        assert model.get_performance_metrics()["total_refreshes"] == 1

        model.refresh_shots()
        assert model.get_performance_metrics()["total_refreshes"] == 2


class TestAvailableShows:
    """Test available shows extraction."""

    def test_get_available_shows(self, shot_cache: object) -> None:
        """Test getting unique show names."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        model.shots = [
            Shot("SHOW1", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0010"),
            Shot("SHOW1", "seq01", "0020", f"{Config.SHOWS_ROOT}/SHOW1/shots/seq01/seq01_0020"),
            Shot("SHOW2", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW2/shots/seq01/seq01_0010"),
            Shot("SHOW3", "seq01", "0010", f"{Config.SHOWS_ROOT}/SHOW3/shots/seq01/seq01_0010"),
        ]

        shows = model.get_available_shows()

        assert len(shows) == 3
        assert "SHOW1" in shows
        assert "SHOW2" in shows
        assert "SHOW3" in shows

    def test_get_available_shows_empty(self, shot_cache: object) -> None:
        """Test getting shows when no shots."""
        model = ConcreteTestModel(cache_manager=shot_cache, load_cache=False)

        shows = model.get_available_shows()
        assert len(shows) == 0
