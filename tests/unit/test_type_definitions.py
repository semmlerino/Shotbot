"""Unit tests for type_definitions module.

This module tests:
1. Shot dataclass - field validation, serialization, thread safety
2. Protocols - compliance verification for existing implementations
3. TypedDict structures - required/optional field handling
4. Type aliases - correct type resolution

Following UNIFIED_TESTING_GUIDE best practices:
- Tests behavior, not implementation
- Uses real components where possible
- Minimal mocking at system boundaries
"""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path

import pytest

from type_definitions import (
    Shot,
    # TypedDicts
    ShotDict,
)


pytestmark = [pytest.mark.smoke]


# ==============================================================================
# Shot Dataclass Tests
# ==============================================================================


@pytest.mark.unit
class TestShotDataclass:
    """Tests for Shot dataclass correctness and behavior."""

    def test_shot_creation_with_required_fields(self) -> None:
        """Shot can be created with all required fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot.show == "testshow"
        assert shot.sequence == "sq010"
        assert shot.shot == "0010"
        assert shot.workspace_path == "/shows/testshow/shots/sq010/sq010_0010"

    def test_shot_discovered_at_can_be_set(self) -> None:
        """Shot discovered_at field can be explicitly set."""
        timestamp = time.time()
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=timestamp,
        )

        assert shot.discovered_at == timestamp

    def test_shot_full_name_property(self) -> None:
        """Shot.full_name returns sequence_shot format."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        assert shot.full_name == "sq010_0010"

    def test_shot_full_name_with_special_characters(self) -> None:
        """Shot.full_name works with special characters in sequence/shot names."""
        shot = Shot(
            show="testshow",
            sequence="101_ABC",
            shot="0010_v2",
            workspace_path="/shows/testshow/shots/101_ABC/101_ABC_0010_v2",
        )

        assert shot.full_name == "101_ABC_0010_v2"

    def test_shot_equality_semantics(self) -> None:
        """Shots with same values are equal; shots with different values are not."""
        base = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        same = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        different = Shot(
            show="testshow",
            sequence="sq010",
            shot="0020",  # Different shot
            workspace_path="/shows/testshow/shots/sq010/sq010_0020",
        )

        assert base == same
        assert base != different


@pytest.mark.unit
class TestShotSerialization:
    """Tests for Shot serialization to/from dictionary."""

    def test_to_dict_contains_required_fields(self) -> None:
        """Shot.to_dict() includes all required fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        result = shot.to_dict()

        assert result["show"] == "testshow"
        assert result["sequence"] == "sq010"
        assert result["shot"] == "0010"
        assert result["workspace_path"] == "/shows/testshow/shots/sq010/sq010_0010"

    def test_to_dict_includes_discovered_at(self) -> None:
        """Shot.to_dict() includes discovered_at timestamp."""
        timestamp = 1700000000.0
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=timestamp,
        )

        result = shot.to_dict()

        assert result["discovered_at"] == timestamp

    def test_to_dict_excludes_private_fields(self) -> None:
        """Shot.to_dict() does not include private/internal fields."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        result = shot.to_dict()

        # Private fields should not be serialized
        assert "_cached_thumbnail_path" not in result
        assert "_thumbnail_lock" not in result

    def test_from_dict_with_all_fields(self) -> None:
        """Shot.from_dict() creates shot with all provided fields."""
        data: ShotDict = {
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
            "discovered_at": 1700000000.0,
        }

        shot = Shot.from_dict(data)

        assert shot.show == "testshow"
        assert shot.sequence == "sq010"
        assert shot.shot == "0010"
        assert shot.workspace_path == "/shows/testshow/shots/sq010/sq010_0010"
        assert shot.discovered_at == 1700000000.0

    def test_from_dict_without_discovered_at(self) -> None:
        """Shot.from_dict() defaults discovered_at to 0.0 if not provided."""
        data: ShotDict = {
            "show": "testshow",
            "sequence": "sq010",
            "shot": "0010",
            "workspace_path": "/shows/testshow/shots/sq010/sq010_0010",
        }

        shot = Shot.from_dict(data)

        assert shot.discovered_at == 0.0

    def test_roundtrip_serialization(self) -> None:
        """Shot serialization roundtrip preserves all data."""
        original = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=1700000000.0,
        )

        serialized = original.to_dict()
        restored = Shot.from_dict(serialized)

        assert restored == original


