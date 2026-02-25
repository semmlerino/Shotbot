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


# Test markers for categorization
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
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
        priorities = Config.TURNOVER_PLATE_PRIORITY

        # Primary plates (use these) - must be ordered correctly
        assert priorities["FG"] < priorities["PL"], "FG should have highest priority (lowest value)"
        assert priorities["PL"] < priorities["BG"], "PL should be between FG and BG"
        assert priorities["BG"] < priorities["COMP"], "BG should have priority over COMP"
        assert priorities["COMP"] < priorities["EL"], "COMP should have priority over EL"

        # Reference plates (skip these) - must have high values
        assert priorities["BC"] > 5, "BC plates are reference-only, should have high priority value"
        assert priorities["*"] > priorities["BC"], "Default (*) should be lowest priority (highest value)"

    def test_primary_plates_have_low_priority(self) -> None:
        """Validate primary workflow plates have priority values < 2.

        FG, PL, and BG are the primary plates used in production.
        They must have low priority values (high priority) to be
        selected before reference plates.
        """
        priorities = Config.TURNOVER_PLATE_PRIORITY

        primary_plates = ["FG", "PL", "BG"]
        for plate in primary_plates:
            assert plate in priorities, f"Primary plate {plate} missing from TURNOVER_PLATE_PRIORITY"
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
        priorities = Config.TURNOVER_PLATE_PRIORITY

        reference_plates = ["BC"]
        for plate in reference_plates:
            assert plate in priorities, f"Reference plate {plate} missing from TURNOVER_PLATE_PRIORITY"
            assert priorities[plate] >= 10, (
                f"Reference plate {plate} has priority {priorities[plate]}, "
                f"should be >= 10 to ensure it's skipped"
            )

    def test_all_priority_values_are_numeric(self) -> None:
        """Validate all priority values are numeric (int or float).

        Priority values must be numeric for comparison operations.
        String values or None would cause runtime errors.
        """
        priorities = Config.TURNOVER_PLATE_PRIORITY

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
        shows_root = Config.SHOWS_ROOT
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
        settings_file = Config.SETTINGS_FILE
        assert isinstance(settings_file, Path), "SETTINGS_FILE should be Path object"
        assert settings_file.is_absolute(), "SETTINGS_FILE should be absolute path"
        assert ".shotbot" in str(settings_file), "SETTINGS_FILE should be in .shotbot directory"

    def test_path_segments_are_not_empty(self) -> None:
        """Validate path segment lists contain no empty strings.

        Empty strings in path segments could cause double slashes
        or invalid path construction.
        """
        segment_lists = [
            ("THUMBNAIL_SEGMENTS", Config.THUMBNAIL_SEGMENTS),
            ("RAW_PLATE_SEGMENTS", Config.RAW_PLATE_SEGMENTS),
            ("THREEDE_SCENE_SEGMENTS", Config.THREEDE_SCENE_SEGMENTS),
        ]

        for name, segments in segment_lists:
            assert len(segments) > 0, f"{name} should not be empty list"
            for segment in segments:
                assert segment, f"{name} contains empty string: {segments}"
                assert isinstance(segment, str), f"{name} contains non-string: {segment!r}"


