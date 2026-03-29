"""Validation tests for Config class - Configuration constraint verification.

This module provides comprehensive validation tests for the Config class,
ensuring configuration values meet their constraints and relationships.
These are NOT behavior tests - they validate configuration correctness.

The tests catch silent misconfigurations that could cause runtime issues,
such as the critical plate priority bug where PL plates were incorrectly
marked as reference-only (priority 10) instead of primary workflow plates
(priority 0.5).

Test Categories:
    - Plate Priority Validation: Ensures correct ordering and values
    - Path Configuration: Validates filesystem paths are valid
    - Timeout Configuration: Ensures timeouts are positive and reasonable
    - Application Configuration: Validates app settings completeness
    - Memory Configuration: Validates memory limits are sensible
    - Thread Configuration: Ensures thread counts are valid

Examples:
    Run all config validation tests:
        >>> pytest tests/unit/test_config.py -v

    Run specific validation:
        >>> pytest tests/unit/test_config.py::test_turnover_plate_priority_ordering -v

    Check if config is valid before release:
        >>> pytest tests/unit/test_config.py -v --tb=short

"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Config, ThreadingConfig
from timeout_config import TimeoutConfig


# Test markers for categorization
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.smoke,
]


class TestPlatePriorityValidation:
    """Validation tests for plate priority configuration.

    These tests catch configuration errors like the critical bug where PL
    (turnover) plates had priority 10 (reference-only) instead of 0.5
    (primary workflow), causing them to be skipped incorrectly.
    """

    def test_turnover_plate_priority_ordering(self) -> None:
        """Validate plate priorities maintain correct ordering.

        Primary workflow plates (FG, PL, BG) must have lower values
        than reference-only plates (BC). This prevents accidentally
        selecting reference plates over production plates.

        Regression test for bug where PL was 10 instead of 0.5.
        """
        priorities = Config.FileDiscovery.TURNOVER_PLATE_PRIORITY

        # Primary plates (use these) - must be ordered correctly
        assert priorities["FG"] < priorities["PL"], (
            "FG should have highest priority (lowest value)"
        )
        assert priorities["PL"] < priorities["BG"], "PL should be between FG and BG"
        assert priorities["BG"] < priorities["COMP"], (
            "BG should have priority over COMP"
        )
        assert priorities["COMP"] < priorities["EL"], (
            "COMP should have priority over EL"
        )

        # Reference plates (skip these) - must have high values
        assert priorities["BC"] > 5, (
            "BC plates are reference-only, should have high priority value"
        )
        assert priorities["*"] > priorities["BC"], (
            "Default (*) should be lowest priority (highest value)"
        )

    def test_primary_plates_have_low_priority(self) -> None:
        """Validate primary workflow plates have priority values < 2.

        FG, PL, and BG are the primary plates used in production.
        They must have low priority values (high priority) to be
        selected before reference plates.
        """
        priorities = Config.FileDiscovery.TURNOVER_PLATE_PRIORITY

        primary_plates = ["FG", "PL", "BG"]
        for plate in primary_plates:
            assert plate in priorities, (
                f"Primary plate {plate} missing from TURNOVER_PLATE_PRIORITY"
            )
            assert priorities[plate] < 2, (
                f"Primary plate {plate} has priority {priorities[plate]}, "
                f"should be < 2 for workflow plates"
            )

    def test_reference_plates_have_high_priority(self) -> None:
        """Validate reference-only plates have priority values >= 10.

        BC (background clean) plates are reference-only and should
        not be selected for primary workflow. High priority values
        ensure they're skipped in favor of production plates.
        """
        priorities = Config.FileDiscovery.TURNOVER_PLATE_PRIORITY

        reference_plates = ["BC"]
        for plate in reference_plates:
            assert plate in priorities, (
                f"Reference plate {plate} missing from TURNOVER_PLATE_PRIORITY"
            )
            assert priorities[plate] >= 10, (
                f"Reference plate {plate} has priority {priorities[plate]}, "
                f"should be >= 10 to ensure it's skipped"
            )

    def test_all_priority_values_are_numeric(self) -> None:
        """Validate all priority values are numeric (int or float).

        Priority values must be numeric for comparison operations.
        String values or None would cause runtime errors.
        """
        priorities = Config.FileDiscovery.TURNOVER_PLATE_PRIORITY

        for plate, priority in priorities.items():
            assert isinstance(priority, (int, float)), (
                f"Plate {plate} has non-numeric priority {priority!r} "
                f"(type: {type(priority).__name__})"
            )
            assert priority >= 0, f"Plate {plate} has negative priority {priority}"


class TestPathConfigurationValidation:
    """Validation tests for filesystem path configuration."""

    def test_shows_root_is_absolute_path(self) -> None:
        """Validate SHOWS_ROOT is an absolute path.

        Relative paths could cause issues with directory resolution.
        SHOWS_ROOT must be absolute for reliable filesystem operations.
        """
        shows_root = Config.Paths.SHOWS_ROOT
        path = Path(shows_root)

        assert path.is_absolute(), (
            f"SHOWS_ROOT must be absolute path, got: {shows_root}"
        )

    def test_cache_directories_are_valid_patterns(self) -> None:
        """Validate cache directory patterns are sensible.

        Cache paths should not contain invalid characters or
        patterns that could cause filesystem errors.
        """
        # Check SETTINGS_FILE path
        settings_file = Config.Paths.SETTINGS_FILE
        assert isinstance(settings_file, Path), "SETTINGS_FILE should be Path object"
        assert settings_file.is_absolute(), "SETTINGS_FILE should be absolute path"
        assert ".shotbot" in str(settings_file), (
            "SETTINGS_FILE should be in .shotbot directory"
        )

    def test_path_segments_are_not_empty(self) -> None:
        """Validate path segment lists contain no empty strings.

        Empty strings in path segments could cause double slashes
        or invalid path construction.
        """
        segment_lists = [
            ("THUMBNAIL_SEGMENTS", Config.FileDiscovery.THUMBNAIL_SEGMENTS),
            ("RAW_PLATE_SEGMENTS", Config.FileDiscovery.RAW_PLATE_SEGMENTS),
        ]

        for name, segments in segment_lists:
            assert len(segments) > 0, f"{name} should not be empty list"
            for segment in segments:
                assert segment, f"{name} contains empty string: {segments}"
                assert isinstance(segment, str), (
                    f"{name} contains non-string: {segment!r}"
                )


class TestTimeoutConfigurationValidation:
    """Validation tests for timeout configuration."""

    def test_timeout_values_are_positive(self) -> None:
        """Validate all timeout values are positive numbers.

        Zero or negative timeouts could cause immediate failures
        or infinite waits depending on implementation.
        """
        timeouts = [
            ("NOTIFICATION_SUCCESS_MS", TimeoutConfig.NOTIFICATION_SUCCESS_MS),
            ("NOTIFICATION_ERROR_MS", TimeoutConfig.NOTIFICATION_ERROR_MS),
            ("THUMBNAIL_UNLOAD_DELAY_MS", TimeoutConfig.THUMBNAIL_UNLOAD_DELAY_MS),
            ("WORKER_COORDINATION_STOP_MS", TimeoutConfig.WORKER_COORDINATION_STOP_MS),
        ]

        for name, timeout in timeouts:
            assert isinstance(timeout, (int, float)), (
                f"{name} must be numeric, got {type(timeout).__name__}"
            )
            assert timeout > 0, f"{name} must be positive, got {timeout}"

    def test_timeout_values_are_reasonable(self) -> None:
        """Validate timeout values are within reasonable ranges.

        Absurdly large timeouts (> 10 minutes) likely indicate
        misconfiguration in milliseconds vs seconds.
        """
        # Check second-based timeouts (should be < 600 seconds = 10 minutes)
        second_timeouts = [
            ("SUBPROCESS_SEC", TimeoutConfig.SUBPROCESS_SEC),
        ]

        for name, timeout in second_timeouts:
            assert timeout < 600, (
                f"{name} is {timeout}s (> 10 minutes), likely misconfigured"
            )

        # Check millisecond timeouts (should be < 600000ms = 10 minutes)
        ms_timeouts = [
            ("WORKER_COORDINATION_STOP_MS", TimeoutConfig.WORKER_COORDINATION_STOP_MS),
            ("THUMBNAIL_UNLOAD_DELAY_MS", TimeoutConfig.THUMBNAIL_UNLOAD_DELAY_MS),
        ]

        for name, timeout in ms_timeouts:
            assert timeout < 600000, (
                f"{name} is {timeout}ms (> 10 minutes), likely misconfigured"
            )

    def test_threading_config_timeouts_are_positive(self) -> None:
        """Validate TimeoutConfig timeout values are positive.

        Timeout configuration values must be positive to prevent
        deadlocks and infinite waits.
        """
        timeouts = [
            ("WORKER_GRACEFUL_STOP_MS", TimeoutConfig.WORKER_GRACEFUL_STOP_MS),
            ("WORKER_TERMINATE_MS", TimeoutConfig.WORKER_TERMINATE_MS),
            ("SESSION_INIT_SEC", TimeoutConfig.SESSION_INIT_SEC),
            ("SUBPROCESS_SEC", TimeoutConfig.SUBPROCESS_SEC),
        ]

        for name, timeout in timeouts:
            assert isinstance(timeout, (int, float)), f"{name} must be numeric"
            assert timeout > 0, f"{name} must be positive, got {timeout}"


class TestApplicationConfigurationValidation:
    """Validation tests for application configuration."""

    def test_app_config_completeness(self) -> None:
        """Validate all required application config keys are present.

        Missing configuration keys could cause AttributeErrors at runtime.
        """
        # Check basic app info
        assert hasattr(Config.App, "NAME"), "Missing App.NAME"
        assert hasattr(Config.App, "VERSION"), "Missing App.VERSION"
        assert isinstance(Config.App.NAME, str), "App.NAME must be string"
        assert isinstance(Config.App.VERSION, str), "App.VERSION must be string"
        assert len(Config.App.NAME) > 0, "App.NAME cannot be empty"
        assert len(Config.App.VERSION) > 0, "App.VERSION cannot be empty"

        # Check application commands dict
        assert hasattr(Config.Launch, "APPS"), "Missing Launch.APPS"
        assert isinstance(Config.Launch.APPS, dict), "Launch.APPS must be dictionary"
        assert len(Config.Launch.APPS) > 0, "Launch.APPS cannot be empty"

        # Check default app exists in APPS
        assert hasattr(Config.Launch, "DEFAULT_APP"), "Missing Launch.DEFAULT_APP"
        assert Config.Launch.DEFAULT_APP in Config.Launch.APPS, (
            f"DEFAULT_APP '{Config.Launch.DEFAULT_APP}' not in APPS: {list(Config.Launch.APPS.keys())}"
        )

    def test_window_dimensions_are_positive(self) -> None:
        """Validate window dimensions are positive integers.

        Zero or negative dimensions would cause Qt errors.
        """
        dimensions = [
            ("DEFAULT_WINDOW_WIDTH", Config.Window.DEFAULT_WIDTH),
            ("DEFAULT_WINDOW_HEIGHT", Config.Window.DEFAULT_HEIGHT),
            ("MIN_WINDOW_WIDTH", Config.Window.MIN_WIDTH),
            ("MIN_WINDOW_HEIGHT", Config.Window.MIN_HEIGHT),
        ]

        for name, dimension in dimensions:
            assert isinstance(dimension, int), f"{name} must be integer"
            assert dimension > 0, f"{name} must be positive, got {dimension}"

    def test_window_dimension_constraints(self) -> None:
        """Validate window dimension min/max relationships.

        Default dimensions should be >= minimum dimensions.
        """
        assert Config.Window.DEFAULT_WIDTH >= Config.Window.MIN_WIDTH, (
            f"DEFAULT_WINDOW_WIDTH ({Config.Window.DEFAULT_WIDTH}) "
            f"< MIN_WINDOW_WIDTH ({Config.Window.MIN_WIDTH})"
        )
        assert Config.Window.DEFAULT_HEIGHT >= Config.Window.MIN_HEIGHT, (
            f"DEFAULT_WINDOW_HEIGHT ({Config.Window.DEFAULT_HEIGHT}) "
            f"< MIN_WINDOW_HEIGHT ({Config.Window.MIN_HEIGHT})"
        )

    def test_thumbnail_size_constraints(self) -> None:
        """Validate thumbnail size configuration constraints.

        Default size must be between min and max values.
        """
        assert Config.Thumbnail.MIN_SIZE < Config.Thumbnail.MAX_SIZE, (
            f"MIN_THUMBNAIL_SIZE ({Config.Thumbnail.MIN_SIZE}) "
            f">= MAX_THUMBNAIL_SIZE ({Config.Thumbnail.MAX_SIZE})"
        )
        assert (
            Config.Thumbnail.MIN_SIZE
            <= Config.Thumbnail.DEFAULT_SIZE
            <= Config.Thumbnail.MAX_SIZE
        ), (
            f"DEFAULT_THUMBNAIL_SIZE ({Config.Thumbnail.DEFAULT_SIZE}) "
            f"not in range [{Config.Thumbnail.MIN_SIZE}, {Config.Thumbnail.MAX_SIZE}]"
        )
        assert Config.Cache.THUMBNAIL_SIZE > 0, "CACHE_THUMBNAIL_SIZE must be positive"


class TestMemoryConfigurationValidation:
    """Validation tests for memory limit configuration."""

    def test_memory_limits_are_positive(self) -> None:
        """Validate memory limit values are positive numbers.

        Zero or negative memory limits could disable caching or
        cause division by zero errors in memory calculations.
        """
        memory_limits = [
            ("MAX_THUMBNAIL_MEMORY_MB", Config.ImageLimits.MAX_THUMBNAIL_MEMORY_MB),
            ("MAX_FILE_SIZE_MB", Config.ImageLimits.MAX_FILE_SIZE_MB),
            ("PATH_CACHE_MAX_MEMORY_MB", Config.Cache.PATH_MAX_MEMORY_MB),
            ("DIR_CACHE_MAX_MEMORY_MB", Config.Cache.DIR_MAX_MEMORY_MB),
            ("SCENE_CACHE_MAX_MEMORY_MB", Config.Cache.SCENE_MAX_MEMORY_MB),
            ("THUMB_CACHE_MAX_MEMORY_MB", Config.Cache.THUMB_MAX_MEMORY_MB),
        ]

        for name, limit in memory_limits:
            assert isinstance(limit, (int, float)), f"{name} must be numeric"
            assert limit > 0, f"{name} must be positive, got {limit}"

    def test_cache_size_limits_are_positive(self) -> None:
        """Validate cache size limits are positive integers.

        Cache sizes must be positive for LRU eviction to work.
        """
        cache_sizes = [
            ("PATH_CACHE_MAX_SIZE", Config.Cache.PATH_MAX_SIZE),
            ("DIR_CACHE_MAX_SIZE", Config.Cache.DIR_MAX_SIZE),
            ("SCENE_CACHE_MAX_SIZE", Config.Cache.SCENE_MAX_SIZE),
        ]

        for name, size in cache_sizes:
            assert isinstance(size, int), f"{name} must be integer"
            assert size > 0, f"{name} must be positive, got {size}"


class TestThreadConfigurationValidation:
    """Validation tests for thread configuration."""

    def test_thread_counts_are_positive(self) -> None:
        """Validate thread count values are positive integers.

        Zero or negative thread counts would prevent work execution.
        """
        thread_counts = [
            ("MAX_THUMBNAIL_THREADS", Config.Threading.MAX_THUMBNAIL_THREADS),
            ("CPU_COUNT", Config.Threading.CPU_COUNT),
        ]

        for name, count in thread_counts:
            assert isinstance(count, int), f"{name} must be integer"
            assert count > 0, f"{name} must be positive, got {count}"

    def test_threading_config_worker_threads_are_reasonable(self) -> None:
        """Validate ThreadingConfig worker thread counts are reasonable.

        Thread counts should be positive and not exceed reasonable limits
        (e.g., < 100 threads to prevent resource exhaustion).
        """
        workers = [
            (
                "PREVIOUS_SHOTS_PARALLEL_WORKERS",
                ThreadingConfig.PREVIOUS_SHOTS_PARALLEL_WORKERS,
            ),
        ]

        for name, count in workers:
            assert isinstance(count, int), f"ThreadingConfig.{name} must be integer"
            assert count > 0, f"ThreadingConfig.{name} must be positive, got {count}"
            assert count <= 100, (
                f"ThreadingConfig.{name} is {count} (> 100), likely excessive"
            )

    def test_polling_intervals_are_valid(self) -> None:
        """Validate polling interval configuration is sensible.

        Initial poll should be < max poll, backoff should be > 1.
        """
        initial = TimeoutConfig.POLL_INITIAL_SEC
        max_poll = TimeoutConfig.POLL_MAX_SEC
        backoff = ThreadingConfig.POLL_BACKOFF_FACTOR

        assert 0 < initial < max_poll, (
            f"POLL_INITIAL_SEC ({initial}) must be < POLL_MAX_SEC ({max_poll})"
        )
        assert backoff > 1, (
            f"POLL_BACKOFF_FACTOR ({backoff}) must be > 1 for exponential backoff"
        )


class TestFileExtensionConfigurationValidation:
    """Validation tests for file extension configuration."""

    def test_file_extensions_have_leading_dot(self) -> None:
        """Validate all file extensions start with a dot.

        Extensions without leading dots would fail string matching.
        """
        extension_lists = [
            ("THUMBNAIL_EXTENSIONS", Config.FileDiscovery.THUMBNAIL_EXTENSIONS),
            ("THUMBNAIL_FALLBACK_EXTENSIONS", Config.FileDiscovery.THUMBNAIL_FALLBACK_EXTENSIONS),
            ("IMAGE_EXTENSIONS", Config.FileDiscovery.IMAGE_EXTENSIONS),
            ("NUKE_EXTENSIONS", Config.FileDiscovery.NUKE_EXTENSIONS),
            ("THREEDE_EXTENSIONS", Config.FileDiscovery.THREEDE_EXTENSIONS),
        ]

        for name, extensions in extension_lists:
            assert len(extensions) > 0, f"{name} should not be empty"
            for ext in extensions:
                assert isinstance(ext, str), f"{name} contains non-string: {ext!r}"
                assert ext.startswith("."), (
                    f"{name} contains extension without leading dot: {ext!r}"
                )
                assert len(ext) > 1, (
                    f"{name} contains invalid extension (just dot): {ext!r}"
                )

    def test_thumbnail_extensions_are_lightweight(self) -> None:
        """Validate primary thumbnail extensions are lightweight formats.

        Primary extensions should be JPG/PNG for fast loading.
        Heavy formats (EXR/TIFF) should only be in fallback list.
        """
        primary = Config.FileDiscovery.THUMBNAIL_EXTENSIONS
        fallback = Config.FileDiscovery.THUMBNAIL_FALLBACK_EXTENSIONS

        # Primary should contain only lightweight formats
        lightweight = {".jpg", ".jpeg", ".png"}
        for ext in primary:
            assert ext.lower() in lightweight, (
                f"Primary THUMBNAIL_EXTENSIONS contains heavy format: {ext}"
            )

        # Fallback should contain heavy formats (EXR, TIFF)
        heavy = {".tiff", ".tif", ".exr"}
        for ext in fallback:
            assert ext.lower() in heavy, (
                f"THUMBNAIL_FALLBACK_EXTENSIONS should only contain heavy formats, got: {ext}"
            )


class TestProgressConfigurationValidation:
    """Validation tests for progress reporting configuration."""

    def test_progress_intervals_are_positive(self) -> None:
        """Validate progress update intervals are positive.

        Zero or negative intervals could cause update storms.
        """
        intervals = [
            ("PROGRESS_UPDATE_INTERVAL_MS", TimeoutConfig.PROGRESS_UPDATE_INTERVAL_MS),
            ("PROGRESS_ETA_SMOOTHING_WINDOW", Config.UI.PROGRESS_ETA_SMOOTHING_WINDOW),
        ]

        for name, interval in intervals:
            assert isinstance(interval, int), f"{name} must be integer"
            assert interval > 0, f"{name} must be positive, got {interval}"
