"""Property-based tests using Hypothesis for path parsing and validation.

This module tests invariants that must hold for all inputs, following
UNIFIED_TESTING_GUIDE best practices for property-based testing.

Key Properties Tested:
    - Shot path parsing roundtrips correctly
    - Path validation handles edge cases consistently
    - Workspace command parsing handles any valid format
"""

from __future__ import annotations

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

# Local application imports
from config import Config


pytestmark = [pytest.mark.unit, pytest.mark.slow]


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

    Uses hardcoded /shows prefix to avoid dependency on mutable Config.Paths.SHOWS_ROOT,
    which can cause FlakyStrategyDefinition errors when other tests monkeypatch it.
    """
    show = draw(show_name())
    seq = draw(sequence_name())
    shot = draw(shot_number())
    # Standard VFX shot path structure with hardcoded prefix (avoids global state)
    return f"/shows/{show}/shots/{seq}/{seq}_{shot}"


class TestShotPathProperties:
    """Property-based tests for shot path operations."""

    @given(show_name(), sequence_name(), shot_number())
    @settings(max_examples=25, deadline=None)
    def test_shot_creation_and_roundtrip(self, show: str, seq: str, shot: str) -> None:
        """Shot fields must round-trip through Shot construction.

        Builds the workspace path from components, constructs a Shot, then
        asserts every field reflects the original inputs exactly.
        """
        # Local application imports
        from type_definitions import Shot

        workspace = f"{Config.Paths.SHOWS_ROOT}/{show}/shots/{seq}/{seq}_{shot}"
        shot_obj = Shot(show, seq, f"{seq}_{shot}", workspace)

        assert shot_obj.show == show
        assert shot_obj.sequence == seq
        assert shot_obj.shot == f"{seq}_{shot}"
        assert shot_obj.workspace_path == workspace


class TestWorkspaceCommandProperties:
    """Property-based tests for workspace command parsing."""

    @given(st.lists(shot_path(), min_size=0, max_size=50))
    @settings(max_examples=20, deadline=None)
    def test_workspace_parsing_consistency(self, paths) -> None:
        """Workspace output parsing should handle any valid format."""
        # Standard library imports
        import tempfile

        # Local application imports
        from shots.shot_model import (
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
        from shots.shot_model import (
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


class TestSceneFinderProperties:
    """Property-based tests for 3DE scene finder."""

    @settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
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
        from threede.scene_discovery_coordinator import (
            SceneDiscoveryCoordinator as ThreeDESceneFinder,
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
                # Empty scene list: finder should return an empty result
                scenes = finder.find_scenes_for_shot(
                    str(shot_path), "test", "seq01", "seq01_0010"
                )
                assert scenes == []


# Test runner for standalone execution
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
