"""Unit tests for regex pre-compilation performance optimizations.

These tests verify that:
1. Pre-compiled patterns work correctly
2. Pattern matching still produces correct results
3. Edge cases with various shot/plate names are handled
4. Performance improvements are measurable
"""

import re
import time
from pathlib import Path
from typing import List, Pattern
from unittest.mock import Mock, patch

import pytest

from raw_plate_finder import RawPlateFinder
from tests.performance.timed_operation import TimingRegistry, timed_operation


class TestRegexPrecompilation:
    """Test suite for regex pre-compilation optimizations."""

    def setup_method(self):
        """Set up test environment."""
        TimingRegistry.clear()
        # Clear pattern caches for clean testing
        RawPlateFinder._pattern_cache.clear()
        RawPlateFinder._verify_pattern_cache.clear()

    def teardown_method(self):
        """Clean up after tests."""
        TimingRegistry.clear()

    def test_pattern_cache_initialization(self):
        """Test that pattern cache is properly initialized."""
        # Pattern cache should be empty initially
        assert len(RawPlateFinder._pattern_cache) == 0

        # After first call, cache should be populated
        patterns = RawPlateFinder._get_plate_patterns("108_CHV_0015", "FG01", "v001")
        assert len(patterns) == 2
        assert len(RawPlateFinder._pattern_cache) == 1

        # Cache key should be correct
        cache_key = ("108_CHV_0015", "FG01", "v001")
        assert cache_key in RawPlateFinder._pattern_cache

    def test_pattern_cache_reuse(self):
        """Test that cached patterns are reused properly."""
        shot_name = "108_CHV_0015"
        plate_name = "FG01"
        version = "v001"

        # First call should create patterns
        patterns1 = RawPlateFinder._get_plate_patterns(shot_name, plate_name, version)

        # Second call should return cached patterns (same object references)
        patterns2 = RawPlateFinder._get_plate_patterns(shot_name, plate_name, version)

        assert patterns1 is patterns2  # Should be exact same objects
        assert len(RawPlateFinder._pattern_cache) == 1

    @pytest.mark.parametrize(
        "shot_name,plate_name,version",
        [
            ("108_CHV_0015", "FG01", "v001"),
            ("109_ABC_0020", "BG01", "v002"),
            ("110_XYZ_0030", "bg01", "v003"),
            ("TEST_SHOT_001", "FG02", "v010"),
            ("SPECIAL_123", "plate", "v999"),
        ],
    )
    def test_pattern_generation_variations(
        self, shot_name: str, plate_name: str, version: str
    ):
        """Test pattern generation with various shot/plate name combinations."""
        patterns = RawPlateFinder._get_plate_patterns(shot_name, plate_name, version)

        assert len(patterns) == 2
        pattern1, pattern2 = patterns

        # Patterns should be compiled regex objects
        assert isinstance(pattern1, Pattern)
        assert isinstance(pattern2, Pattern)

        # Patterns should have IGNORECASE flag
        assert pattern1.flags & re.IGNORECASE
        assert pattern2.flags & re.IGNORECASE

    def test_pattern_matching_accuracy(self):
        """Test that pre-compiled patterns match correctly."""
        shot_name = "108_CHV_0015"
        plate_name = "FG01"
        version = "v001"

        pattern1, pattern2 = RawPlateFinder._get_plate_patterns(
            shot_name, plate_name, version
        )

        # Test Pattern 1: {shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.####.exr
        test_filename1 = "108_CHV_0015_turnover-plate_FG01_aces_v001.1001.exr"
        match1 = pattern1.match(test_filename1)
        assert match1 is not None
        assert match1.group(1) == "aces"  # Color space should be captured

        # Test Pattern 2: {shot_name}_turnover-plate_{plate_name}{color_space}_{version}.####.exr
        test_filename2 = "108_CHV_0015_turnover-plate_FG01lin_sgamut3cine_v001.1001.exr"
        match2 = pattern2.match(test_filename2)
        assert match2 is not None
        assert match2.group(1) == "lin_sgamut3cine"  # Color space should be captured

    def test_case_insensitive_matching(self):
        """Test case insensitive pattern matching."""
        shot_name = "108_CHV_0015"
        plate_name = "fg01"  # lowercase
        version = "v001"

        pattern1, pattern2 = RawPlateFinder._get_plate_patterns(
            shot_name, plate_name, version
        )

        # Test with mixed case filename
        test_filename = "108_CHV_0015_turnover-plate_FG01_ACES_v001.1001.EXR"
        match1 = pattern1.match(test_filename)
        assert match1 is not None
        assert match1.group(1) == "ACES"

    def test_verify_pattern_cache(self):
        """Test the verify_plate_exists pattern cache."""
        # Test pattern caching in verify_plate_exists
        plate_path = "/path/to/shot_turnover-plate_FG01_aces_v001.####.exr"

        # Mock the directory and file structure
        mock_dir = Mock()
        mock_file = Mock()
        mock_file.is_file.return_value = True
        mock_file.name = "shot_turnover-plate_FG01_aces_v001.1001.exr"
        mock_dir.iterdir.return_value = [mock_file]

        with patch.object(
            Path, "parent", new_callable=lambda: Mock(return_value=mock_dir)
        ):
            with patch(
                "raw_plate_finder.PathUtils.validate_path_exists", return_value=True
            ):
                # First call should compile and cache pattern
                result1 = RawPlateFinder.verify_plate_exists(plate_path)
                assert result1 is True
                assert len(RawPlateFinder._verify_pattern_cache) == 1

                # Second call should use cached pattern
                result2 = RawPlateFinder.verify_plate_exists(plate_path)
                assert result2 is True
                # Cache size should remain the same
                assert len(RawPlateFinder._verify_pattern_cache) == 1

    @timed_operation("regex_baseline", store_results=True)
    def _baseline_regex_matching(
        self, test_filenames: List[str], iterations: int = 1000
    ):
        """Baseline regex matching without pre-compilation."""
        shot_name = "108_CHV_0015"
        plate_name = "FG01"
        version = "v001"

        matches = 0
        for _ in range(iterations):
            for filename in test_filenames:
                # Compile pattern each time (baseline behavior)
                pattern1_str = rf"{shot_name}_turnover-plate_{plate_name}_([^_]+)_{version}\.\d{{4}}\.exr"
                pattern1 = re.compile(pattern1_str, re.IGNORECASE)

                pattern2_str = rf"{shot_name}_turnover-plate_{plate_name}([^_]+)_{version}\.\d{{4}}\.exr"
                pattern2 = re.compile(pattern2_str, re.IGNORECASE)

                if pattern1.match(filename) or pattern2.match(filename):
                    matches += 1

        return matches

    @timed_operation("regex_optimized", store_results=True)
    def _optimized_regex_matching(
        self, test_filenames: List[str], iterations: int = 1000
    ):
        """Optimized regex matching with pre-compilation."""
        shot_name = "108_CHV_0015"
        plate_name = "FG01"
        version = "v001"

        matches = 0
        for _ in range(iterations):
            for filename in test_filenames:
                # Use pre-compiled patterns
                pattern1, pattern2 = RawPlateFinder._get_plate_patterns(
                    shot_name, plate_name, version
                )

                if pattern1.match(filename) or pattern2.match(filename):
                    matches += 1

        return matches

    def test_performance_improvement(self):
        """Test that pre-compiled patterns provide significant performance improvement."""
        # Test filenames with various patterns
        test_filenames = [
            "108_CHV_0015_turnover-plate_FG01_aces_v001.1001.exr",
            "108_CHV_0015_turnover-plate_FG01_lin_sgamut3cine_v001.1002.exr",
            "108_CHV_0015_turnover-plate_FG01lin_rec709_v001.1003.exr",
            "108_CHV_0015_turnover-plate_FG01_srgb_v001.1004.exr",
            "different_shot_name_v001.1001.exr",  # Should not match
        ]

        iterations = 100  # Reduced for testing

        # Run baseline (compile each time)
        baseline_matches = self._baseline_regex_matching(test_filenames, iterations)

        # Run optimized (use pre-compiled)
        optimized_matches = self._optimized_regex_matching(test_filenames, iterations)

        # Results should be identical
        assert baseline_matches == optimized_matches

        # Get timing statistics
        baseline_stats = TimingRegistry.get_stats("regex_baseline")
        optimized_stats = TimingRegistry.get_stats("regex_optimized")

        assert baseline_stats is not None
        assert optimized_stats is not None

        # Calculate speedup
        speedup = TimingRegistry.compare_operations("regex_baseline", "regex_optimized")
        assert speedup is not None

        # Should see significant improvement (at least 5x)
        assert speedup >= 5.0, f"Expected at least 5x speedup, got {speedup:.2f}x"

        print(f"Regex pre-compilation speedup: {speedup:.1f}x")
        print(f"Baseline: {baseline_stats['mean_ms']:.2f}ms")
        print(f"Optimized: {optimized_stats['mean_ms']:.2f}ms")

    def test_edge_cases_shot_names(self):
        """Test edge cases with unusual shot names."""
        edge_case_shots = [
            "SHOT_WITH_UNDERSCORES_001",
            "shot-with-dashes-002",
            "ShotWithCamelCase003",
            "123_NUMERIC_START_004",
            "VERY_LONG_SHOT_NAME_WITH_MANY_SEGMENTS_005",
            "SH_006",  # Very short
        ]

        for shot_name in edge_case_shots:
            patterns = RawPlateFinder._get_plate_patterns(shot_name, "FG01", "v001")
            assert len(patterns) == 2

            # Test that patterns can be used for matching
            test_filename = f"{shot_name}_turnover-plate_FG01_aces_v001.1001.exr"
            match = patterns[0].match(test_filename)
            assert match is not None
            assert match.group(1) == "aces"

    def test_edge_cases_color_spaces(self):
        """Test edge cases with various color spaces."""
        color_spaces = [
            "aces",
            "lin_sgamut3cine",
            "lin_rec709",
            "rec709",
            "srgb",
            "custom_cs",
            "ACEScg",
            "lin_ap1",
            "xyz",
        ]

        shot_name = "108_CHV_0015"
        plate_name = "FG01"
        version = "v001"

        patterns = RawPlateFinder._get_plate_patterns(shot_name, plate_name, version)

        for color_space in color_spaces:
            # Test Pattern 1 format
            test_filename1 = f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.1001.exr"
            match1 = patterns[0].match(test_filename1)
            assert match1 is not None
            assert match1.group(1) == color_space

            # Test Pattern 2 format (no underscore before color space)
            test_filename2 = f"{shot_name}_turnover-plate_{plate_name}{color_space}_{version}.1001.exr"
            match2 = patterns[1].match(test_filename2)
            assert match2 is not None
            assert match2.group(1) == color_space

    def test_memory_usage_pattern_cache(self):
        """Test that pattern cache doesn't consume excessive memory."""

        initial_cache_size = len(RawPlateFinder._pattern_cache)

        # Generate many different pattern combinations
        shots = [f"SHOT_{i:03d}" for i in range(50)]
        plates = ["FG01", "BG01", "fg01", "bg01"]
        versions = [f"v{i:03d}" for i in range(1, 11)]

        for shot in shots:
            for plate in plates:
                for version in versions:
                    RawPlateFinder._get_plate_patterns(shot, plate, version)

        # Check cache size
        final_cache_size = len(RawPlateFinder._pattern_cache)
        expected_combinations = len(shots) * len(plates) * len(versions)

        assert final_cache_size == initial_cache_size + expected_combinations

        # Estimate memory usage (very rough)
        # Each cache entry contains 2 compiled pattern objects
        # Compiled patterns are relatively small (few KB each)
        estimated_memory_kb = final_cache_size * 2 * 2  # 2 patterns * ~2KB each

        # Should be reasonable memory usage (less than 20MB for this test)
        assert estimated_memory_kb < 20 * 1024, (
            f"Pattern cache using too much memory: ~{estimated_memory_kb}KB"
        )

        print(f"Pattern cache entries: {final_cache_size}")
        print(f"Estimated memory usage: ~{estimated_memory_kb}KB")

    def test_thread_safety_pattern_cache(self):
        """Test thread safety of pattern cache operations."""
        import concurrent.futures

        def worker_function(worker_id: int) -> List[str]:
            """Worker function for thread safety testing."""
            results = []
            for i in range(10):
                shot_name = f"WORKER_{worker_id}_SHOT_{i}"
                patterns = RawPlateFinder._get_plate_patterns(shot_name, "FG01", "v001")
                results.append(f"{shot_name}:{len(patterns)}")
            return results

        # Run multiple threads concurrently
        num_workers = 8
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_function, i) for i in range(num_workers)]

            # Wait for all threads to complete
            all_results = []
            for future in concurrent.futures.as_completed(futures):
                worker_results = future.result()
                all_results.extend(worker_results)

        # Verify all workers completed successfully
        assert len(all_results) == num_workers * 10

        # Verify cache contains all expected entries
        expected_entries = num_workers * 10
        assert len(RawPlateFinder._pattern_cache) >= expected_entries

        print(
            f"Thread safety test: {len(all_results)} operations completed successfully"
        )
        print(f"Cache entries after threading: {len(RawPlateFinder._pattern_cache)}")

    def test_regex_compilation_errors(self):
        """Test handling of regex compilation errors."""
        # Test with invalid regex characters in shot name
        invalid_shots = [
            "SHOT[WITH]BRACKETS",  # These should work fine actually
            "SHOT(WITH)PARENS",  # These should work fine too
        ]

        for shot_name in invalid_shots:
            # Should not raise exceptions
            patterns = RawPlateFinder._get_plate_patterns(shot_name, "FG01", "v001")
            assert len(patterns) == 2

            # Patterns should still be usable
            assert isinstance(patterns[0], Pattern)
            assert isinstance(patterns[1], Pattern)

    def test_performance_regression_detection(self):
        """Test for performance regression detection."""
        # This test sets up baseline expectations for performance
        test_filenames = [
            "108_CHV_0015_turnover-plate_FG01_aces_v001.1001.exr",
            "109_ABC_0020_turnover-plate_BG01_lin_sgamut3cine_v002.1002.exr",
        ]

        iterations = 50
        max_acceptable_time_ms = 100  # 100ms should be more than enough

        start_time = time.time()
        matches = self._optimized_regex_matching(test_filenames, iterations)
        end_time = time.time()

        elapsed_ms = (end_time - start_time) * 1000

        assert elapsed_ms < max_acceptable_time_ms, (
            f"Performance regression detected: took {elapsed_ms:.2f}ms, "
            f"expected < {max_acceptable_time_ms}ms"
        )

        assert matches == iterations * 2  # Should match 2 files per iteration

        print(f"Performance test: {iterations} iterations in {elapsed_ms:.2f}ms")
        print(f"Average per iteration: {elapsed_ms / iterations:.3f}ms")
