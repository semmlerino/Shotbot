"""Unit tests for BaseAssetFinder class."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from base_asset_finder import BaseAssetFinder


class ConcreteAssetFinder(BaseAssetFinder):
    """Concrete implementation for testing."""

    def get_asset_directories(self, workspace: Path) -> list[Path]:
        """Get test asset directories."""
        return [
            workspace / "textures",
            workspace / "cache",
            workspace / "renders",
        ]

    def get_asset_patterns(self) -> list[str]:
        """Get test asset patterns."""
        return ["*.exr", "*.jpg", "*.abc"]


class TestBaseAssetFinder:
    """Test BaseAssetFinder abstract base class."""

    def test_initialization(self) -> None:
        """Test that concrete finder initializes correctly."""
        finder = ConcreteAssetFinder()
        assert finder is not None
        assert hasattr(finder, "_asset_cache")
        assert finder._asset_cache == {}

    def test_find_assets_basic(self, tmp_path: Path) -> None:
        """Test finding assets in workspace."""
        workspace = tmp_path / "workspace"

        # Create asset directories and files
        textures = workspace / "textures"
        textures.mkdir(parents=True)
        (textures / "diffuse.jpg").touch()
        (textures / "normal.jpg").touch()

        cache = workspace / "cache"
        cache.mkdir(parents=True)
        (cache / "model.abc").touch()

        renders = workspace / "renders"
        renders.mkdir(parents=True)
        (renders / "beauty.exr").touch()

        finder = ConcreteAssetFinder()
        assets = finder.find_assets(str(workspace))

        assert len(assets) == 4
        extensions = {a.suffix for a in assets}
        assert extensions == {".jpg", ".abc", ".exr"}

    def test_find_assets_with_type_filter(self, tmp_path: Path) -> None:
        """Test finding assets with type filter."""
        workspace = tmp_path / "workspace"
        textures = workspace / "textures"
        textures.mkdir(parents=True)

        (textures / "diffuse.jpg").touch()
        (textures / "normal.jpg").touch()
        (textures / "height.exr").touch()

        finder = ConcreteAssetFinder()
        # Mock the _matches_asset_type to filter jpg only
        with patch.object(
            finder, "_matches_asset_type", side_effect=lambda p, _t: "jpg" in p.lower()
        ):
            assets = finder.find_assets(str(workspace), asset_type="jpg")

        assert len(assets) == 2
        assert all(a.suffix == ".jpg" for a in assets)

    def test_find_assets_with_cache(self, tmp_path: Path) -> None:
        """Test that caching works correctly."""
        workspace = tmp_path / "workspace"
        textures = workspace / "textures"
        textures.mkdir(parents=True)
        (textures / "test.jpg").touch()

        finder = ConcreteAssetFinder()

        # First call
        assets1 = finder.find_assets(str(workspace))
        assert len(assets1) == 1

        # Add another file
        (textures / "test2.jpg").touch()

        # Second call with cache should return cached result
        assets2 = finder.find_assets(str(workspace), use_cache=True)
        assert len(assets2) == 1  # Still cached

        # Third call without cache should find new file
        assets3 = finder.find_assets(str(workspace), use_cache=False)
        assert len(assets3) == 2  # Updated

    def test_find_assets_nonexistent_workspace(self) -> None:
        """Test behavior with nonexistent workspace."""
        finder = ConcreteAssetFinder()
        assets = finder.find_assets("/nonexistent/path")
        assert assets == []

    def test_find_latest_asset(self, tmp_path: Path) -> None:
        """Test finding latest version of asset."""
        workspace = tmp_path / "workspace"
        textures = workspace / "textures"
        textures.mkdir(parents=True)

        # Create versioned assets
        (textures / "diffuse_v001.jpg").touch()
        (textures / "diffuse_v002.jpg").touch()
        (textures / "diffuse_v003.jpg").touch()

        finder = ConcreteAssetFinder()
        version_pattern = re.compile(r"_v(\d{3})")

        latest = finder.find_latest_asset(str(workspace), "diffuse", version_pattern)

        assert latest is not None
        assert latest.name == "diffuse_v003.jpg"

    def test_find_latest_asset_no_version_pattern(self, tmp_path: Path) -> None:
        """Test finding latest asset by modification time."""
        import time

        workspace = tmp_path / "workspace"
        textures = workspace / "textures"
        textures.mkdir(parents=True)

        # Create files with different modification times
        file1 = textures / "diffuse_old.jpg"
        file1.touch()
        time.sleep(0.01)  # Ensure different mtime

        file2 = textures / "diffuse_new.jpg"
        file2.touch()

        finder = ConcreteAssetFinder()
        latest = finder.find_latest_asset(str(workspace), "diffuse")

        assert latest is not None
        assert latest.name == "diffuse_new.jpg"

    def test_find_latest_asset_not_found(self, tmp_path: Path) -> None:
        """Test finding asset that doesn't exist."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        finder = ConcreteAssetFinder()
        latest = finder.find_latest_asset(str(workspace), "nonexistent")
        assert latest is None

    def test_group_assets_by_type(self, tmp_path: Path) -> None:
        """Test grouping assets by file extension."""
        assets = [
            tmp_path / "diffuse.jpg",
            tmp_path / "normal.jpg",
            tmp_path / "beauty.exr",
            tmp_path / "model.abc",
            tmp_path / "depth.exr",
        ]
        for a in assets:
            a.touch()

        finder = ConcreteAssetFinder()
        grouped = finder.group_assets_by_type(assets)

        assert len(grouped) == 3
        assert len(grouped[".jpg"]) == 2
        assert len(grouped[".exr"]) == 2
        assert len(grouped[".abc"]) == 1

    def test_group_assets_by_sequence(self, tmp_path: Path) -> None:
        """Test grouping assets by image sequence."""
        assets = [
            tmp_path / "beauty.0001.exr",
            tmp_path / "beauty.0002.exr",
            tmp_path / "beauty.0003.exr",
            tmp_path / "depth.0001.exr",
            tmp_path / "depth.0002.exr",
            tmp_path / "single_file.jpg",
        ]
        for a in assets:
            a.touch()

        finder = ConcreteAssetFinder()
        sequences = finder.group_assets_by_sequence(assets)

        assert len(sequences) == 3
        assert len(sequences["beauty"]) == 3
        assert len(sequences["depth"]) == 2
        assert len(sequences["single_files"]) == 1

    def test_find_missing_frames(self, tmp_path: Path) -> None:
        """Test finding missing frames in sequence."""
        sequence_files = [
            tmp_path / "beauty.0001.exr",
            tmp_path / "beauty.0002.exr",
            tmp_path / "beauty.0004.exr",
            tmp_path / "beauty.0006.exr",
        ]
        for f in sequence_files:
            f.touch()

        finder = ConcreteAssetFinder()
        missing = finder.find_missing_frames(sequence_files, (1, 6))

        assert missing == [3, 5]

    def test_find_missing_frames_auto_range(self, tmp_path: Path) -> None:
        """Test finding missing frames with automatic range."""
        sequence_files = [
            tmp_path / "beauty.0010.exr",
            tmp_path / "beauty.0011.exr",
            tmp_path / "beauty.0013.exr",
        ]
        for f in sequence_files:
            f.touch()

        finder = ConcreteAssetFinder()
        missing = finder.find_missing_frames(sequence_files)

        assert missing == [12]

    def test_calculate_asset_size(self, tmp_path: Path) -> None:
        """Test calculating total asset size."""
        assets = []
        for i in range(3):
            asset = tmp_path / f"asset_{i}.exr"
            asset.write_bytes(b"x" * (1024 * (i + 1)))  # 1KB, 2KB, 3KB
            assets.append(asset)

        finder = ConcreteAssetFinder()
        total_size = finder.calculate_asset_size(assets)

        assert total_size == 6144  # 6KB total

    def test_format_size(self) -> None:
        """Test size formatting."""
        finder = ConcreteAssetFinder()

        assert finder.format_size(512) == "512.0 B"
        assert finder.format_size(1024) == "1.0 KB"
        assert finder.format_size(1536) == "1.5 KB"
        assert finder.format_size(1048576) == "1.0 MB"
        assert finder.format_size(1073741824) == "1.0 GB"
        assert finder.format_size(1099511627776) == "1.0 TB"

    def test_progress_reporting(self, tmp_path: Path) -> None:
        """Test progress reporting during asset search."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        finder = ConcreteAssetFinder()

        # Set up progress callback
        progress_calls = []

        def progress_callback(current: int, total: int, message: str) -> None:
            progress_calls.append((current, total, message))

        finder.set_progress_callback(progress_callback)

        # Run search
        finder.find_assets(str(workspace))

        # Should have progress calls
        assert len(progress_calls) > 0
        # Final call should indicate completion
        last_call = progress_calls[-1]
        assert last_call[0] == last_call[1]  # current == total
        assert "complete" in last_call[2].lower()

    def test_stop_requested(self, tmp_path: Path) -> None:
        """Test that search stops when requested."""
        workspace = tmp_path / "workspace"
        for i in range(5):
            asset_dir = workspace / f"dir_{i}"
            asset_dir.mkdir(parents=True)
            (asset_dir / "asset.jpg").touch()

        finder = ConcreteAssetFinder()

        # Request stop immediately
        finder.request_stop()

        assets = finder.find_assets(str(workspace))

        # Should have stopped early
        assert len(assets) < 5

    def test_clear_cache_specific(self, tmp_path: Path) -> None:
        """Test clearing cache for specific workspace."""
        workspace1 = tmp_path / "workspace1"
        workspace1.mkdir()
        workspace2 = tmp_path / "workspace2"
        workspace2.mkdir()

        finder = ConcreteAssetFinder()

        # Populate cache
        finder._asset_cache[f"{workspace1}:all"] = []
        finder._asset_cache[f"{workspace2}:all"] = []

        # Clear specific workspace
        finder.clear_cache(str(workspace1))

        assert f"{workspace1}:all" not in finder._asset_cache
        assert f"{workspace2}:all" in finder._asset_cache

    def test_clear_cache_all(self) -> None:
        """Test clearing all cache."""
        finder = ConcreteAssetFinder()

        # Populate cache
        finder._asset_cache["workspace1:all"] = []
        finder._asset_cache["workspace2:all"] = []

        # Clear all
        finder.clear_cache()

        assert len(finder._asset_cache) == 0

    def test_matches_asset_type(self) -> None:
        """Test asset type matching."""
        finder = ConcreteAssetFinder()

        assert finder._matches_asset_type("*.exr", "exr")
        assert finder._matches_asset_type("*.jpg", "jpg")
        assert not finder._matches_asset_type("*.exr", "jpg")

    def test_recursive_search(self, tmp_path: Path) -> None:
        """Test that assets are found recursively."""
        workspace = tmp_path / "workspace"
        textures = workspace / "textures"
        subdirs = textures / "level1" / "level2" / "level3"
        subdirs.mkdir(parents=True)

        # Create files at various depths
        (textures / "root.jpg").touch()
        (textures / "level1" / "mid.jpg").touch()
        (subdirs / "deep.jpg").touch()

        finder = ConcreteAssetFinder()
        assets = finder.find_assets(str(workspace))

        assert len(assets) == 3
        names = {a.name for a in assets}
        assert names == {"root.jpg", "mid.jpg", "deep.jpg"}
