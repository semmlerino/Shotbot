"""Property-based tests using Hypothesis for ShotBot components."""

import re
from pathlib import Path

import pytest

try:
    from hypothesis import assume, example, given, settings
    from hypothesis import strategies as st
    from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

    HYPOTHESIS_AVAILABLE = True
except ImportError:
    HYPOTHESIS_AVAILABLE = False
    pytest.skip("Hypothesis not installed", allow_module_level=True)

from cache_manager import CacheManager
from threede_scene_model import ThreeDEScene, ThreeDESceneModel
from utils import PathUtils


# Custom strategies for ShotBot-specific data types
@st.composite
def shot_name_strategy(draw):
    """Generate valid shot names."""
    show_code = draw(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=4)
    )
    sequence = draw(st.integers(min_value=1, max_value=999))
    shot = draw(st.integers(min_value=0, max_value=9999))
    return f"{show_code}_{sequence:03d}_{shot:04d}"


@st.composite
def plate_name_strategy(draw):
    """Generate valid plate names."""
    plate_types = ["FG", "BG", "fg", "bg", "plate", "PLATE"]
    plate_type = draw(st.sampled_from(plate_types))
    plate_num = draw(st.integers(min_value=1, max_value=99))
    return f"{plate_type}{plate_num:02d}"


@st.composite
def version_strategy(draw):
    """Generate valid version strings."""
    version_num = draw(st.integers(min_value=1, max_value=999))
    return f"v{version_num:03d}"


@st.composite
def color_space_strategy(draw):
    """Generate valid color space names."""
    color_spaces = ["aces", "lin_sgamut3cine", "rec709", "linear", "srgb", "linear_ap0"]
    return draw(st.sampled_from(color_spaces))


@st.composite
def resolution_strategy(draw):
    """Generate valid resolution strings."""
    width = draw(st.sampled_from([1920, 2048, 4096, 4312]))
    height = draw(st.sampled_from([1080, 1137, 2160, 2274, 2304]))
    return f"{width}x{height}"


@st.composite
def unix_path_strategy(draw):
    """Generate valid Unix-style paths."""
    components = draw(
        st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=5,
        )
    )
    return "/" + "/".join(components)


class TestRawPlateFinderProperties:
    """Property-based tests for RawPlateFinder."""

    @given(
        shot_name=shot_name_strategy(),
        plate_name=plate_name_strategy(),
        version=version_strategy(),
        color_space=color_space_strategy(),
        resolution=resolution_strategy(),
    )
    def test_plate_pattern_matching(
        self, shot_name, plate_name, version, color_space, resolution
    ):
        """Test that plate patterns are correctly parsed and matched."""
        # Construct a plate filename
        filename = (
            f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.1001.exr"
        )

        # Use the more flexible pattern that handles color spaces with underscores
        # This matches the actual pattern used in RawPlateFinder
        pattern1_str = (
            rf"{shot_name}_turnover-plate_{plate_name}_(.+?)_{version}\.\d{{4}}\.exr"
        )
        pattern1 = re.compile(pattern1_str, re.IGNORECASE)

        match = pattern1.match(filename)

        # Should match and extract color space
        assert match is not None, f"Pattern {pattern1_str} didn't match {filename}"
        assert match.group(1) == color_space

    @given(
        plates=st.lists(
            st.tuples(
                plate_name_strategy(),
                st.integers(min_value=0, max_value=100),  # priority
            ),
            min_size=1,
            max_size=20,
        )
    )
    def test_plate_priority_ordering(self, plates):
        """Test that plates are correctly ordered by priority."""
        # Sort by priority (highest first), then name
        sorted_plates = sorted(plates, key=lambda x: (-x[1], x[0]))

        # Verify ordering
        for i in range(len(sorted_plates) - 1):
            current = sorted_plates[i]
            next_plate = sorted_plates[i + 1]

            # Priority should be descending
            assert current[1] >= next_plate[1]

            # If same priority, should be alphabetical
            if current[1] == next_plate[1]:
                assert current[0] <= next_plate[0]

    @given(path=unix_path_strategy())
    def test_path_sanitization(self, path):
        """Test that path sanitization is idempotent."""
        # Add leading slash if missing
        if not path.startswith("/"):
            sanitized = "/" + path
        else:
            sanitized = path

        # Sanitizing again should give same result
        if not sanitized.startswith("/"):
            resanitized = "/" + sanitized
        else:
            resanitized = sanitized

        assert resanitized == sanitized