class TestTimeoutConfigurationValidation:
    """Validation tests for timeout configuration."""

    def test_timeout_values_are_positive(self) -> None:
        """Validate all timeout values are positive numbers.

        Zero or negative timeouts could cause immediate failures
        or infinite waits depending on implementation.
        """
        timeouts = [
            ("SUBPROCESS_TIMEOUT_SECONDS", Config.SUBPROCESS_TIMEOUT_SECONDS),
            ("WS_COMMAND_TIMEOUT_SECONDS", Config.WS_COMMAND_TIMEOUT_SECONDS),
            ("WORKER_STOP_TIMEOUT_MS", Config.WORKER_STOP_TIMEOUT_MS),
            ("NOTIFICATION_TOAST_DURATION_MS", Config.NOTIFICATION_TOAST_DURATION_MS),
            ("NOTIFICATION_SUCCESS_TIMEOUT_MS", Config.NOTIFICATION_SUCCESS_TIMEOUT_MS),
            ("NOTIFICATION_ERROR_TIMEOUT_MS", Config.NOTIFICATION_ERROR_TIMEOUT_MS),
            ("THUMBNAIL_UNLOAD_DELAY_MS", Config.THUMBNAIL_UNLOAD_DELAY_MS),
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
            ("SUBPROCESS_TIMEOUT_SECONDS", Config.SUBPROCESS_TIMEOUT_SECONDS),
            ("WS_COMMAND_TIMEOUT_SECONDS", Config.WS_COMMAND_TIMEOUT_SECONDS),
        ]

        for name, timeout in second_timeouts:
            assert timeout < 600, (
                f"{name} is {timeout}s (> 10 minutes), likely misconfigured"
            )

        # Check millisecond timeouts (should be < 600000ms = 10 minutes)
        ms_timeouts = [
            ("WORKER_STOP_TIMEOUT_MS", Config.WORKER_STOP_TIMEOUT_MS),
            ("NOTIFICATION_TOAST_DURATION_MS", Config.NOTIFICATION_TOAST_DURATION_MS),
            ("THUMBNAIL_UNLOAD_DELAY_MS", Config.THUMBNAIL_UNLOAD_DELAY_MS),
        ]

        for name, timeout in ms_timeouts:
            assert timeout < 600000, (
                f"{name} is {timeout}ms (> 10 minutes), likely misconfigured"
            )

    def test_threading_config_timeouts_are_positive(self) -> None:
        """Validate ThreadingConfig timeout values are positive.

        Threading configuration timeouts must be positive to prevent
        deadlocks and infinite waits.
        """
        timeouts = [
            ("WORKER_STOP_TIMEOUT_MS", ThreadingConfig.WORKER_STOP_TIMEOUT_MS),
            ("WORKER_TERMINATE_TIMEOUT_MS", ThreadingConfig.WORKER_TERMINATE_TIMEOUT_MS),
            ("CLEANUP_RETRY_DELAY_MS", ThreadingConfig.CLEANUP_RETRY_DELAY_MS),
            ("CLEANUP_INITIAL_DELAY_MS", ThreadingConfig.CLEANUP_INITIAL_DELAY_MS),
            ("SESSION_INIT_TIMEOUT", ThreadingConfig.SESSION_INIT_TIMEOUT),
            ("SUBPROCESS_TIMEOUT", ThreadingConfig.SUBPROCESS_TIMEOUT),
        ]

        for name, timeout in timeouts:
            assert isinstance(timeout, (int, float)), (
                f"ThreadingConfig.{name} must be numeric"
            )
            assert timeout > 0, f"ThreadingConfig.{name} must be positive, got {timeout}"


