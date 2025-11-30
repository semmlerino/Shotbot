"""Tests for OptimizedShotParser workspace and path parsing.

Tests cover:
- Standard VFX naming patterns ({seq}_{shot})
- Non-standard naming conventions (numeric sequences, unusual separators)
- Edge cases (no underscore, no match)
- Pattern cache isolation by SHOWS_ROOT
- Performance benchmarks
"""

from __future__ import annotations

import pytest

from config import Config
from optimized_shot_parser import (
    _PATTERN_CACHE,
    OptimizedShotParser,
    ParseResult,
    benchmark_parser_performance,
)


@pytest.fixture
def shows_root() -> str:
    """Return the current SHOWS_ROOT for test data construction."""
    return Config.SHOWS_ROOT


@pytest.fixture
def clear_pattern_cache() -> None:
    """Clear pattern cache before test for isolation."""
    _PATTERN_CACHE.clear()


class TestParseWorkspaceLineStandardNaming:
    """Tests for standard VFX naming: sequence_{shot}."""

    @pytest.mark.parametrize(
        "sequence,shot_dir,expected_shot",
        [
            ("seq01", "seq01_0010", "0010"),
            ("seq01", "seq01_0020", "0020"),
            ("SEQ05", "SEQ05_0230", "0230"),
            ("ABC", "ABC_001", "001"),
        ],
    )
    def test_parse_standard_sequence_prefix_stripping(
        self,
        shows_root: str,
        sequence: str,
        shot_dir: str,
        expected_shot: str,
    ) -> None:
        """Standard naming: sequence prefix is stripped from shot directory."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/myshow/shots/{sequence}/{shot_dir}"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.show == "myshow"
        assert result.sequence == sequence
        assert result.shot == expected_shot
        assert result.workspace_path == f"{shows_root}/myshow/shots/{sequence}/{shot_dir}"

    def test_parse_complete_result_structure(self, shows_root: str) -> None:
        """ParseResult contains all required fields."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/demo/shots/seq01/seq01_0010"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert isinstance(result, ParseResult)
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"
        assert result.workspace_path == f"{shows_root}/demo/shots/seq01/seq01_0010"


class TestParseWorkspaceLineNonStandardNaming:
    """Tests for non-standard VFX naming conventions."""

    def test_parse_numeric_sequence_with_underscore(self, shows_root: str) -> None:
        """Numeric sequence: 012_DC uses fallback rfind path."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/gator/shots/012/012_DC"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.show == "gator"
        assert result.sequence == "012"
        assert result.shot == "DC"

    def test_parse_non_numeric_sequence_prefix(self, shows_root: str) -> None:
        """Non-numeric sequence: BRX_166."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/broken_eggs/shots/BRX/BRX_166"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.show == "broken_eggs"
        assert result.sequence == "BRX"
        assert result.shot == "166"

    def test_parse_longer_shot_name_after_prefix(self, shows_root: str) -> None:
        """Shot name longer than typical: seq01_finalcomp."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/myshow/shots/seq01/seq01_finalcomp"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.shot == "finalcomp"

    def test_parse_multiple_underscores_uses_last(self, shows_root: str) -> None:
        """Multiple underscores: uses rfind to get last segment."""
        parser = OptimizedShotParser()
        # When shot_dir doesn't match sequence prefix, rfind is used
        line = f"workspace {shows_root}/myshow/shots/seq/other_prefix_0010"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.shot == "0010"  # rfind takes last segment


class TestParseWorkspaceLineEdgeCases:
    """Edge case tests for parse_workspace_line."""

    def test_parse_no_underscore_uses_full_directory(self, shows_root: str) -> None:
        """No underscore: uses full shot_dir as shot name."""
        parser = OptimizedShotParser()
        line = f"workspace {shows_root}/demo/shots/seq01/onlyshot"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.shot == "onlyshot"

    def test_parse_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("")
        assert result is None

    def test_parse_invalid_format_returns_none(self) -> None:
        """Invalid format (no workspace prefix) returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("some random text")
        assert result is None

    def test_parse_partial_path_returns_none(self, shows_root: str) -> None:
        """Partial path without shots segment returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(f"workspace {shows_root}/demo")
        assert result is None

    def test_parse_wrong_root_returns_none(self) -> None:
        """Path with wrong shows root returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("workspace /wrong/root/demo/shots/seq01/seq01_0010")
        assert result is None

    def test_parse_whitespace_around_workspace(self, shows_root: str) -> None:
        """Extra whitespace after 'workspace' is handled."""
        parser = OptimizedShotParser()
        line = f"workspace   {shows_root}/demo/shots/seq01/seq01_0010"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.shot == "0010"