@pytest.mark.unit
class TestShotThumbnailCaching:
    """Tests for Shot thumbnail path caching behavior."""

    def test_thumbnail_cache_initially_not_searched(self) -> None:
        """Shot thumbnail cache starts in 'not searched' state."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        # The sentinel value indicates not yet searched
        from type_definitions import _NOT_SEARCHED

        assert shot._cached_thumbnail_path is _NOT_SEARCHED

    def test_thumbnail_lock_per_instance(self) -> None:
        """Each Shot instance has its own lock (not shared)."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0020",
            workspace_path="/shows/testshow/shots/sq010/sq010_0020",
        )

        assert shot1._thumbnail_lock is not shot2._thumbnail_lock

    def test_thumbnail_cache_not_included_in_equality(self) -> None:
        """Thumbnail cache state doesn't affect Shot equality."""
        shot1 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )
        shot2 = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        # Artificially set different cache states
        shot1._cached_thumbnail_path = None
        shot2._cached_thumbnail_path = Path("/some/path.jpg")

        # Should still be equal (compare=False on cache field)
        assert shot1 == shot2


@pytest.mark.unit
class TestShotThreadSafety:
    """Tests for Shot thread safety in concurrent scenarios."""

    def test_concurrent_thumbnail_access_no_crash(self) -> None:
        """Multiple threads accessing thumbnail path don't cause crashes."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
        )

        errors: list[Exception] = []

        def access_thumbnail() -> None:
            try:
                # Access the lock attribute (don't call get_thumbnail_path
                # as it requires real filesystem)
                with shot._thumbnail_lock:
                    pass
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        # Run many concurrent accesses
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(access_thumbnail) for _ in range(100)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Thread errors occurred: {errors}"


# ==============================================================================
# Edge Case Tests
# ==============================================================================


@pytest.mark.unit
class TestShotEdgeCases:
    """Tests for Shot edge cases and boundary conditions."""

    @pytest.mark.parametrize(
        ("show", "sequence", "shot_num", "workspace_path", "expected_full_name"),
        [
            ("", "", "", "", "_"),  # empty strings
            (
                "テスト",
                "日本語",
                "0010",
                "/shows/テスト/shots/日本語/日本語_0010",
                "日本語_0010",
            ),  # unicode
            (
                "testshow",
                "sq010",
                "0010",
                "/shows/" + "a" * 500 + "/shots/seq/shot",
                "sq010_0010",
            ),  # long path
            (
                "test-show_v2",
                "sq.010",
                "0010-final",
                "/shows/test-show_v2/shots/sq.010/sq.010_0010-final",
                "sq.010_0010-final",
            ),  # special chars
        ],
    )
    def test_field_edge_cases(
        self,
        show: str,
        sequence: str,
        shot_num: str,
        workspace_path: str,
        expected_full_name: str,
    ) -> None:
        """Shot handles edge-case field values correctly."""
        shot = Shot(
            show=show,
            sequence=sequence,
            shot=shot_num,
            workspace_path=workspace_path,
        )

        assert shot.show == show
        assert shot.sequence == sequence
        assert shot.shot == shot_num
        assert shot.workspace_path == workspace_path
        assert shot.full_name == expected_full_name

    @pytest.mark.parametrize("timestamp", [-1000.0, 32503680000.0])
    def test_discovered_at_extreme_timestamps(self, timestamp: float) -> None:
        """Shot accepts extreme discovered_at values."""
        shot = Shot(
            show="testshow",
            sequence="sq010",
            shot="0010",
            workspace_path="/shows/testshow/shots/sq010/sq010_0010",
            discovered_at=timestamp,
        )

        assert shot.discovered_at == timestamp