class TestApplicationConfigurationValidation:
    """Validation tests for application configuration."""

    def test_app_config_completeness(self) -> None:
        """Validate all required application config keys are present.

        Missing configuration keys could cause AttributeErrors at runtime.
        """
        # Check basic app info
        assert hasattr(Config, "APP_NAME"), "Missing APP_NAME"
        assert hasattr(Config, "APP_VERSION"), "Missing APP_VERSION"
        assert isinstance(Config.APP_NAME, str), "APP_NAME must be string"
        assert isinstance(Config.APP_VERSION, str), "APP_VERSION must be string"
        assert len(Config.APP_NAME) > 0, "APP_NAME cannot be empty"
        assert len(Config.APP_VERSION) > 0, "APP_VERSION cannot be empty"

        # Check application commands dict
        assert hasattr(Config, "APPS"), "Missing APPS"
        assert isinstance(Config.APPS, dict), "APPS must be dictionary"
        assert len(Config.APPS) > 0, "APPS cannot be empty"

        # Check default app exists in APPS
        assert hasattr(Config, "DEFAULT_APP"), "Missing DEFAULT_APP"
        assert Config.DEFAULT_APP in Config.APPS, (
            f"DEFAULT_APP '{Config.DEFAULT_APP}' not in APPS: {list(Config.APPS.keys())}"
        )

    def test_window_dimensions_are_positive(self) -> None:
        """Validate window dimensions are positive integers.

        Zero or negative dimensions would cause Qt errors.
        """
        dimensions = [
            ("DEFAULT_WINDOW_WIDTH", Config.DEFAULT_WINDOW_WIDTH),
            ("DEFAULT_WINDOW_HEIGHT", Config.DEFAULT_WINDOW_HEIGHT),
            ("MIN_WINDOW_WIDTH", Config.MIN_WINDOW_WIDTH),
            ("MIN_WINDOW_HEIGHT", Config.MIN_WINDOW_HEIGHT),
        ]

        for name, dimension in dimensions:
            assert isinstance(dimension, int), f"{name} must be integer"
            assert dimension > 0, f"{name} must be positive, got {dimension}"

    def test_window_dimension_constraints(self) -> None:
        """Validate window dimension min/max relationships.

        Default dimensions should be >= minimum dimensions.
        """
        assert Config.DEFAULT_WINDOW_WIDTH >= Config.MIN_WINDOW_WIDTH, (
            f"DEFAULT_WINDOW_WIDTH ({Config.DEFAULT_WINDOW_WIDTH}) "
            f"< MIN_WINDOW_WIDTH ({Config.MIN_WINDOW_WIDTH})"
        )
        assert Config.DEFAULT_WINDOW_HEIGHT >= Config.MIN_WINDOW_HEIGHT, (
            f"DEFAULT_WINDOW_HEIGHT ({Config.DEFAULT_WINDOW_HEIGHT}) "
            f"< MIN_WINDOW_HEIGHT ({Config.MIN_WINDOW_HEIGHT})"
        )

    def test_thumbnail_size_constraints(self) -> None:
        """Validate thumbnail size configuration constraints.

        Default size must be between min and max values.
        """
        assert Config.MIN_THUMBNAIL_SIZE < Config.MAX_THUMBNAIL_SIZE, (
            f"MIN_THUMBNAIL_SIZE ({Config.MIN_THUMBNAIL_SIZE}) "
            f">= MAX_THUMBNAIL_SIZE ({Config.MAX_THUMBNAIL_SIZE})"
        )
        assert Config.MIN_THUMBNAIL_SIZE <= Config.DEFAULT_THUMBNAIL_SIZE <= Config.MAX_THUMBNAIL_SIZE, (
            f"DEFAULT_THUMBNAIL_SIZE ({Config.DEFAULT_THUMBNAIL_SIZE}) "
            f"not in range [{Config.MIN_THUMBNAIL_SIZE}, {Config.MAX_THUMBNAIL_SIZE}]"
        )
        assert Config.CACHE_THUMBNAIL_SIZE > 0, "CACHE_THUMBNAIL_SIZE must be positive"


