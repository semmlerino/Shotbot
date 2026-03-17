"""Comprehensive tests for shot_filter functional filtering utilities.

Tests pure functions for filtering shot collections.
Following UNIFIED_TESTING_GUIDE principles:
- Test behavior, not implementation
- Use real components (no mocks for pure functions)
- Clear test names describing expected behavior
- Parametrization for multiple scenarios
"""

from __future__ import annotations

import pytest

from shots.shot_filter import (
    compose_filters,
    filter_by_show,
    filter_by_text,
    get_available_shows,
)
from type_definitions import Shot


pytestmark = [pytest.mark.smoke]


class TestFilterByShow:
    """Test filtering shots by show name."""

    def test_filter_by_show_returns_matching_shots(self) -> None:
        """Filter returns only shots matching the specified show."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
            Shot("show1", "seq2", "shot3", "/path3"),
        ]

        filtered = filter_by_show(shots, "show1")

        assert len(filtered) == 2
        assert all(shot.show == "show1" for shot in filtered)
        assert filtered[0].shot == "shot1"
        assert filtered[1].shot == "shot3"

    def test_filter_by_show_none_returns_all_shots(self) -> None:
        """Filter with None show returns all shots unchanged."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_show(shots, None)

        assert len(filtered) == 2
        assert filtered == shots

    def test_filter_by_show_no_matches_returns_empty_list(self) -> None:
        """Filter with non-existent show returns empty list."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_show(shots, "nonexistent")

        assert len(filtered) == 0
        assert filtered == []

    def test_filter_by_show_empty_input_returns_empty_list(self) -> None:
        """Filter with empty shot list returns empty list."""
        filtered = filter_by_show([], "show1")

        assert len(filtered) == 0
        assert filtered == []

    def test_filter_by_show_preserves_shot_type(self) -> None:
        """Filter preserves the Shot object type."""
        shots = [Shot("show1", "seq1", "shot1", "/path1")]

        filtered = filter_by_show(shots, "show1")

        assert len(filtered) == 1
        assert isinstance(filtered[0], Shot)
        assert filtered[0].show == "show1"


class TestFilterByText:
    """Test filtering shots by text substring."""

    def test_filter_by_text_case_insensitive_matching(self) -> None:
        """Filter matches text case-insensitively in full_name."""
        shots = [
            Shot("show1", "seq1", "SHOT1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
            Shot("show1", "seq2", "Shot3", "/path3"),
        ]

        filtered = filter_by_text(shots, "shot1")

        assert len(filtered) == 1
        assert filtered[0].shot == "SHOT1"

    def test_filter_by_text_matches_partial_names(self) -> None:
        """Filter matches partial strings within full_name."""
        shots = [
            Shot("show1", "seq010", "shot010", "/path1"),
            Shot("show1", "seq010", "shot020", "/path2"),
            Shot("show1", "seq020", "shot010", "/path3"),
        ]

        # Should match both shots with "010" in full_name
        filtered = filter_by_text(shots, "010")

        assert len(filtered) == 3  # All contain "010" somewhere
        assert all("010" in shot.full_name.lower() for shot in filtered)

    def test_filter_by_text_none_returns_all_shots(self) -> None:
        """Filter with None text returns all shots unchanged."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_text(shots, None)

        assert len(filtered) == 2
        assert filtered == shots

    def test_filter_by_text_empty_string_returns_all_shots(self) -> None:
        """Filter with empty string returns all shots unchanged."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_text(shots, "")

        assert len(filtered) == 2
        assert filtered == shots

    def test_filter_by_text_whitespace_only_returns_all_shots(self) -> None:
        """Filter with whitespace-only string returns all shots."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_text(shots, "   ")

        assert len(filtered) == 2
        assert filtered == shots

    def test_filter_by_text_no_matches_returns_empty_list(self) -> None:
        """Filter with non-matching text returns empty list."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_text(shots, "nonexistent")

        assert len(filtered) == 0
        assert filtered == []

    def test_filter_by_text_strips_whitespace(self) -> None:
        """Filter strips leading/trailing whitespace from search text."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_text(shots, "  shot1  ")

        assert len(filtered) == 1
        assert filtered[0].shot == "shot1"


