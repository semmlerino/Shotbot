"""Base class for asset finders with common functionality."""

from __future__ import annotations

# Standard library imports
import re
from abc import ABC, abstractmethod
from pathlib import Path
from re import Pattern

# Local application imports
from progress_mixin import ProgressReportingMixin


class BaseAssetFinder(ProgressReportingMixin, ABC):
    """Abstract base class for asset file finders.

    Provides common functionality for finding asset files (textures, caches, etc.)
    in a VFX workspace structure. Focuses on non-versioned or differently-versioned
    assets compared to scene files.
    """

    def __init__(self) -> None:
        """Initialize the asset finder with progress reporting."""
        super().__init__()
        self._asset_cache: dict[str, list[Path]] = {}

    @abstractmethod
    def get_asset_directories(self, workspace: Path) -> list[Path]:
        """Get directories where assets are stored.

        Args:
            workspace: Workspace path

        Returns:
            List of directories to search for assets

        """
        raise NotImplementedError

    @abstractmethod
    def get_asset_patterns(self) -> list[str]:
        """Get file patterns for assets.

        Returns:
            List of glob patterns (e.g., ['*.exr', '*.jpg'])

        """
        raise NotImplementedError

    def find_assets(
        self,
        workspace_path: str,
        asset_type: str | None = None,
        use_cache: bool = True,
    ) -> list[Path]:
        """Find all assets in a workspace.

        Args:
            workspace_path: Full path to the shot workspace
            asset_type: Optional specific asset type to filter
            use_cache: Whether to use cached results

        Returns:
            List of paths to asset files

        """
        # Check cache
        cache_key = f"{workspace_path}:{asset_type or 'all'}"
        if use_cache and cache_key in self._asset_cache:
            self.logger.debug(f"Using cached results for {cache_key}")
            return self._asset_cache[cache_key]

        # Validate workspace
        workspace = self._validate_workspace(workspace_path)
        if workspace is None:
            return []

        # Get asset directories
        asset_dirs = self.get_asset_directories(workspace)
        assets: list[Path] = []

        # Track progress
        total_dirs = len(asset_dirs)
        for idx, asset_dir in enumerate(asset_dirs):
            if self._check_stop():
                self.logger.info("Asset search stopped by user request")
                break

            self._report_progress(idx, total_dirs, f"Searching {asset_dir.name}")

            if not asset_dir.exists():
                continue

            # Search for assets
            for pattern in self.get_asset_patterns():
                if asset_type and not self._matches_asset_type(pattern, asset_type):
                    continue

                # Search recursively
                assets.extend(asset_dir.rglob(pattern))

        # Cache results
        if use_cache:
            self._asset_cache[cache_key] = assets

        self._report_progress(total_dirs, total_dirs, "Asset search complete")
        self.logger.info(f"Found {len(assets)} assets in {workspace_path}")

        return assets

    def find_latest_asset(
        self,
        workspace_path: str,
        asset_name: str,
        version_pattern: Pattern[str] | None = None,
    ) -> Path | None:
        """Find the latest version of a specific asset.

        Args:
            workspace_path: Full path to the shot workspace
            asset_name: Name or pattern of the asset to find
            version_pattern: Optional pattern to extract version

        Returns:
            Path to the latest asset, or None if not found

        """
        # Find all matching assets
        all_assets = self.find_assets(workspace_path)

        # Filter by name
        matching_assets = [
            a for a in all_assets if asset_name.lower() in a.name.lower()
        ]

        if not matching_assets:
            self.logger.debug(f"No assets matching '{asset_name}' found")
            return None

        # If no version pattern, return most recently modified
        if version_pattern is None:
            try:
                return max(matching_assets, key=lambda p: p.stat().st_mtime)
            except (OSError, ValueError) as e:
                self.logger.warning(f"Error finding latest asset by mtime: {e}")
                # Fallback to alphabetical sorting
                return max(matching_assets, key=lambda p: p.name)

        # Extract versions and sort
        versioned_assets: list[tuple[Path, int]] = []
        for asset in matching_assets:
            match = version_pattern.search(asset.name)
            if match:
                try:
                    version = int(match.group(1))
                    versioned_assets.append((asset, version))
                except (IndexError, ValueError):
                    continue

        if not versioned_assets:
            # No versioned files, return most recent
            return max(matching_assets, key=lambda p: p.stat().st_mtime)

        # Sort by version and return latest
        versioned_assets.sort(key=lambda x: x[1])
        return versioned_assets[-1][0]

    def group_assets_by_type(self, assets: list[Path]) -> dict[str, list[Path]]:
        """Group assets by their type/extension.

        Args:
            assets: List of asset paths

        Returns:
            Dictionary mapping file extension to list of assets

        """
        grouped: dict[str, list[Path]] = {}

        for asset in assets:
            ext = asset.suffix.lower()
            if ext not in grouped:
                grouped[ext] = []
            grouped[ext].append(asset)

        return grouped

    def group_assets_by_sequence(
        self,
        assets: list[Path],
        sequence_pattern: Pattern[str] | None = None,
    ) -> dict[str, list[Path]]:
        """Group assets by sequence (for image sequences).

        Args:
            assets: List of asset paths
            sequence_pattern: Pattern to extract sequence name

        Returns:
            Dictionary mapping sequence name to list of frames

        """
        if sequence_pattern is None:
            # Default pattern for image sequences (name.####.ext)
            sequence_pattern = re.compile(r"^(.+?)\.(\d{4,})\.")

        sequences: dict[str, list[Path]] = {}

        for asset in assets:
            match = sequence_pattern.search(asset.name)
            if match:
                seq_name = match.group(1)
                if seq_name not in sequences:
                    sequences[seq_name] = []
                sequences[seq_name].append(asset)
            else:
                # Non-sequence file
                if "single_files" not in sequences:
                    sequences["single_files"] = []
                sequences["single_files"].append(asset)

        # Sort frames within each sequence
        for frames in sequences.values():
            frames.sort()

        return sequences

    def find_missing_frames(
        self,
        sequence_files: list[Path],
        expected_range: tuple[int, int] | None = None,
    ) -> list[int]:
        """Find missing frames in an image sequence.

        Args:
            sequence_files: List of sequence file paths
            expected_range: Optional (start, end) frame range

        Returns:
            List of missing frame numbers

        """
        # Extract frame numbers
        frame_pattern = re.compile(r"\.(\d{4,})\.")
        frame_numbers: set[int] = set()

        for file_path in sequence_files:
            match = frame_pattern.search(file_path.name)
            if match:
                frame_numbers.add(int(match.group(1)))

        if not frame_numbers:
            return []

        # Determine range
        if expected_range:
            start, end = expected_range
        else:
            start = min(frame_numbers)
            end = max(frame_numbers)

        # Find missing frames
        expected = set(range(start, end + 1))
        missing = sorted(expected - frame_numbers)

        if missing:
            self.logger.warning(
                f"Found {len(missing)} missing frames in sequence",
            )

        return missing

    def calculate_asset_size(self, assets: list[Path]) -> int:
        """Calculate total size of assets in bytes.

        Args:
            assets: List of asset paths

        Returns:
            Total size in bytes

        """
        total_size = 0
        for asset in assets:
            try:
                total_size += asset.stat().st_size
            except (OSError, FileNotFoundError):
                continue

        return total_size

    def format_size(self, size_bytes: int) -> str:
        """Format size in human-readable format.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string (e.g., "1.5 GB")

        """
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"

    def _validate_workspace(self, workspace_path: str | None) -> Path | None:
        """Validate that workspace exists and is accessible.

        Args:
            workspace_path: Path to validate

        Returns:
            Path object if valid, None otherwise

        """
        if not workspace_path:
            self.logger.debug("No workspace path provided")
            return None

        workspace = Path(workspace_path)
        if not workspace.exists():
            self.logger.debug(f"Workspace does not exist: {workspace_path}")
            return None

        return workspace

    def _matches_asset_type(self, pattern: str, asset_type: str) -> bool:
        """Check if a pattern matches the requested asset type.

        Args:
            pattern: File pattern (e.g., '*.exr')
            asset_type: Requested asset type

        Returns:
            True if pattern matches asset type

        """
        # Simple matching - can be overridden for complex logic
        return asset_type.lower() in pattern.lower()

    def clear_cache(self, workspace_path: str | None = None) -> None:
        """Clear cached asset results.

        Args:
            workspace_path: Optional specific workspace to clear

        """
        if workspace_path:
            # Clear specific workspace
            keys_to_remove = [
                k for k in self._asset_cache if k.startswith(f"{workspace_path}:")
            ]
            for key in keys_to_remove:
                del self._asset_cache[key]
        else:
            # Clear all
            self._asset_cache.clear()

        self.logger.debug("Asset cache cleared")