class TestMemoryConfigurationValidation:
    """Validation tests for memory limit configuration."""

    def test_memory_limits_are_positive(self) -> None:
        """Validate memory limit values are positive numbers.

        Zero or negative memory limits could disable caching or
        cause division by zero errors in memory calculations.
        """
        memory_limits = [
            ("MAX_THUMBNAIL_MEMORY_MB", Config.MAX_THUMBNAIL_MEMORY_MB),
            ("MAX_FILE_SIZE_MB", Config.MAX_FILE_SIZE_MB),
            ("PATH_CACHE_MAX_MEMORY_MB", Config.PATH_CACHE_MAX_MEMORY_MB),
            ("DIR_CACHE_MAX_MEMORY_MB", Config.DIR_CACHE_MAX_MEMORY_MB),
            ("SCENE_CACHE_MAX_MEMORY_MB", Config.SCENE_CACHE_MAX_MEMORY_MB),
            ("THUMB_CACHE_MAX_MEMORY_MB", Config.THUMB_CACHE_MAX_MEMORY_MB),
            ("PROGRESSIVE_MAX_MEMORY_MB", Config.PROGRESSIVE_MAX_MEMORY_MB),
        ]

        for name, limit in memory_limits:
            assert isinstance(limit, (int, float)), f"{name} must be numeric"
            assert limit > 0, f"{name} must be positive, got {limit}"

    def test_memory_pressure_thresholds_are_ordered(self) -> None:
        """Validate memory pressure thresholds maintain correct ordering.

        Thresholds must increase: NORMAL < MODERATE < HIGH
        """
        normal = Config.MEMORY_PRESSURE_NORMAL
        moderate = Config.MEMORY_PRESSURE_MODERATE
        high = Config.MEMORY_PRESSURE_HIGH

        assert normal < moderate, (
            f"MEMORY_PRESSURE_NORMAL ({normal}) >= MODERATE ({moderate})"
        )
        assert moderate < high, (
            f"MEMORY_PRESSURE_MODERATE ({moderate}) >= HIGH ({high})"
        )
        assert 0 < normal < 100, f"MEMORY_PRESSURE_NORMAL ({normal}) not in (0, 100)"
        assert 0 < moderate < 100, f"MEMORY_PRESSURE_MODERATE ({moderate}) not in (0, 100)"
        assert 0 < high <= 100, f"MEMORY_PRESSURE_HIGH ({high}) not in (0, 100]"

    def test_cache_size_limits_are_positive(self) -> None:
        """Validate cache size limits are positive integers.

        Cache sizes must be positive for LRU eviction to work.
        """
        cache_sizes = [
            ("PATH_CACHE_MAX_SIZE", Config.PATH_CACHE_MAX_SIZE),
            ("DIR_CACHE_MAX_SIZE", Config.DIR_CACHE_MAX_SIZE),
            ("SCENE_CACHE_MAX_SIZE", Config.SCENE_CACHE_MAX_SIZE),
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
            ("MAX_THUMBNAIL_THREADS", Config.MAX_THUMBNAIL_THREADS),
            ("CPU_COUNT", Config.CPU_COUNT),
            ("THREEDE_SCAN_PARALLEL_SEQUENCES", Config.THREEDE_SCAN_PARALLEL_SEQUENCES),
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
            ("MAX_WORKER_THREADS", ThreadingConfig.MAX_WORKER_THREADS),
            ("PREVIOUS_SHOTS_PARALLEL_WORKERS", ThreadingConfig.PREVIOUS_SHOTS_PARALLEL_WORKERS),
            ("THREEDE_PARALLEL_WORKERS", ThreadingConfig.THREEDE_PARALLEL_WORKERS),
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
        initial = ThreadingConfig.INITIAL_POLL_INTERVAL
        max_poll = ThreadingConfig.MAX_POLL_INTERVAL
        backoff = ThreadingConfig.POLL_BACKOFF_FACTOR

        assert 0 < initial < max_poll, (
            f"INITIAL_POLL_INTERVAL ({initial}) must be < MAX_POLL_INTERVAL ({max_poll})"
        )
        assert backoff > 1, f"POLL_BACKOFF_FACTOR ({backoff}) must be > 1 for exponential backoff"


class TestFileExtensionConfigurationValidation:
    """Validation tests for file extension configuration."""

    def test_file_extensions_have_leading_dot(self) -> None:
        """Validate all file extensions start with a dot.

        Extensions without leading dots would fail string matching.
        """
        extension_lists = [
            ("THUMBNAIL_EXTENSIONS", Config.THUMBNAIL_EXTENSIONS),
            ("THUMBNAIL_FALLBACK_EXTENSIONS", Config.THUMBNAIL_FALLBACK_EXTENSIONS),
            ("IMAGE_EXTENSIONS", Config.IMAGE_EXTENSIONS),
            ("NUKE_EXTENSIONS", Config.NUKE_EXTENSIONS),
            ("THREEDE_EXTENSIONS", Config.THREEDE_EXTENSIONS),
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
        primary = Config.THUMBNAIL_EXTENSIONS
        fallback = Config.THUMBNAIL_FALLBACK_EXTENSIONS

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
            ("PROGRESS_UPDATE_INTERVAL_MS", Config.PROGRESS_UPDATE_INTERVAL_MS),
            ("PROGRESS_FILES_PER_UPDATE", Config.PROGRESS_FILES_PER_UPDATE),
            ("PROGRESS_ETA_SMOOTHING_WINDOW", Config.PROGRESS_ETA_SMOOTHING_WINDOW),
        ]

        for name, interval in intervals:
            assert isinstance(interval, int), f"{name} must be integer"
            assert interval > 0, f"{name} must be positive, got {interval}"

    def test_batch_size_constraints(self) -> None:
        """Validate progressive scan batch size constraints.

        Min batch size should be <= default <= max batch size.
        """
        min_batch = Config.PROGRESSIVE_SCAN_MIN_BATCH_SIZE
        default_batch = Config.PROGRESSIVE_SCAN_BATCH_SIZE
        max_batch = Config.PROGRESSIVE_SCAN_MAX_BATCH_SIZE

        assert min_batch <= default_batch <= max_batch, (
            f"Batch size constraint violation: "
            f"MIN ({min_batch}) <= DEFAULT ({default_batch}) <= MAX ({max_batch})"
        )
        assert min_batch > 0, "PROGRESSIVE_SCAN_MIN_BATCH_SIZE must be positive"
        assert max_batch > 0, "PROGRESSIVE_SCAN_MAX_BATCH_SIZE must be positive"
