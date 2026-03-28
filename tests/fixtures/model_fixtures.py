"""Model and signal test doubles.

Consolidated from:
- model_doubles.py:       Shot, ShotModel, CacheManager doubles
- signal_doubles.py:      SignalDouble lightweight signal test double
- integration_doubles.py: Removed (replaced with MagicMock and create_autospec)

Classes (model_doubles):
    TestShot:                Test double for Shot objects
    TestShotModel:           Test double for ShotModel with real Qt signals
    TestCacheManager:        Test double for CacheManager with real Qt signals
    FakeShotModel:           Test double for ShotModel (Previous Shots feature)
    FakePreviousShotsFinder: Test double for PreviousShotsFinder
    FakePreviousShotsWorker: Test double for PreviousShotsWorker

Functions (model_doubles):
    create_test_shot:  Factory for creating test shots
    create_test_shots: Factory for creating multiple test shots

Classes (signal_doubles):
    SignalDouble: Lightweight signal test double for non-Qt objects
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# signal_doubles contents
# ---------------------------------------------------------------------------
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable


class SignalDouble:
    """Lightweight signal test double for non-Qt objects.

    Use this instead of trying to use QSignalSpy on Mock objects,
    which will crash. This provides a simple interface for testing
    signal emissions and connections.

    Example:
        signal = SignalDouble()
        results = []
        signal.connect(lambda *args: results.append(args))
        signal.emit("test", 123)
        assert signal.was_emitted
        assert results == [("test", 123)]

    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    def __init__(self) -> None:
        """Initialize the test signal."""
        self.emissions: list[tuple[Any, ...]] = []
        self.callbacks: list[Callable[..., Any]] = []

    def emit(self, *args: Any) -> None:
        """Emit the signal with arguments."""
        self.emissions.append(args)
        for callback in self.callbacks:
            try:
                callback(*args)
            except Exception as e:  # noqa: BLE001
                print(f"SignalDouble callback error: {e}")

    def connect(
        self, callback: Callable[..., Any], connection_type: Any = None
    ) -> None:
        """Connect a callback to the signal.

        Args:
            callback: Callable to invoke on emit.
            connection_type: Ignored; accepted for Qt API compatibility.
        """
        self.callbacks.append(callback)

    def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
        """Disconnect a callback or all callbacks."""
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    @property
    def was_emitted(self) -> bool:
        """Check if the signal was emitted at least once."""
        return len(self.emissions) > 0

    @property
    def emit_count(self) -> int:
        """Get the number of times the signal was emitted."""
        return len(self.emissions)

    def get_last_emission(self) -> tuple[Any, ...] | None:
        """Get the arguments from the last emission."""
        if self.emissions:
            return self.emissions[-1]
        return None

    def clear(self) -> None:
        """Clear emission history and callbacks."""
        self.emissions.clear()
        self.callbacks.clear()

    def reset(self) -> None:
        """Reset emission history (keeps callbacks)."""
        self.emissions.clear()


# ---------------------------------------------------------------------------
# model_doubles contents
# ---------------------------------------------------------------------------

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal


if TYPE_CHECKING:
    from type_definitions import Shot


# Imported here to avoid circular import; used only in simulate_work_without_sleep calls
def _simulate_work(duration_ms: int = 10) -> None:
    from tests.fixtures.process_fixtures import simulate_work_without_sleep

    simulate_work_without_sleep(duration_ms)


# =============================================================================
# SHOT AND MODEL TEST DOUBLES
# =============================================================================


@dataclass
class TestShot:
    """Test double for Shot objects with real behavior."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    show: str = "test_show"
    sequence: str = "seq01"
    shot: str = "0010"
    workspace_path: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        """Initialize computed fields."""
        if not self.workspace_path:
            self.workspace_path = (
                f"/shows/{self.show}/shots/{self.sequence}/{self.sequence}_{self.shot}"
            )
        if not self.name:
            self.name = f"{self.sequence}_{self.shot}"

    @property
    def full_name(self) -> str:
        """Get full shot name (matches real Shot class interface)."""
        return f"{self.sequence}_{self.shot}"

    def get_thumbnail_path(self) -> Path:
        """Get path to thumbnail with real path construction."""
        return Path(self.workspace_path) / "publish" / "editorial" / "thumbnail.jpg"  # type: ignore[arg-type]

    def get_plate_path(self) -> Path:
        """Get path to plate directory."""
        return Path(self.workspace_path) / "publish" / "plates"  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for serialization."""
        return {
            "show": self.show,
            "sequence": self.sequence,
            "shot": self.shot,
            "workspace_path": self.workspace_path or "",
            "name": self.name or "",
        }


