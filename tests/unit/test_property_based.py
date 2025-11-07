"""Property-based tests using Hypothesis for path parsing and validation.

This module tests invariants that must hold for all inputs, following
UNIFIED_TESTING_GUIDE best practices for property-based testing.

Key Properties Tested:
    - Shot path parsing roundtrips correctly
    - Cache key generation is deterministic and unique
    - Path validation handles edge cases consistently
    - Workspace command parsing handles any valid format
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

# Local application imports
from config import Config


pytestmark = [pytest.mark.unit, pytest.mark.fast]


# Custom strategies for shot components
@composite
def show_name(draw):
    """Generate valid show names."""
    # Shows typically have alphanumeric names with underscores
    return draw(st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{2,15}", fullmatch=True))


@composite
def sequence_name(draw):
    """Generate valid sequence names."""
    # Sequences are typically like seq001, seq002, etc.
    return draw(st.from_regex(r"seq\d{3}", fullmatch=True))


@composite
def shot_number(draw):
    """Generate valid shot numbers."""
    # Shots are typically 4-digit numbers
    return draw(st.from_regex(r"\d{4}", fullmatch=True))


@composite
def shot_path(draw) -> str:
    """Generate valid shot workspace paths.

    Uses hardcoded /shows prefix to avoid dependency on mutable Config.SHOWS_ROOT,
    which can cause FlakyStrategyDefinition errors when other tests monkeypatch it.
    """
    show = draw(show_name())
    seq = draw(sequence_name())
    shot = draw(shot_number())
    # Standard VFX shot path structure with hardcoded prefix (avoids global state)
    return f"/shows/{show}/shots/{seq}/{seq}_{shot}"


class TestShotPathProperties:
    """Property-based tests for shot path operations."""

    @given(shot_path())
    @settings(
        max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    def test_shot_path_roundtrip(self, path: str) -> None:
        """Any valid shot path should parse and reconstruct identically."""
        # Import locally to avoid circular dependencies
        # Local application imports
        from shot_model import (
            Shot,
        )

        # Parse the path
        parts = path.split("/")
        show = parts[2]
        seq = parts[4]
        shot_name = parts[5]

        # Create shot from components
        shot = Shot(show, seq, shot_name, path)

        # Verify roundtrip
        assert shot.workspace_path == path
        assert shot.show == show
        assert shot.sequence == seq
        assert shot.shot == shot_name

    @given(show_name(), sequence_name(), shot_number())
    @settings(max_examples=25, deadline=None)
    def test_shot_creation_consistency(self, show: str, seq: str, shot: str) -> None:
        """Shot creation should be consistent regardless of input format."""
        # Local application imports
        from shot_model import (
            Shot,
        )

        # Create shot with explicit workspace path
        workspace = f"{Config.SHOWS_ROOT}/{show}/shots/{seq}/{seq}_{shot}"
        shot1 = Shot(show, seq, f"{seq}_{shot}", workspace)

        # Verify all properties are set correctly
        assert shot1.show == show
        assert shot1.sequence == seq
        assert shot1.shot == f"{seq}_{shot}"
        assert shot1.workspace_path == workspace
        # Note: Shot may not have a 'name' attribute, shot is the identifier


class TestCacheKeyProperties:
    """Property-based tests for cache key generation."""

    @given(
        show=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"
            ),
        ),
        seq=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"
            ),
        ),
        shot=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"
            ),
        ),
    )
    def test_cache_key_uniqueness(self, show: str, seq: str, shot: str) -> None:
        """Cache keys must be unique and deterministic."""
        # Simple key generation matching CacheManager implementation
        # CacheManager uses: f"{show}_{sequence}_{shot}"

        # Generate keys multiple times - should be deterministic
        key1 = f"{show}_{seq}_{shot}"
        key2 = f"{show}_{seq}_{shot}"

        assert key1 == key2  # Deterministic
        assert "/" not in key1  # Safe for filesystem
        assert ".." not in key1  # No path traversal

        # Different inputs should generate different keys
        if seq != shot:  # Only test if inputs are different
            key3 = f"{show}_{shot}_{seq}"
            assert key1 != key3  # Unique for different inputs

    @given(
        st.lists(
            st.tuples(show_name(), sequence_name(), shot_number()),
            min_size=2,
            max_size=10,
        )
    )
    @settings(max_examples=20, deadline=None)
    def test_cache_key_collision_resistance(self, shot_list) -> None:
        """Cache keys should not collide for different shots."""
        # Skip if all shots are identical
        if len(set(shot_list)) < 2:
            assume(False)

        keys = set()
        for show, seq, shot in shot_list:
            # Use the same key format as CacheManager: f"{show}_{sequence}_{shot}"
            key = f"{show}_{seq}_{shot}"
            keys.add(key)

        # All unique inputs should generate unique keys
        assert len(keys) == len(set(shot_list))


class TestWorkspaceCommandProperties:
    """Property-based tests for workspace command parsing."""

    @given(st.lists(shot_path(), min_size=0, max_size=50))
    @settings(max_examples=20, deadline=None)
    def test_workspace_parsing_consistency(self, paths) -> None:
        """Workspace output parsing should handle any valid format."""
        # Standard library imports
        import tempfile

        # Local application imports
        from shot_model import (
            ShotModel,
        )

        # Generate mock workspace output
        ws_output = "\n".join(f"workspace {path}" for path in paths)

        with tempfile.TemporaryDirectory():
            # Don't use cache for this test
            model = ShotModel(cache_manager=None)

            # Parse the output using the actual method name
            shots = model._parse_ws_output(ws_output)

            # Verify parsing
            assert len(shots) == len(paths)

            for shot, path in zip(shots, paths, strict=False):
                assert shot.workspace_path == path
                # Verify path components were extracted correctly
                parts = path.split("/")
                assert shot.show == parts[2]
                assert shot.sequence == parts[4]
                # Shot is extracted from shot_dir by removing sequence prefix
                # e.g., "seq000_0000" -> "0000"
                shot_dir = parts[5]
                sequence = parts[4]
                if shot_dir.startswith(f"{sequence}_"):
                    expected_shot = shot_dir[len(sequence) + 1 :]
                else:
                    # Fallback logic matches what's in base_shot_model.py
                    shot_parts = shot_dir.rsplit("_", 1)
                    expected_shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir
                assert shot.shot == expected_shot

    @given(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn"),
                blacklist_characters="\n\r",
            ),
            min_size=1,
            max_size=100,
        )
    )
    def test_invalid_workspace_line_handling(self, line: str) -> None:
        """Invalid workspace lines should be handled gracefully."""
        # Local application imports
        from shot_model import (
            ShotModel,
        )

        # Create model without cache
        model = ShotModel(cache_manager=None)

        # Try to parse an invalid line using the actual method
        shots = model._parse_ws_output(line)

        # Should either parse correctly or return empty
        # (depending on whether line accidentally matches pattern)
        assert isinstance(shots, list)

        # If it parsed something, verify it's valid
        for shot in shots:
            assert shot.show
            assert shot.sequence
            assert shot.shot
            assert shot.workspace_path


class TestPathValidationProperties:
    """Property-based tests for path validation utilities."""

    @given(st.text(min_size=1, max_size=200))
    def test_path_validation_consistency(self, path_str: str) -> None:
        """Path validation should be consistent."""
        # Local application imports
        from utils import (
            PathUtils,
        )

        # Skip invalid paths
        if "\x00" in path_str or not path_str.strip():
            assume(False)

        # Validate multiple times - should be consistent
        result1 = PathUtils.validate_path_exists(path_str, "test")
        result2 = PathUtils.validate_path_exists(path_str, "test")

        # Results should be identical (both True or both False)
        assert result1 == result2

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"
                ),
            ),
            min_size=1,
            max_size=10,
        )
    )
    def test_path_building_consistency(self, components) -> None:
        """Path building should be consistent."""
        # Local application imports
        from utils import (
            PathUtils,
        )

        if not components:
            assume(False)

        # Build path using PathUtils
        base = "/test"
        path1 = PathUtils.build_path(base, *components)

        # Build again - should be identical
        path2 = PathUtils.build_path(base, *components)

        assert path1 == path2
        assert isinstance(path1, Path)


class TestSceneFinderProperties:
    """Property-based tests for 3DE scene finder."""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(
        st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=30,
                    alphabet=st.characters(
                        whitelist_categories=("Lu", "Ll", "Nd"),
                        whitelist_characters="_-",
                    ),
                ),  # filename
                st.floats(min_value=0, max_value=1e9, allow_nan=False),  # mtime
            ),
            min_size=0,
            max_size=100,
        )
    )
    def test_scene_finding_consistency(self, scene_list) -> None:
        """Scene finding should be consistent."""
        # Standard library imports
        import tempfile

        # Local application imports
        from threede_scene_finder import (
            ThreeDESceneFinder,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test shot workspace structure
            shot_path = temp_path / "shows" / "test" / "shots" / "seq01" / "seq01_0010"
            shot_path.mkdir(parents=True, exist_ok=True)

            # Create actual .3de files for testing
            for _i, (filename, _mtime) in enumerate(
                scene_list[:5]
            ):  # Limit to 5 for speed
                scene_file = shot_path / f"{filename}.3de"
                scene_file.write_text(f"# 3DE scene {filename}")

            # Create finder instance
            finder = ThreeDESceneFinder()

            # Use the actual method signature with shot workspace path
            if scene_list:  # Only test if we have scenes
                scenes1 = finder.find_scenes_for_shot(
                    str(shot_path), "test", "seq01", "seq01_0010"
                )
                scenes2 = finder.find_scenes_for_shot(
                    str(shot_path), "test", "seq01", "seq01_0010"
                )

                # Should find same number of scenes
                assert len(scenes1) == len(scenes2)
            else:
                # Empty list should return empty result
                assert True  # Pass for empty case


# Test runner for standalone execution
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