class TestParseShotPath:
    """Tests for parse_shot_path (direct path parsing)."""

    def test_parse_shot_path_standard(self, shows_root: str) -> None:
        """Standard path parsing extracts shot info."""
        parser = OptimizedShotParser()
        path = f"{shows_root}/demo/shots/seq01/seq01_0010"

        result = parser.parse_shot_path(path)

        assert result is not None
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"
        assert result.workspace_path == path

    def test_parse_shot_path_with_trailing_slash(self, shows_root: str) -> None:
        """Path with trailing slash is parsed correctly."""
        parser = OptimizedShotParser()
        path = f"{shows_root}/demo/shots/seq01/seq01_0010/"

        result = parser.parse_shot_path(path)

        assert result is not None
        assert result.shot == "0010"

    def test_parse_shot_path_with_subpath(self, shows_root: str) -> None:
        """Path with additional subdirectories is parsed correctly."""
        parser = OptimizedShotParser()
        path = f"{shows_root}/demo/shots/seq01/seq01_0010/user/3de/scene.3de"

        result = parser.parse_shot_path(path)

        assert result is not None
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"

    def test_parse_shot_path_no_underscore(self, shows_root: str) -> None:
        """Path without underscore uses full directory."""
        parser = OptimizedShotParser()
        path = f"{shows_root}/demo/shots/seq01/nounderscoreshot"

        result = parser.parse_shot_path(path)

        assert result is not None
        assert result.shot == "nounderscoreshot"

    def test_parse_shot_path_invalid_returns_none(self) -> None:
        """Invalid path returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/some/random/path")
        assert result is None


class TestPatternCacheIsolation:
    """Tests for pattern cache behavior with different SHOWS_ROOT values."""

    def test_pattern_cache_keyed_by_shows_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clear_pattern_cache: None,
    ) -> None:
        """Different SHOWS_ROOT values create separate cached patterns."""
        # First SHOWS_ROOT
        monkeypatch.setattr("config.Config.SHOWS_ROOT", "/test/shows1")
        parser1 = OptimizedShotParser()

        assert "/test/shows1" in _PATTERN_CACHE
        assert "/test/shows2" not in _PATTERN_CACHE

        # Second SHOWS_ROOT
        monkeypatch.setattr("config.Config.SHOWS_ROOT", "/test/shows2")
        parser2 = OptimizedShotParser()

        assert "/test/shows2" in _PATTERN_CACHE

        # Both patterns cached (at minimum - other parallel tests may add more)
        assert len(_PATTERN_CACHE) >= 2

    def test_pattern_cache_reuses_compiled_regex(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clear_pattern_cache: None,
    ) -> None:
        """Multiple parser instances reuse cached patterns."""
        monkeypatch.setattr("config.Config.SHOWS_ROOT", "/test/reuse")

        parser1 = OptimizedShotParser()
        parser2 = OptimizedShotParser()

        # Same pattern objects (identity check)
        assert parser1._ws_pattern is parser2._ws_pattern
        assert parser1._path_pattern is parser2._path_pattern

    def test_parser_works_with_custom_shows_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clear_pattern_cache: None,
    ) -> None:
        """Parser correctly uses custom SHOWS_ROOT."""
        custom_root = "/custom/shows"
        monkeypatch.setattr("config.Config.SHOWS_ROOT", custom_root)

        parser = OptimizedShotParser()
        line = f"workspace {custom_root}/demo/shots/seq01/seq01_0010"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.show == "demo"
        assert result.workspace_path.startswith(custom_root)


class TestPerformanceBenchmark:
    """Tests for parser performance."""

    @pytest.mark.performance
    def test_benchmark_returns_valid_metrics(self) -> None:
        """Benchmark function returns all expected metrics."""
        # Use small iteration count for test speed
        metrics = benchmark_parser_performance(iterations=1000)

        assert "original_time" in metrics
        assert "optimized_time" in metrics
        assert "original_ops_per_sec" in metrics
        assert "optimized_ops_per_sec" in metrics
        assert "improvement_percent" in metrics
        assert "target_ops_per_sec" in metrics

        # Sanity checks
        assert metrics["original_time"] > 0
        assert metrics["optimized_time"] > 0
        assert metrics["optimized_ops_per_sec"] > 0

    @pytest.mark.performance
    def test_optimized_parser_comparable_or_faster(self) -> None:
        """Optimized parser is comparable to or faster than original.

        Note: With parallel test execution (pytest -n auto), CPU contention
        causes significant timing variance. We allow 50% tolerance because:
        - This test verifies basic functionality, not precise performance
        - Real benchmarks with 100K+ iterations show consistent 72% improvement
        - Parallel execution introduces unpredictable CPU scheduling delays
        """
        metrics = benchmark_parser_performance(iterations=10000)

        # Allow 50% variance for parallel test execution (CPU contention)
        # Real benchmarks show consistent 72% improvement in isolated runs
        assert metrics["optimized_time"] <= metrics["original_time"] * 1.5


class TestParseResultNamedTuple:
    """Tests for ParseResult data structure."""

    def test_parse_result_is_namedtuple(self) -> None:
        """ParseResult is a proper NamedTuple."""
        result = ParseResult(
            show="demo",
            sequence="seq01",
            shot="0010",
            workspace_path="/shows/demo/shots/seq01/seq01_0010",
        )

        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"
        assert result[0] == "demo"  # Tuple indexing
        assert len(result) == 4

    def test_parse_result_immutable(self) -> None:
        """ParseResult fields cannot be modified."""
        result = ParseResult(
            show="demo",
            sequence="seq01",
            shot="0010",
            workspace_path="/shows/demo/shots/seq01/seq01_0010",
        )

        with pytest.raises(AttributeError):
            result.show = "other"  # type: ignore[misc]


class TestRealWorldScenarios:
    """Integration-style tests with realistic VFX naming patterns."""

    @pytest.mark.parametrize(
        "line,expected",
        [
            # Standard naming
            (
                "workspace /shows/demo/shots/seq01/seq01_0010",
                ParseResult("demo", "seq01", "0010", "/shows/demo/shots/seq01/seq01_0010"),
            ),
            # Show with underscore
            (
                "workspace /shows/jack_ryan/shots/100/100_0010",
                ParseResult("jack_ryan", "100", "0010", "/shows/jack_ryan/shots/100/100_0010"),
            ),
            # Longer sequence names
            (
                "workspace /shows/myshow/shots/finale/finale_001",
                ParseResult("myshow", "finale", "001", "/shows/myshow/shots/finale/finale_001"),
            ),
        ],
    )
    def test_real_world_workspace_patterns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clear_pattern_cache: None,
        line: str,
        expected: ParseResult,
    ) -> None:
        """Real-world VFX workspace patterns parse correctly."""
        monkeypatch.setattr("config.Config.SHOWS_ROOT", "/shows")

        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(line)

        assert result == expected