class TestShotModel(QObject):
    """Test double for ShotModel with real Qt signals."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    # Real Qt signals for proper testing
    shots_updated = Signal()
    shot_selected = Signal(str)
    refresh_started = Signal()
    refresh_finished = Signal(bool)
    error_occurred = Signal(str)  # Added to match real ShotModel interface

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize test shot model."""
        super().__init__(parent)
        self._shots: list[TestShot] = []
        self._selected_shot: TestShot | None = None
        self.refresh_count = 0
        self.signal_emissions: dict[str, int] = {
            "shots_updated": 0,
            "shot_selected": 0,
            "refresh_started": 0,
            "refresh_finished": 0,
        }

        # Connect signals to track emissions
        self.shots_updated.connect(lambda: self._track_signal("shots_updated"))
        self.shot_selected.connect(lambda _x: self._track_signal("shot_selected"))
        self.refresh_started.connect(lambda: self._track_signal("refresh_started"))
        self.refresh_finished.connect(lambda _x: self._track_signal("refresh_finished"))

    def _track_signal(self, signal_name: str) -> None:
        """Track signal emissions for testing."""
        self.signal_emissions[signal_name] += 1

    def add_shot(self, shot: TestShot) -> None:
        """Add a shot and emit signal."""
        self._shots.append(shot)
        self.shots_updated.emit()

    def add_test_shots(self, shots: list[TestShot]) -> None:
        """Add multiple shots at once."""
        self._shots.extend(shots)
        self.shots_updated.emit()

    def get_shots(self) -> list[TestShot]:
        """Get all shots."""
        return self._shots.copy()

    @property
    def shots(self) -> list[TestShot]:
        """Get all shots as property for compatibility with ShotGrid."""
        return self._shots.copy()

    def get_shot_by_name(self, name: str) -> TestShot | None:
        """Find shot by name."""
        for shot in self._shots:
            if shot.name == name:
                return shot
        return None

    def refresh_shots(self, force_fresh: bool = False) -> tuple[bool, bool]:
        """Simulate shot refresh with configurable behavior."""
        self.refresh_count += 1
        self.refresh_started.emit()

        # Simulate some work
        _simulate_work(10)  # 10ms

        # Determine if there are changes
        has_changes = self.refresh_count == 1 or len(self._shots) == 0

        if has_changes and self.refresh_count == 1:
            # Add default test shots on first refresh
            self.add_test_shots(
                [
                    TestShot("show1", "seq01", "0010"),
                    TestShot("show1", "seq01", "0020"),
                    TestShot("show1", "seq02", "0030"),
                ]
            )

        self.refresh_finished.emit(True)
        return (True, has_changes)

    def select_shot(self, shot: TestShot | str) -> None:
        """Select a shot and emit signal."""
        if isinstance(shot, str):
            shot = self.get_shot_by_name(shot)  # type: ignore[assignment]
        if shot:
            self._selected_shot = shot  # type: ignore[assignment]
            # Handle both TestShot and real Shot objects
            shot_name = getattr(shot, "name", None) or getattr(
                shot, "full_name", str(shot)
            )
            self.shot_selected.emit(shot_name)

    def clear(self) -> None:
        """Clear all shots."""
        self._shots.clear()
        self._selected_shot = None
        self.shots_updated.emit()

    def get_available_shows(self) -> set[str]:
        """Get all unique show names from current shots.

        Returns:
            Set of unique show names

        """
        return {shot.show for shot in self._shots}