class TestComposeFilters:
    """Test composed filtering with multiple criteria."""

    def test_compose_filters_applies_both_show_and_text(self) -> None:
        """Compose applies both show and text filters (AND logic)."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq2", "shot2", "/path2"),
            Shot("show2", "seq1", "shot1", "/path3"),
            Shot("show2", "seq2", "shot3", "/path4"),
        ]

        filtered = compose_filters(shots, show="show1", text="shot1")

        assert len(filtered) == 1
        assert filtered[0].show == "show1"
        assert filtered[0].shot == "shot1"

    def test_compose_filters_show_only(self) -> None:
        """Compose with show only applies show filter."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
            Shot("show1", "seq2", "shot3", "/path3"),
        ]

        filtered = compose_filters(shots, show="show1")

        assert len(filtered) == 2
        assert all(shot.show == "show1" for shot in filtered)

    def test_compose_filters_text_only(self) -> None:
        """Compose with text only applies text filter."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
            Shot("show1", "seq2", "shot1", "/path3"),
        ]

        filtered = compose_filters(shots, text="shot1")

        assert len(filtered) == 2
        assert all("shot1" in shot.full_name.lower() for shot in filtered)

    def test_compose_filters_no_filters_returns_all_shots(self) -> None:
        """Compose with no filters returns all shots unchanged."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
        ]

        filtered = compose_filters(shots)

        assert len(filtered) == 2
        assert filtered == shots

    def test_compose_filters_none_values_returns_all_shots(self) -> None:
        """Compose with explicit None values returns all shots."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
        ]

        filtered = compose_filters(shots, show=None, text=None)

        assert len(filtered) == 2
        assert filtered == shots

    def test_compose_filters_no_matches_returns_empty_list(self) -> None:
        """Compose with non-matching filters returns empty list."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
        ]

        filtered = compose_filters(shots, show="show1", text="nonexistent")

        assert len(filtered) == 0
        assert filtered == []

    def test_compose_filters_applies_in_order(self) -> None:
        """Compose applies filters in order: show first, then text."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
            Shot("show2", "seq1", "shot1", "/path3"),
        ]

        # First filters to show1 (2 shots), then filters to shot1 (1 shot)
        filtered = compose_filters(shots, show="show1", text="shot1")

        assert len(filtered) == 1
        assert filtered[0].show == "show1"
        assert filtered[0].shot == "shot1"


class TestGetAvailableShows:
    """Test extraction of unique show names."""

    def test_get_available_shows_returns_unique_shows(self) -> None:
        """Extract returns set of unique show names."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show2", "seq1", "shot2", "/path2"),
            Shot("show1", "seq2", "shot3", "/path3"),
            Shot("show3", "seq1", "shot4", "/path4"),
        ]

        shows = get_available_shows(shots)

        assert len(shows) == 3
        assert shows == {"show1", "show2", "show3"}

    def test_get_available_shows_single_show_returns_one_item(self) -> None:
        """Extract from single show returns set with one item."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq2", "shot2", "/path2"),
        ]

        shows = get_available_shows(shots)

        assert len(shows) == 1
        assert shows == {"show1"}

    def test_get_available_shows_empty_input_returns_empty_set(self) -> None:
        """Extract from empty list returns empty set."""
        shows = get_available_shows([])

        assert len(shows) == 0
        assert shows == set()

    def test_get_available_shows_returns_set_type(self) -> None:
        """Extract returns a set for efficient membership testing."""
        shots = [Shot("show1", "seq1", "shot1", "/path1")]

        shows = get_available_shows(shots)

        assert isinstance(shows, set)
        assert "show1" in shows


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.parametrize(
        ("show_filter", "text_filter", "expected_count"),
        [
            ("show1", None, 2),  # Show only
            (None, "shot1", 2),  # Text only
            ("show1", "shot1", 1),  # Both filters
            (None, None, 3),  # No filters
            ("nonexistent", "shot1", 0),  # No show match
            ("show1", "nonexistent", 0),  # No text match
        ],
        ids=[
            "show_only",
            "text_only",
            "both_filters",
            "no_filters",
            "no_show_match",
            "no_text_match",
        ],
    )
    def test_parametrized_filter_combinations(
        self,
        show_filter: str | None,
        text_filter: str | None,
        expected_count: int,
    ) -> None:
        """Test various filter combinations efficiently."""
        shots = [
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq2", "shot2", "/path2"),
            Shot("show2", "seq1", "shot1", "/path3"),
        ]

        filtered = compose_filters(shots, show=show_filter, text=text_filter)

        assert len(filtered) == expected_count

    def test_filter_with_special_characters_in_text(self) -> None:
        """Filter handles special characters in search text."""
        shots = [
            Shot("show1", "seq_01", "shot-01", "/path1"),
            Shot("show1", "seq_02", "shot.02", "/path2"),
        ]

        filtered = filter_by_text(shots, "shot-01")

        assert len(filtered) == 1
        assert filtered[0].shot == "shot-01"

    def test_filter_with_unicode_characters(self) -> None:
        """Filter handles Unicode characters correctly."""
        shots = [
            Shot("café", "seq1", "shot1", "/path1"),
            Shot("show1", "séq1", "shot2", "/path2"),
        ]

        filtered = filter_by_show(shots, "café")

        assert len(filtered) == 1
        assert filtered[0].show == "café"

    def test_filter_preserves_shot_order(self) -> None:
        """Filter maintains original shot order in results."""
        shots = [
            Shot("show1", "seq1", "shot3", "/path3"),
            Shot("show1", "seq1", "shot1", "/path1"),
            Shot("show1", "seq1", "shot2", "/path2"),
        ]

        filtered = filter_by_show(shots, "show1")

        assert len(filtered) == 3
        assert filtered[0].shot == "shot3"
        assert filtered[1].shot == "shot1"
        assert filtered[2].shot == "shot2"


class TestTypePreservation:
    """Test that filtering preserves type information."""

    def test_filter_returns_list_type(self) -> None:
        """All filter functions return list type."""
        shots = [Shot("show1", "seq1", "shot1", "/path1")]

        show_filtered = filter_by_show(shots, "show1")
        text_filtered = filter_by_text(shots, "shot1")
        composed = compose_filters(shots, show="show1")

        assert isinstance(show_filtered, list)
        assert isinstance(text_filtered, list)
        assert isinstance(composed, list)

    def test_filter_preserves_shot_attributes(self) -> None:
        """Filter preserves all Shot attributes."""
        original = Shot("show1", "seq1", "shot1", "/path/to/shot1")

        filtered = filter_by_show([original], "show1")

        assert len(filtered) == 1
        result = filtered[0]
        assert result.show == original.show
        assert result.sequence == original.sequence
        assert result.shot == original.shot
        assert result.workspace_path == original.workspace_path
        assert result.full_name == original.full_name
