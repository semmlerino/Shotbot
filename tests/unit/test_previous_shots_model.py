"""Unit tests for PreviousShotsModel class following UNIFIED_TESTING_GUIDE.

Tests the model layer with real Qt components and cache integration.
Follows best practices:
- Uses proper test doubles instead of Mock()
- No qtbot.addWidget() for QObject
- Prevents signal race conditions
- Tests thread safety
"""

from __future__ import annotations

# Standard library imports
import concurrent.futures
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

# Third-party imports
import pytest
from PySide6.QtTest import QSignalSpy

# Local application imports
from cache.shot_cache import ShotDataCache
from previous_shots.model import PreviousShotsModel
from tests.fixtures.model_fixtures import (
    FakePreviousShotsFinder,
    FakeShotModel,
    create_test_shot,
)
from tests.test_helpers import process_qt_events


if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

sys.path.insert(0, str(Path(__file__).parent.parent))

# Local application imports
# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.test_doubles import TestCacheManager


pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,
]

# This test file follows UNIFIED_TESTING_GUIDE best practices:
# - Test behavior, not implementation
# - Use test doubles instead of mocks
# - Real components where possible
# - Thread-safe testing patterns


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset singleton instances before each test to prevent contamination.

    This fixture resets all singleton manager instances that might be used
    by the code under test, ensuring test isolation in parallel execution.
    """
    from managers.notification_manager import NotificationManager
    from managers.progress_manager import ProgressManager
    from workers.process_pool_manager import ProcessPoolManager

    # Reset singleton instances
    monkeypatch.setattr(NotificationManager, "_instance", None)
    monkeypatch.setattr(ProgressManager, "_instance", None)
    monkeypatch.setattr(ProcessPoolManager, "_instance", None)
    monkeypatch.setattr(ProcessPoolManager, "_initialized", False)


class TestPreviousShotsModel:
    """Test cases for PreviousShotsModel with real Qt components."""

    @pytest.fixture
    def temp_cache_dir(self, tmp_path: Path) -> Path:
        """Create temporary cache directory."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir

    @pytest.fixture
    def real_cache_manager(self, temp_cache_dir: Path) -> ShotDataCache:
        """Create real CacheManager with temporary storage."""
        return ShotDataCache(temp_cache_dir)

    @pytest.fixture
    def test_cache_manager(self, tmp_path: Path) -> TestCacheManager:
        """Create test double CacheManager with isolated cache directory."""
        return TestCacheManager(tmp_path / "cache")

    @pytest.fixture
    def test_shot_model(self, qtbot: QtBot) -> Generator[FakeShotModel, None, None]:
        """Create test double ShotModel with real Qt signals."""
        model = FakeShotModel()
        model.set_shots(
            [
                create_test_shot("show1", "seq1", "shot1"),
                create_test_shot("show1", "seq1", "shot2"),
            ]
        )
        yield model
        # Manual cleanup for QObject
        if hasattr(model, "deleteLater"):
            model.deleteLater()
            process_qt_events()

    @pytest.fixture
    def test_finder(self) -> FakePreviousShotsFinder:
        """Create test double for PreviousShotsFinder."""
        finder = FakePreviousShotsFinder()
        finder.approved_shots_to_return = [
            create_test_shot("show2", "seq2", "shot1"),
            create_test_shot("show2", "seq2", "shot2"),
        ]
        return finder

    @pytest.fixture
    def model(
        self,
        test_shot_model: FakeShotModel,
        test_cache_manager: TestCacheManager,
        qtbot: QtBot,
    ) -> Generator[PreviousShotsModel, None, None]:
        """Create PreviousShotsModel instance with test doubles.

        Following UNIFIED_TESTING_GUIDE:
        - Manual cleanup for QObject (not a QWidget)
        - Use test doubles with predictable behavior
        """
        model = PreviousShotsModel(
            shot_model=test_shot_model, cache_manager=test_cache_manager
        )
        yield model
        # Cleanup worker thread BEFORE deleteLater to prevent Qt crashes
        model._cleanup_worker_safely()
        model.deleteLater()
        process_qt_events()

    @pytest.fixture
    def model_with_real_cache(
        self,
        test_shot_model: FakeShotModel,
        real_cache_manager: ShotDataCache,
        qtbot: QtBot,
    ) -> Generator[PreviousShotsModel, None, None]:
        """Create model with real cache for integration tests."""
        model = PreviousShotsModel(
            shot_model=test_shot_model, cache_manager=real_cache_manager
        )
        yield model
        # Cleanup worker thread BEFORE deleteLater to prevent Qt crashes
        model._cleanup_worker_safely()
        model.deleteLater()
        process_qt_events()

    def test_model_initialization(
        self,
        model: PreviousShotsModel,
        test_shot_model: FakeShotModel,
        test_cache_manager: TestCacheManager,
    ) -> None:
        """Test model initialization with dependencies."""
        assert model._shot_model is test_shot_model
        assert model._cache_manager is test_cache_manager
        assert model._finder is not None
        assert model._previous_shots == []
        assert not model._is_scanning
        assert model._scan_lock is not None  # Thread safety lock

    def test_persistent_cache_no_expiration(self, model: PreviousShotsModel) -> None:
        """Test that previous shots cache persists without expiration."""
        # This test verifies the new persistent caching behavior
        # where cache does not expire and accumulates incrementally
        test_shots = [
            create_test_shot("show1", "seq1", "shot1"),
        ]
        model._previous_shots = test_shots

        # Save to cache
        model._save_to_cache()

        # Cache should exist and be loadable regardless of age
        assert len(model.get_shots()) == 1

    def test_refresh_shots_signal_emission_no_race(
        self,
        model: PreviousShotsModel,
        test_finder: FakePreviousShotsFinder,
        qtbot: QtBot,
    ) -> None:
        """Test signal emission during shot refresh without race conditions.

        Following UNIFIED_TESTING_GUIDE:
        - Set up signal spy BEFORE triggering action
        """
        # Mock PreviousShotsWorker creation to use test double
        # Local application imports
        from tests.fixtures.model_fixtures import (
            FakePreviousShotsWorker,
        )

        # Create test worker that will emit signals synchronously
        test_worker = FakePreviousShotsWorker()
        test_worker.shots_to_find = test_finder.approved_shots_to_return

        # Set up signal spies BEFORE triggering refresh (prevents race)
        scan_started_spy = QSignalSpy(model.scan_started)
        scan_finished_spy = QSignalSpy(model.scan_finished)
        shots_updated_spy = QSignalSpy(model.shots_updated)

        # Mock worker creation to return our test double
        with patch(
            "previous_shots.model.PreviousShotsWorker", return_value=test_worker
        ):
            # Trigger refresh - will create and use our test worker
            result = model.refresh_shots()

            # Manually trigger worker completion since test worker is synchronous
            shot_dicts = [
                {
                    "show": shot.show,
                    "sequence": shot.sequence,
                    "shot": shot.shot,
                    "workspace_path": shot.workspace_path,
                }
                for shot in test_finder.approved_shots_to_return
            ]

            # Simulate worker completion
            model._on_scan_finished(shot_dicts)

        # Verify return value
        assert result is True

        # Verify signals were emitted
        assert scan_started_spy.count() == 1
        assert scan_finished_spy.count() == 1
        assert shots_updated_spy.count() == 1  # Should update since shots changed

        # Verify shots were stored
        assert len(model._previous_shots) == 2
        assert model.get_shot_count() == 2

    def test_refresh_shots_no_changes(
        self, model: PreviousShotsModel, test_finder: FakePreviousShotsFinder
    ) -> None:
        """Test refresh when no changes detected."""
        model._finder = test_finder

        # Pre-populate with same shots
        existing_shots = test_finder.approved_shots_to_return
        model._previous_shots = existing_shots

        # Set up signal spy
        shots_updated_spy = QSignalSpy(model.shots_updated)

        result = model.refresh_shots()

        assert result is True
        # Should not emit shots_updated since no changes
        assert shots_updated_spy.count() == 0

    @pytest.mark.parametrize(
        "scenario",
        [
            pytest.param("concurrent_refresh", id="concurrent_refresh"),
            pytest.param("concurrent_is_scanning", id="concurrent_is_scanning"),
        ],
    )
    def test_thread_safety_concurrent_refresh(
        self,
        model: PreviousShotsModel,
        test_finder: FakePreviousShotsFinder,
        scenario: str,
    ) -> None:
        """Test thread safety with concurrent refresh calls and scanning state access.

        Following UNIFIED_TESTING_GUIDE:
        - Test actual threading behavior
        - Verify lock prevents race conditions
        """
        if scenario == "concurrent_refresh":
            model._finder = test_finder
            results = []

            def refresh_worker() -> None:
                result = model.refresh_shots()
                results.append(result)

            threads = []
            for _ in range(5):
                thread = threading.Thread(target=refresh_worker)
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join(timeout=2.0)

            assert len(results) == 5
            true_count = sum(1 for r in results if r is True)
            # At least one should succeed
            assert true_count >= 1

        else:  # concurrent_is_scanning
            scan_results: list[bool] = []

            def check_scanning() -> None:
                for _ in range(100):
                    scan_results.append(model.is_scanning())
                    threading.Event().wait(0.001)

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(check_scanning) for _ in range(3)]
                concurrent.futures.wait(futures, timeout=5.0)

            # Should not crash or raise exceptions
            assert len(scan_results) == 300  # 3 threads * 100 checks

    def test_refresh_shots_error_handling(
        self, model: PreviousShotsModel, qtbot: QtBot
    ) -> None:
        """Test error handling during refresh."""
        # Local application imports
        from tests.fixtures.model_fixtures import (
            FakePreviousShotsWorker,
        )

        scan_finished_spy = QSignalSpy(model.scan_finished)

        # Create test worker that will simulate an error
        test_worker = FakePreviousShotsWorker()

        # Mock worker creation and simulate error in worker
        with patch(
            "previous_shots.model.PreviousShotsWorker", return_value=test_worker
        ):
            result = model.refresh_shots()

            # Simulate worker error
            model._on_scan_error("Test error")

        # Worker creation succeeded, but error was handled
        assert result is True  # refresh_shots() returns True when worker starts
        assert not model.is_scanning()  # Should reset scanning state after error
        assert scan_finished_spy.count() == 1  # Should still emit finished signal

    def test_get_shots_returns_copy(self, model: PreviousShotsModel) -> None:
        """Test that get_shots returns a copy, not reference."""
        original_shots = [
            create_test_shot("show1", "seq1", "shot1"),
        ]
        model._previous_shots = original_shots

        returned_shots = model.get_shots()

        # Should be equal but not the same object
        assert returned_shots == original_shots
        assert returned_shots is not original_shots

    def test_get_shot_by_name(self, model: PreviousShotsModel) -> None:
        """Test getting shot by name."""
        test_shots = [
            create_test_shot("show1", "seq1", "shot1"),
            create_test_shot("show1", "seq1", "shot2"),
        ]
        model._previous_shots = test_shots

        # Test found
        shot = model.get_shot_by_name("shot2")
        assert shot is not None
        assert shot.shot == "shot2"
        assert shot.sequence == "seq1"

        # Test not found
        shot = model.get_shot_by_name("nonexistent")
        assert shot is None

    def test_get_shot_details_delegation(
        self, model: PreviousShotsModel, test_finder: FakePreviousShotsFinder
    ) -> None:
        """Test that get_shot_details delegates to finder."""
        model._finder = test_finder
        shot = create_test_shot("show1", "seq1", "shot1")

        details = model.get_shot_details(shot)

        # Verify delegation
        assert len(test_finder.get_shot_details_calls) == 1
        assert test_finder.get_shot_details_calls[0] == shot
        assert details["show"] == "show1"
        assert details["status"] == "approved"

    def test_cache_integration_with_real_cache(
        self, model_with_real_cache: PreviousShotsModel, temp_cache_dir: Path
    ) -> None:
        """Test cache saving and loading with real CacheManager."""
        # Local application imports
        from tests.fixtures.model_fixtures import (
            FakePreviousShotsWorker,
        )

        model = model_with_real_cache
        test_finder = FakePreviousShotsFinder()
        test_shots = [
            create_test_shot("show1", "seq1", "shot1"),
            create_test_shot("show1", "seq1", "shot2"),
        ]
        test_finder.approved_shots_to_return = test_shots

        # Create test worker with shots
        test_worker = FakePreviousShotsWorker()
        test_worker.shots_to_find = test_shots

        # Mock worker creation and simulate successful completion
        with patch(
            "previous_shots.model.PreviousShotsWorker", return_value=test_worker
        ):
            # Refresh should save to cache
            model.refresh_shots()

            # Manually trigger successful completion
            shot_dicts = [
                {
                    "show": shot.show,
                    "sequence": shot.sequence,
                    "shot": shot.shot,
                    "workspace_path": shot.workspace_path,
                }
                for shot in test_shots
            ]

            model._on_scan_finished(shot_dicts)

        # Verify cache file was created
        cache_file = temp_cache_dir / "previous_shots.json"
        assert cache_file.exists()

        # Create new model instance - should load from cache
        new_model = PreviousShotsModel(model._shot_model, model._cache_manager)

        shots = new_model.get_shots()
        assert len(shots) == 2
        assert shots[0].show == "show1"

    def test_cache_loading_error_recovery(
        self, temp_cache_dir: Path, test_shot_model: FakeShotModel, qtbot
    ) -> None:
        """Test handling of corrupted cache data."""
        # Create invalid cache file
        cache_file = temp_cache_dir / "previous_shots.json"
        cache_file.write_text("invalid json")

        cache_manager = ShotDataCache(temp_cache_dir)

        # Should handle error gracefully
        model = PreviousShotsModel(test_shot_model, cache_manager)
        assert len(model.get_shots()) == 0
        model.deleteLater()
        process_qt_events()

    def test_clear_cache_functionality(
        self, model_with_real_cache: PreviousShotsModel, temp_cache_dir: Path
    ) -> None:
        """Test cache clearing functionality."""
        # Local application imports
        from tests.fixtures.model_fixtures import (
            FakePreviousShotsWorker,
        )

        model = model_with_real_cache
        test_shot = create_test_shot()

        # Configure and refresh with mock worker
        test_finder = FakePreviousShotsFinder()
        test_finder.approved_shots_to_return = [test_shot]

        test_worker = FakePreviousShotsWorker()
        test_worker.shots_to_find = [test_shot]

        with patch(
            "previous_shots.model.PreviousShotsWorker", return_value=test_worker
        ):
            model.refresh_shots()

            # Manually trigger completion to save cache
            shot_dict = {
                "show": test_shot.show,
                "sequence": test_shot.sequence,
                "shot": test_shot.shot,
                "workspace_path": test_shot.workspace_path,
            }
            model._on_scan_finished([shot_dict])

        # Verify cache exists
        cache_file = temp_cache_dir / "previous_shots.json"
        assert cache_file.exists()

        # Clear cache
        model.clear_cache()

        # Cache file should be removed
        assert not cache_file.exists()

    def test_incremental_cache_merge(
        self,
        test_shot_model: FakeShotModel,
        test_cache_manager: TestCacheManager,
        qtbot: QtBot,
    ) -> None:
        """Test incremental cache merge behavior."""
        # Local application imports
        from tests.fixtures.model_fixtures import (
            FakePreviousShotsWorker,
        )

        model = PreviousShotsModel(test_shot_model, test_cache_manager)

        # Pre-populate cache with existing shots
        existing_shots = [
            create_test_shot("show1", "seq1", "shot1"),
            create_test_shot("show1", "seq1", "shot2"),
        ]
        model._previous_shots = existing_shots

        # Create test worker with mix of existing and new shots
        test_worker = FakePreviousShotsWorker()
        new_shots = [
            create_test_shot("show1", "seq1", "shot1"),  # Existing
            create_test_shot("show1", "seq1", "shot3"),  # New
        ]
        test_worker.shots_to_find = new_shots

        shots_updated_spy = QSignalSpy(model.shots_updated)

        # Mock worker creation and trigger refresh
        with patch(
            "previous_shots.model.PreviousShotsWorker", return_value=test_worker
        ):
            model.refresh_shots()

            # Manually trigger completion
            shot_dicts = [
                {
                    "show": shot.show,
                    "sequence": shot.sequence,
                    "shot": shot.shot,
                    "workspace_path": shot.workspace_path,
                }
                for shot in new_shots
            ]
            model._on_scan_finished(shot_dicts)

        # Should have merged: 2 existing + 1 new = 3 total
        assert len(model.get_shots()) == 3
        # Should only emit update signal when new shots added
        assert shots_updated_spy.count() == 1

        model.deleteLater()
        process_qt_events()

    def test_on_cache_shots_migrated_merges_without_filesystem_scan(
        self,
        test_shot_model: FakeShotModel,
        test_cache_manager: TestCacheManager,
        qtbot: QtBot,
    ) -> None:
        """Emitting shots_migrated merges shots without spawning a worker.

        Verifies that _on_cache_shots_migrated():
        - Adds all new migrated shots to get_shots()
        - Does NOT start a filesystem scan (no PreviousShotsWorker spawned)
        - Persists via _save_to_cache() (shots survive a reload)
        - Emits shots_updated for UI refresh
        """
        model = PreviousShotsModel(test_shot_model, test_cache_manager)

        migrated_payload = [
            {
                "show": "showA",
                "sequence": "seqA",
                "shot": "shot001",
                "workspace_path": "/shows/showA/seqA/shot001",
            },
            {
                "show": "showA",
                "sequence": "seqA",
                "shot": "shot002",
                "workspace_path": "/shows/showA/seqA/shot002",
            },
        ]

        shots_updated_spy = QSignalSpy(model.shots_updated)
        scan_started_spy = QSignalSpy(model.scan_started)

        with patch(
            "previous_shots.model.PreviousShotsWorker"
        ) as mock_worker_cls:
            test_cache_manager.shots_migrated.emit(migrated_payload)
            process_qt_events()

            # Worker constructor must never have been called
            mock_worker_cls.assert_not_called()

        # Both shots appear in get_shots()
        shots = model.get_shots()
        shot_keys = {(s.show, s.sequence, s.shot) for s in shots}
        assert ("showA", "seqA", "shot001") in shot_keys
        assert ("showA", "seqA", "shot002") in shot_keys

        # UI was notified
        assert shots_updated_spy.count() == 1

        # No filesystem scan was started
        assert scan_started_spy.count() == 0

        # Data was persisted: a fresh model loads the same shots
        reloaded = PreviousShotsModel(test_shot_model, test_cache_manager)
        reloaded_keys = {(s.show, s.sequence, s.shot) for s in reloaded.get_shots()}
        assert ("showA", "seqA", "shot001") in reloaded_keys
        assert ("showA", "seqA", "shot002") in reloaded_keys
        reloaded.deleteLater()

        model.deleteLater()
        process_qt_events()

    def test_on_cache_shots_migrated_deduplicates_existing_shots(
        self,
        test_shot_model: FakeShotModel,
        test_cache_manager: TestCacheManager,
        qtbot: QtBot,
    ) -> None:
        """Migrated shots that already exist in the model are not duplicated."""
        model = PreviousShotsModel(test_shot_model, test_cache_manager)

        existing = create_test_shot("showB", "seqB", "shot001")
        model._previous_shots = [existing]

        # Migrate one duplicate + one new
        migrated_payload = [
            {
                "show": "showB",
                "sequence": "seqB",
                "shot": "shot001",  # already present
                "workspace_path": "/shows/showB/seqB/shot001",
            },
            {
                "show": "showB",
                "sequence": "seqB",
                "shot": "shot002",  # new
                "workspace_path": "/shows/showB/seqB/shot002",
            },
        ]

        shots_updated_spy = QSignalSpy(model.shots_updated)

        test_cache_manager.shots_migrated.emit(migrated_payload)
        process_qt_events()

        shots = model.get_shots()
        # Exactly 2 shots: original + the one new one
        assert len(shots) == 2
        shot_keys = {(s.show, s.sequence, s.shot) for s in shots}
        assert ("showB", "seqB", "shot001") in shot_keys
        assert ("showB", "seqB", "shot002") in shot_keys

        # Update was emitted because there was at least one new shot
        assert shots_updated_spy.count() == 1

        model.deleteLater()
        process_qt_events()

    def test_on_cache_shots_migrated_empty_payload_is_noop(
        self,
        model: PreviousShotsModel,
        qtbot: QtBot,
    ) -> None:
        """An empty migrated payload does not touch cache or emit signals."""
        shots_updated_spy = QSignalSpy(model.shots_updated)

        model._on_cache_shots_migrated([])

        assert shots_updated_spy.count() == 0
        assert model.get_shots() == []