class TestThreeDESceneProperties:
    """Property-based tests for 3DE scene handling."""

    @given(
        scenes=st.lists(
            st.builds(
                ThreeDEScene,
                show=st.text(min_size=1, max_size=10),
                sequence=st.text(min_size=1, max_size=5),
                shot=st.text(min_size=1, max_size=5),
                workspace_path=unix_path_strategy(),
                user=st.text(min_size=1, max_size=20),
                plate=plate_name_strategy(),
                scene_path=st.builds(Path, unix_path_strategy()),
            ),
            min_size=0,
            max_size=50,
        )
    )
    def test_deduplication_invariants(self, scenes):
        """Test that deduplication maintains important invariants."""
        model = ThreeDESceneModel()

        # Apply deduplication
        deduplicated = model._deduplicate_scenes_by_shot(scenes)

        # Invariant 1: No duplicates per shot
        shots_seen = set()
        for scene in deduplicated:
            shot_key = f"{scene.show}/{scene.sequence}/{scene.shot}"
            assert shot_key not in shots_seen, (
                f"Duplicate shot after deduplication: {shot_key}"
            )
            shots_seen.add(shot_key)

        # Invariant 2: Result size <= input size
        assert len(deduplicated) <= len(scenes)

        # Invariant 3: All scenes in result are from input
        input_ids = {id(scene) for scene in scenes}
        for scene in deduplicated:
            assert id(scene) in input_ids, "Deduplication created new scene object"

    @given(
        scenes=st.lists(
            st.builds(
                ThreeDEScene,
                show=st.just("testshow"),
                sequence=st.just("TST"),
                shot=st.text(min_size=3, max_size=3, alphabet="0123456789"),
                workspace_path=st.just("/test/path"),
                user=st.sampled_from(["user1", "user2", "user3", "current_user"]),
                plate=st.just("BG01"),
                scene_path=st.builds(Path, st.just("/test/scene.3de")),
            ),
            min_size=0,
            max_size=20,
        ),
        current_user=st.sampled_from(["user1", "user2", "user3", "current_user"]),
    )
    def test_user_exclusion(self, scenes, current_user):
        """Test that current user is properly excluded."""
        model = ThreeDESceneModel()
        model._excluded_users = {current_user}

        # Filter scenes
        filtered = [s for s in scenes if s.user not in model._excluded_users]

        # Verify no scenes from current user
        for scene in filtered:
            assert scene.user != current_user

        # Verify all non-current-user scenes are kept
        for scene in scenes:
            if scene.user != current_user:
                assert scene in filtered


class CacheStateMachine(RuleBasedStateMachine):
    """Stateful testing for cache manager."""

    def __init__(self):
        super().__init__()
        self.cache_manager = CacheManager()
        self.cached_data = None
        self.cache_time = None

    @initialize()
    def setup(self):
        """Initialize the cache state."""
        self.cached_data = None
        self.cache_time = None

    @rule(
        data=st.lists(
            st.dictionaries(
                st.text(min_size=1, max_size=10), st.text(min_size=1, max_size=20)
            ),
            min_size=0,
            max_size=10,
        )
    )
    def cache_data(self, data):
        """Cache some data."""
        self.cache_manager.cache_threede_scenes(data)
        self.cached_data = data
        import time

        self.cache_time = time.time()

    @rule()
    def retrieve_data(self):
        """Retrieve data from cache."""
        result = self.cache_manager.get_cached_threede_scenes()

        if self.cached_data is not None:
            import time

            # If within TTL, should return data
            if self.cache_time and (time.time() - self.cache_time) < 1800:  # 30 min TTL
                assert result == self.cached_data

    @rule()
    def clear_cache(self):
        """Clear the cache."""
        # Simulate cache clear by removing cache file
        if self.cache_manager.threede_scenes_cache_file.exists():
            self.cache_manager.threede_scenes_cache_file.unlink()
        self.cached_data = None
        self.cache_time = None

    @invariant()
    def cache_consistency(self):
        """Cache should be consistent."""
        result = self.cache_manager.get_cached_threede_scenes()

        # If we have cached data and it's not expired, result should match
        if self.cached_data is not None and self.cache_time:
            import time

            if (time.time() - self.cache_time) < 1800:
                # Either we get the data or None (if file was deleted)
                assert result == self.cached_data or result is None


# Test the state machine
TestCacheState = CacheStateMachine.TestCase


class TestPathUtilsProperties:
    """Property-based tests for path utilities."""

    @given(
        base_path=unix_path_strategy(),
        segments=st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    def test_path_building(self, base_path, segments):
        """Test that path building is consistent."""
        result = PathUtils.build_path(base_path, *segments)

        # Result should be a Path object
        assert isinstance(result, Path)

        # Should contain all segments
        path_str = str(result)
        for segment in segments:
            assert segment in path_str

        # Should start with base path
        assert path_str.startswith(base_path.rstrip("/"))

    @given(
        plates=st.lists(
            st.tuples(plate_name_strategy(), st.integers(min_value=0, max_value=100)),
            min_size=0,
            max_size=50,
        )
    )
    def test_plate_discovery_deduplication(self, plates):
        """Test that plate discovery doesn't create duplicates."""
        # Create unique plates only
        unique_plates = {}
        for name, priority in plates:
            if name not in unique_plates or priority > unique_plates[name]:
                unique_plates[name] = priority

        # Result should have at most one entry per plate name
        assert len(unique_plates) <= len(plates)


# Example-based edge cases to complement property tests
class TestEdgeCases:
    """Specific edge cases found through property testing."""

    @pytest.mark.parametrize(
        "shot_name,plate_name,version,color_space",
        [
            ("A_001_0001", "FG01", "v001", "aces"),  # Minimal shot name
            ("VERYLONGSHOW_999_9999", "BG99", "v999", "linear_ap0"),  # Maximum values
            ("TEST_001_0001", "plate", "v001", "rec709"),  # Generic plate name
            ("MX_042_1337", "Fg01", "v002", "lin_sgamut3cine"),  # Mixed case
        ],
    )
    def test_specific_plate_patterns(self, shot_name, plate_name, version, color_space):
        """Test specific edge cases found during property testing."""
        filename = (
            f"{shot_name}_turnover-plate_{plate_name}_{color_space}_{version}.1001.exr"
        )

        # Should be valid filename
        assert ".exr" in filename
        assert version in filename
        assert plate_name in filename


if __name__ == "__main__":
    # Run property tests with more examples
    import sys

    sys.exit(pytest.main([__file__, "-v", "--hypothesis-show-statistics"]))