class TestCacheManager(QObject):
    """Test double for CacheManager with real behavior."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    cache_updated = Signal()
    thumbnail_cached = Signal(str)
    shots_migrated = Signal(object)  # Emitted when shots migrate to Previous Shots

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize test cache manager."""
        super().__init__()
        self.cache_dir = cache_dir or Path("/tmp/test_cache")
        self._cached_thumbnails: dict[str, Path] = {}
        self._cached_shots: list[TestShot] = []
        self._cached_previous_shots: list[dict[str, Any]] | None = None
        self.thumbnails_dir = self.cache_dir / "thumbnails"

    def cache_thumbnail(
        self,
        source_path: str | Path,
        show: str,
        sequence: str,
        shot: str,
        wait: bool = True,
        timeout: float | None = None,
    ) -> Path | None:
        """Cache a thumbnail with real behavior."""
        cache_key = f"{show}_{sequence}_{shot}"

        # Simulate caching
        cached_path = self.cache_dir / "thumbnails" / show / sequence / f"{shot}.jpg"
        cached_path.parent.mkdir(parents=True, exist_ok=True)

        self._cached_thumbnails[cache_key] = cached_path

        self.thumbnail_cached.emit(cache_key)
        self.cache_updated.emit()

        return cached_path

    def get_cached_thumbnail(self, show: str, sequence: str, shot: str) -> Path | None:
        """Get cached thumbnail path."""
        cache_key = f"{show}_{sequence}_{shot}"
        return self._cached_thumbnails.get(cache_key)

    def cache_shots(self, shots: list[TestShot | dict[str, str]]) -> bool:
        """Cache shot data."""
        self._cached_shots.clear()
        for shot in shots:
            shot_obj = TestShot(**shot) if isinstance(shot, dict) else shot
            self._cached_shots.append(shot_obj)
        self.cache_updated.emit()
        return True

    def get_shots_with_ttl(self) -> list[TestShot]:
        """Get cached shots."""
        return self._cached_shots.copy()

    def get_cached_previous_shots(self) -> list[dict[str, Any]] | None:
        """Get cached previous/approved shot list if valid."""
        return (
            self._cached_previous_shots.copy() if self._cached_previous_shots else None
        )

    def get_persistent_previous_shots(self) -> list[dict[str, Any]] | None:
        """Get cached previous/approved shot list without TTL expiration.

        This method mirrors the persistent cache behavior where shots
        accumulate indefinitely without expiration.
        """
        return (
            self._cached_previous_shots.copy() if self._cached_previous_shots else None
        )

    def get_shots_no_ttl(self) -> list[dict[str, Any]] | None:
        """Get My Shots cache without TTL expiration.

        Similar to get_persistent_previous_shots() but for active shots.
        Enables incremental caching by preserving shot history.

        Returns:
            List of shot dictionaries or None if not cached

        """
        if not self._cached_shots:
            return None
        return [shot.to_dict() for shot in self._cached_shots]

    def cache_previous_shots(self, shots: list[TestShot | dict[str, Any]]) -> bool:
        """Cache previous shot data."""
        self._cached_previous_shots = []
        for shot in shots:
            shot_dict = shot.to_dict() if isinstance(shot, TestShot) else shot
            self._cached_previous_shots.append(shot_dict)
        self.cache_updated.emit()
        return True

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._cached_thumbnails.clear()
        self._cached_shots.clear()
        self._cached_previous_shots = None
        self.cache_updated.emit()

    def clear_previous_shots_cache(self) -> None:
        """Clear the previous shots cache."""
        self._cached_previous_shots = None
        self.cache_updated.emit()

    def get_shots_archive(self) -> list[dict[str, Any]] | None:
        """Get shots that were migrated from My Shots.

        Returns:
            List of migrated shot dictionaries or None

        """
        # Test double: return None (no migration tracking)
        return None

    def get_cached_threede_scenes(self) -> list[dict[str, Any]] | None:
        """Get cached 3DE scene list if valid."""
        # For testing, return empty list to simulate no cached scenes initially
        return []

    def cache_threede_scenes(
        self, scenes: list[dict[str, Any]], metadata: dict[str, Any] | None = None
    ) -> bool:
        """Cache 3DE scene data."""
        self.cache_updated.emit()
        return True

    def shutdown(self) -> None:
        """Gracefully shutdown the cache manager (test double)."""
        # For testing, just clear all cached data
        self.clear_cache()


# =============================================================================
# PREVIOUS SHOTS FEATURE TEST DOUBLES (merged from doubles_previous_shots.py)
# =============================================================================


class FakeShotModel(QObject):
    """Test double for ShotModel with real Qt signals and predictable behavior."""

    # Real Qt signals
    shots_updated = Signal()
    refresh_started = Signal()
    refresh_finished = Signal()

    def __init__(self, initial_shots=None) -> None:
        super().__init__()
        self.shots: list[Shot] = initial_shots or []
        self.refresh_calls: list[bool] = []
        self.get_shots_calls = 0

    def get_shots(self):
        """Return configured shots."""
        self.get_shots_calls += 1
        return self.shots.copy()

    def set_shots(self, shots) -> None:
        """Configure shots for testing."""
        self.shots = shots
        self.shots_updated.emit()

    def refresh_shots(self) -> bool:
        """Record refresh call."""
        self.refresh_calls.append(True)
        self.refresh_started.emit()
        # Simulate async completion
        self.refresh_finished.emit()
        return True


class FakePreviousShotsFinder:
    """Test double for PreviousShotsFinder with predictable behavior."""

    def __init__(self, username="testuser") -> None:
        self.username = username
        self.user_path_pattern = f"/user/{username}"

        # Track method calls
        self.find_user_shots_calls: list[Any] = []
        self.find_approved_shots_calls: list[Any] = []
        self.filter_approved_shots_calls: list[Any] = []
        self.get_shot_details_calls: list[Any] = []

        # Configurable return values
        self.user_shots_to_return: list[Any] = []
        self.approved_shots_to_return: list[Any] = []
        self.shot_details_to_return: dict[Any, Any] = {}

    def find_user_shots(self, shows_root: Path = Path("/shows")) -> list[Any]:
        """Record call and return configured shots."""
        self.find_user_shots_calls.append(shows_root)
        return self.user_shots_to_return.copy()

    def filter_approved_shots(
        self, all_user_shots: list[Any], active_shots: list[Any]
    ) -> list[Any]:
        """Record call and return configured shots."""
        self.filter_approved_shots_calls.append((all_user_shots, active_shots))

        # Simulate real filtering behavior
        if self.approved_shots_to_return:
            return self.approved_shots_to_return.copy()

        # Default: filter out active shots
        active_ids = {(s.show, s.sequence, s.shot) for s in active_shots}
        return [
            s for s in all_user_shots if (s.show, s.sequence, s.shot) not in active_ids
        ]

    def find_approved_shots(
        self, active_shots: list[Any], shows_root: Path = Path("/shows")
    ) -> list[Any]:
        """Record call and return configured shots."""
        self.find_approved_shots_calls.append((active_shots, shows_root))

        if self.approved_shots_to_return:
            return self.approved_shots_to_return.copy()

        # Simulate real behavior
        user_shots = self.find_user_shots(shows_root)
        return self.filter_approved_shots(user_shots, active_shots)

    def get_shot_details(self, shot: Any) -> dict[str, Any]:
        """Record call and return configured details."""
        self.get_shot_details_calls.append(shot)

        # Use shot ID as key instead of object (Shot is unhashable)
        shot_id = (shot.show, shot.sequence, shot.shot)
        if shot_id in self.shot_details_to_return:
            return self.shot_details_to_return[shot_id]

        # Default details
        return {
            "show": shot.show,
            "sequence": shot.sequence,
            "shot": shot.shot,
            "workspace_path": shot.workspace_path,
            "user_path": f"{shot.workspace_path}{self.user_path_pattern}",
            "status": "approved",
            "user_dir_exists": "True",
        }


class FakePreviousShotsWorker(QObject):
    """Test double for PreviousShotsWorker with controlled behavior and real Qt signals."""

    # Real Qt signals for proper integration
    started = Signal()
    scan_progress = Signal(int, int, str)
    scan_finished = Signal(object)
    worker_error = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Control behavior
        self.should_stop_flag = False
        self.run_calls = 0
        self.shots_to_find: list[Any] = []

        # Track method calls
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        """Start the worker (simulate thread start)."""
        self.start_calls += 1
        self.started.emit()
        # For testing, we don't automatically run - tests will trigger completion manually

    def run(self) -> None:
        """Simulate worker execution."""
        self.run_calls += 1

        # Emit signals based on configuration
        for i, shot in enumerate(self.shots_to_find):
            if self.should_stop_flag:
                break

            self.scan_progress.emit(
                i + 1, len(self.shots_to_find), f"Processing {shot.shot}"
            )

        if not self.should_stop_flag:
            shot_dicts = [
                {
                    "show": shot.show,
                    "sequence": shot.sequence,
                    "shot": shot.shot,
                    "workspace_path": shot.workspace_path,
                }
                for shot in self.shots_to_find
            ]
            self.scan_finished.emit(shot_dicts)

    def stop(self) -> None:
        """Request stop."""
        self.stop_calls += 1
        self.should_stop_flag = True

    def wait(self, timeout_ms: int = 1000) -> bool:
        """Simulate thread wait."""
        return True  # Always succeeds in test

    def should_stop(self) -> bool:
        """Check if stop was requested."""
        return self.should_stop_flag

    def is_zombie(self) -> bool:
        """Test double: never a zombie."""
        return False

    def safe_shutdown(self, timeout_ms: int = 2000) -> None:
        """Test double: simulate safe shutdown."""
        self.stop()
        self.deleteLater()


def create_test_shot(
    show: str = "test", seq: str = "seq01", shot: str = "0010", path: str | None = None
) -> Any:
    """Factory function for creating test shots."""
    from type_definitions import Shot

    if path is None:
        path = f"/shows/{show}/shots/{seq}/{shot}"
    return Shot(show=show, sequence=seq, shot=shot, workspace_path=path)


def create_test_shots(count: int = 3, show: str = "test") -> list[Any]:
    """Create multiple test shots."""
    return [
        create_test_shot(show, f"seq{i:02d}", f"{(i + 1) * 10:04d}")
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# integration_doubles contents
# ---------------------------------------------------------------------------
