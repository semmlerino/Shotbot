"""Utility for finding 3DE scene files from other users."""

import itertools
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Generator, List, Optional, Set, Tuple

from config import Config
from performance_monitor import timed_operation
from threede_scene_model import ThreeDEScene
from utils import PathUtils, ValidationUtils

# Set up logger for this module
logger = logging.getLogger(__name__)


class PathDiagnostics:
    """Helper class for detailed path diagnostics during 3DE scene finding."""

    @staticmethod
    def log_path_attempt(path: Path, description: str, exists: Optional[bool] = None):
        """Log a path access attempt with detailed information.

        Args:
            path: Path being accessed
            description: Description of what this path represents
            exists: Whether path exists (checked if None)
        """
        if exists is None:
            exists = path.exists()

        status = "EXISTS" if exists else "MISSING"
        logger.debug(f"PATH CHECK [{status}] {description}: {path}")

        if not exists:
            # Check parent directory
            parent = path.parent
            if parent.exists():
                logger.debug(f"  Parent directory exists: {parent}")
                try:
                    siblings = list(parent.iterdir())[:10]  # Limit to first 10
                    sibling_names = [s.name for s in siblings]
                    logger.debug(f"  Parent contains: {sibling_names}")
                except PermissionError:
                    logger.debug("  Permission denied listing parent directory")
            else:
                logger.debug(f"  Parent directory also missing: {parent}")

    @staticmethod
    def check_alternative_paths(workspace_path: str, username: str) -> List[Path]:
        """Check alternative path patterns for 3DE scenes.

        Args:
            workspace_path: Shot workspace path
            username: Username to check for

        Returns:
            List of alternative paths that exist
        """
        base_path = Path(workspace_path) / "user" / username
        alternatives = []

        # Alternative path patterns to check
        path_patterns = [
            # Current expected pattern
            Config.THREEDE_SCENE_SEGMENTS,
            # Alternative patterns from config
            *Config.THREEDE_ALTERNATIVE_PATTERNS,
            # Check environment variable patterns
            *PathDiagnostics._get_env_path_patterns(),
        ]

        logger.debug(
            f"Checking {len(path_patterns)} alternative path patterns for user {username}"
        )

        for pattern in path_patterns:
            try:
                alt_path = PathUtils.build_path(str(base_path), *pattern)
                PathDiagnostics.log_path_attempt(
                    alt_path, f"Alternative pattern {' -> '.join(pattern)}"
                )

                if alt_path.exists():
                    alternatives.append(alt_path)
                    logger.info(
                        f"Found alternative 3DE path for {username}: {alt_path}"
                    )

            except Exception as e:
                logger.debug(f"Error checking alternative pattern {pattern}: {e}")

        return alternatives

    @staticmethod
    def _get_env_path_patterns() -> List[List[str]]:
        """Get path patterns from environment variables.

        Returns:
            List of path segment lists based on environment variables
        """
        patterns = []

        # Check for 3DE-specific environment variables from config
        env_patterns = {}
        for env_var in Config.THREEDE_ENV_VARS:
            value = os.environ.get(env_var)
            if value:
                env_patterns[env_var] = value

        for env_var, value in env_patterns.items():
            if value:
                # Split path and use as segments
                segments = [seg for seg in value.split("/") if seg]
                if segments:
                    patterns.append(segments)
                    logger.debug(f"Added path pattern from {env_var}: {segments}")

        return patterns


class ThreeDESceneFinder:
    """Static utility class for discovering 3DE scene files."""

    # Pre-compiled regex patterns for performance
    # Compile patterns once at class level to avoid repeated compilation in loops
    _BG_FG_PATTERN = re.compile(r"^[bf]g\d{2}$", re.IGNORECASE)
    _PLATE_PATTERNS = [
        re.compile(r"^[bf]g\d{2}$", re.IGNORECASE),  # bg01, fg01, etc.
        re.compile(r"^plate_?\d+$", re.IGNORECASE),  # plate01, plate_01
        re.compile(r"^comp_?\d+$", re.IGNORECASE),  # comp01, comp_01
        re.compile(r"^shot_?\d+$", re.IGNORECASE),  # shot01, shot_01
        re.compile(r"^sc\d+$", re.IGNORECASE),  # sc01, sc02
        re.compile(r"^[\w]+_v\d{3}$", re.IGNORECASE),  # anything_v001
    ]

    # Convert generic directory names to uppercase set for O(1) lookup
    _GENERIC_DIRS = {
        "3de",
        "scenes",
        "scene",
        "mm",
        "matchmove",
        "tracking",
        "work",
        "wip",
        "exports",
        "user",
        "files",
        "data",
    }

    @staticmethod
    def quick_3de_exists_check(base_paths: List[str], timeout_seconds: int = 5) -> bool:
        """Quick check if ANY .3de files exist in the given paths.

        Uses 'find' command with -quit to exit as soon as first file is found.
        This is much faster than full directory traversal.

        Args:
            base_paths: List of base paths to check
            timeout_seconds: Maximum time to search before giving up

        Returns:
            True if at least one .3de file exists, False otherwise
        """
        import subprocess

        for base_path in base_paths:
            if not os.path.exists(base_path):
                continue

            try:
                # Use find with -quit to exit on first match (very fast)
                # -name "*.3de" -o -name "*.3DE" to catch both cases
                result = subprocess.run(
                    [
                        "find",
                        base_path,
                        "-type",
                        "f",
                        "(",
                        "-name",
                        "*.3de",
                        "-o",
                        "-name",
                        "*.3DE",
                        ")",
                        "-print",
                        "-quit",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )

                # If find returns any output, a .3de file exists
                if result.stdout.strip():
                    logger.debug(
                        f"Quick check found .3de file: {result.stdout.strip()}"
                    )
                    return True

            except subprocess.TimeoutExpired:
                logger.warning(
                    f"Quick .3de check timed out after {timeout_seconds}s for {base_path}"
                )
                # Assume files might exist if timeout (better to scan than miss files)
                return True
            except FileNotFoundError:
                # 'find' command not available (Windows?), assume files might exist
                logger.debug(
                    "'find' command not available, assuming .3de files might exist"
                )
                return True
            except Exception as e:
                logger.warning(f"Quick .3de check failed: {e}")
                # On error, assume files might exist
                return True

        logger.debug("Quick check found no .3de files in any path")
        return False

    @staticmethod
    @timed_operation("extract_plate_from_path", log_threshold_ms=5)
    def extract_plate_from_path(file_path: Path, user_path: Path) -> str:
        """Extract meaningful plate/grouping identifier from an arbitrary path.

        Args:
            file_path: Full path to the .3de file
            user_path: Base user directory path

        Returns:
            Extracted plate/grouping name
        """
        try:
            # Get relative path from user directory
            relative_path = file_path.relative_to(user_path)
            path_parts = relative_path.parts

            # First pass: Look for BG/FG plate patterns (highest priority)
            for i, part in enumerate(path_parts[:-1]):  # Exclude the filename
                if ThreeDESceneFinder._BG_FG_PATTERN.match(part):
                    logger.debug(f"Found BG/FG plate pattern match: {part}")
                    return part

            # Second pass: Look for other plate patterns using pre-compiled patterns
            for i, part in enumerate(path_parts[:-1]):  # Exclude the filename
                # Check if this part matches common plate patterns
                for pattern in ThreeDESceneFinder._PLATE_PATTERNS:
                    if pattern.match(part):
                        logger.debug(f"Found plate pattern match: {part}")
                        return part

            # Third pass: Look for directories after VFX markers (fallback)
            for i, part in enumerate(path_parts[:-1]):  # Exclude the filename
                part_lower = part.lower()

                # Check for common VFX directory names that indicate grouping
                if part_lower in [
                    "3de",
                    "scenes",
                    "scene",
                    "matchmove",
                    "mm",
                    "tracking",
                ]:
                    # Use the next directory if available
                    if i + 1 < len(path_parts) - 1:
                        next_part = path_parts[i + 1]
                        if next_part not in ["3de", "scenes", "scene", "exports"]:
                            logger.debug(f"Using directory after {part}: {next_part}")
                            return next_part

            # If no pattern matched, use intelligent fallback
            # Prefer directories that aren't generic tool/process names
            # Use pre-computed set for O(1) lookup instead of O(n) list membership
            for part in reversed(path_parts[:-1]):
                if part.lower() not in ThreeDESceneFinder._GENERIC_DIRS:
                    logger.debug(f"Using non-generic directory as plate: {part}")
                    return part

            # Last resort: use parent directory
            parent_name = file_path.parent.name
            logger.debug(f"Using parent directory as plate: {parent_name}")
            return parent_name

        except ValueError:
            # Can't make relative path, use parent directory
            logger.debug(
                f"Cannot make relative path, using parent: {file_path.parent.name}"
            )
            return file_path.parent.name

    @staticmethod
    @timed_operation("find_scenes_for_shot", log_threshold_ms=100)
    def find_scenes_for_shot(
        shot_workspace_path: str,
        show: str,
        sequence: str,
        shot: str,
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Find all 3DE scenes for a shot from other users.

        This method now performs a flexible recursive search for all .3de files
        in user directories, regardless of specific path structure.

        Args:
            shot_workspace_path: The workspace path for the shot
            show: Show name
            sequence: Sequence name
            shot: Shot number
            excluded_users: Set of usernames to exclude (uses current user if None)

        Returns:
            List of ThreeDEScene objects
        """
        # Validate input parameters
        if not ValidationUtils.validate_shot_components(show, sequence, shot):
            logger.warning("Invalid shot components provided")
            return []

        if not shot_workspace_path:
            logger.warning("Empty shot workspace path provided")
            return []

        # Get excluded users if not provided
        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        scenes: List[ThreeDEScene] = []
        user_dir = PathUtils.build_path(shot_workspace_path, "user")

        # Check if user directory exists
        if not PathUtils.validate_path_exists(user_dir, "User directory"):
            logger.warning(f"User directory does not exist: {user_dir}")
            return scenes

        logger.info(f"Performing flexible 3DE scene search in {user_dir}")
        logger.debug(f"Excluding users: {excluded_users}")

        try:
            # Iterate through user directories
            scene_count = 0
            user_count = 0
            total_scanned = 0

            for user_path in user_dir.iterdir():
                if not user_path.is_dir():
                    continue

                user_name = user_path.name
                total_scanned += 1

                # Skip excluded users
                if user_name in excluded_users:
                    logger.debug(f"Skipping excluded user: {user_name}")
                    continue

                user_count += 1
                logger.debug(f"Scanning user directory: {user_name}")

                # Recursively find ALL .3de files in the user's directory
                try:
                    # Search for both lowercase and uppercase extensions
                    threede_files = list(user_path.rglob("*.3de"))
                    threede_files.extend(list(user_path.rglob("*.3DE")))

                    if threede_files:
                        logger.info(
                            f"Found {len(threede_files)} .3de files for user {user_name}"
                        )

                        for threede_file in threede_files:
                            # Skip if file doesn't exist or isn't readable
                            if not ThreeDESceneFinder.verify_scene_exists(threede_file):
                                logger.debug(
                                    f"Skipping inaccessible file: {threede_file}"
                                )
                                continue

                            # Extract meaningful plate/grouping from path
                            plate = ThreeDESceneFinder.extract_plate_from_path(
                                threede_file, user_path
                            )

                            # Create ThreeDEScene object
                            scene = ThreeDEScene(
                                show=show,
                                sequence=sequence,
                                shot=shot,
                                workspace_path=shot_workspace_path,
                                user=user_name,
                                plate=plate,
                                scene_path=threede_file,
                            )
                            scenes.append(scene)
                            scene_count += 1

                            logger.debug(
                                f"Added 3DE scene: {user_name}/{plate} -> {threede_file.name}"
                            )
                    else:
                        logger.debug(f"No .3de files found for user {user_name}")

                except PermissionError:
                    logger.warning(f"Permission denied accessing {user_name} directory")
                except Exception as e:
                    logger.error(f"Error scanning user {user_name}: {e}")

            logger.info(
                f"Flexible search complete: Found {scene_count} 3DE scenes from {user_count} users (scanned {total_scanned} directories)"
            )

        except PermissionError as e:
            logger.error(f"Permission denied accessing user directories: {e}")
        except Exception as e:
            logger.error(f"Error scanning for 3DE scenes: {e}")

        return scenes

    @staticmethod
    @timed_operation("discover_all_shots_in_show", log_threshold_ms=500)
    def discover_all_shots_in_show(
        show_root: str, show: str
    ) -> List[Tuple[str, str, str, str]]:
        """Discover all shots in a show by scanning the filesystem.

        Args:
            show_root: Root directory for shows (e.g., /shows)
            show: Show name

        Returns:
            List of (workspace_path, show, sequence, shot) tuples
        """
        shots = []
        show_path = Path(show_root) / show / "shots"

        if not show_path.exists():
            logger.warning(f"Show shots directory does not exist: {show_path}")
            return shots

        logger.info(f"Discovering all shots in show: {show}")

        try:
            # Pattern: /shows/{show}/shots/{sequence}/{shot}/
            sequence_count = 0
            shot_count = 0

            # Iterate through sequence directories
            for sequence_dir in show_path.iterdir():
                if not sequence_dir.is_dir():
                    continue

                sequence = sequence_dir.name
                # Skip common non-sequence directories
                skip_patterns = (
                    Config.SKIP_SEQUENCE_PATTERNS
                    if hasattr(Config, "SKIP_SEQUENCE_PATTERNS")
                    else ["tmp", "temp", "test"]
                )
                if sequence in skip_patterns or sequence.startswith("."):
                    logger.debug(f"Skipping sequence directory: {sequence}")
                    continue

                sequence_count += 1

                # Iterate through shot directories
                for shot_dir in sequence_dir.iterdir():
                    if not shot_dir.is_dir():
                        continue

                    shot = shot_dir.name
                    # Skip common non-shot directories
                    skip_patterns = (
                        Config.SKIP_SHOT_PATTERNS
                        if hasattr(Config, "SKIP_SHOT_PATTERNS")
                        else ["tmp", "temp", "test"]
                    )
                    if shot in skip_patterns or shot.startswith("."):
                        logger.debug(f"Skipping shot directory: {shot}")
                        continue

                    # Verify this looks like a valid shot workspace
                    # Should have at least a user directory
                    user_dir = shot_dir / "user"
                    if user_dir.exists():
                        workspace_path = str(shot_dir)
                        shots.append((workspace_path, show, sequence, shot))
                        shot_count += 1
                        logger.debug(f"Found shot: {show}/{sequence}/{shot}")

                        # Safety limit to prevent excessive searching
                        max_shots = (
                            Config.MAX_SHOTS_PER_SHOW
                            if hasattr(Config, "MAX_SHOTS_PER_SHOW")
                            else 1000
                        )
                        if shot_count >= max_shots:
                            logger.warning(
                                f"Reached maximum shot limit ({max_shots}) for {show}. Stopping discovery."
                            )
                            return shots
                    else:
                        logger.debug(f"Skipping {shot_dir} - no user directory")

            logger.info(
                f"Discovered {shot_count} shots across {sequence_count} sequences in {show}"
            )

        except PermissionError as e:
            logger.error(f"Permission denied accessing show directory: {e}")
        except Exception as e:
            logger.error(f"Error discovering shots in show: {e}")

        return shots

    @staticmethod
    @timed_operation("find_all_scenes_in_shows", log_threshold_ms=1000)
    def find_all_scenes_in_shows(
        user_shots: List[Any],  # List of Shot objects
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Find 3DE scenes across ALL shots in shows the user is working on.

        This performs a show-wide search, not limited to the user's assigned shots.

        Args:
            user_shots: User's assigned shots (used to determine which shows to search)
            excluded_users: Set of usernames to exclude

        Returns:
            List of all ThreeDEScene objects found across all shots in relevant shows
        """
        if not user_shots:
            logger.info("No user shots provided for show-wide search")
            return []

        # Check if show-wide search is enabled
        if hasattr(Config, "SHOW_SEARCH_ENABLED") and not Config.SHOW_SEARCH_ENABLED:
            logger.info(
                "Show-wide search is disabled. Falling back to user's shots only."
            )
            # Fall back to searching only user's assigned shots
            all_scenes = []
            for shot in user_shots:
                scenes = ThreeDESceneFinder.find_scenes_for_shot(
                    shot.workspace_path,
                    shot.show,
                    shot.sequence,
                    shot.shot,
                    excluded_users,
                )
                all_scenes.extend(scenes)
            return all_scenes

        # Extract unique shows from user's shots
        shows_to_search = set()
        show_roots = set()

        for shot in user_shots:
            shows_to_search.add(shot.show)
            # Extract show root from workspace path
            # e.g., /shows/jack_ryan/shots/GF_256/GF_256_0620 -> /shows
            workspace_parts = Path(shot.workspace_path).parts
            if "shows" in workspace_parts:
                shows_idx = workspace_parts.index("shows")
                show_root = "/".join(workspace_parts[: shows_idx + 1])
                show_roots.add(show_root)

        if not show_roots:
            # Use configured show roots or fallback
            configured_roots = (
                Config.SHOW_ROOT_PATHS
                if hasattr(Config, "SHOW_ROOT_PATHS")
                else ["/shows"]
            )
            show_roots = set(configured_roots)

        logger.info(f"Performing show-wide 3DE search across shows: {shows_to_search}")

        all_scenes = []

        # Discover and search all shots in each show
        for show_root in show_roots:
            for show in shows_to_search:
                # Discover all shots in this show
                all_shots = ThreeDESceneFinder.discover_all_shots_in_show(
                    show_root, show
                )

                if not all_shots:
                    logger.warning(f"No shots discovered in {show}")
                    continue

                logger.info(
                    f"Searching {len(all_shots)} shots in {show} for 3DE scenes"
                )

                # Search each discovered shot
                for workspace_path, show_name, sequence, shot in all_shots:
                    scenes = ThreeDESceneFinder.find_scenes_for_shot(
                        workspace_path, show_name, sequence, shot, excluded_users
                    )
                    all_scenes.extend(scenes)

        logger.info(
            f"Show-wide search complete: Found {len(all_scenes)} total 3DE scenes"
        )
        return all_scenes

    @staticmethod
    def find_all_scenes(
        shots: List[Tuple[str, str, str, str]],
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Find 3DE scenes for multiple shots.

        Args:
            shots: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude (uses current user if None)

        Returns:
            Combined list of ThreeDEScene objects
        """
        if not shots:
            logger.debug("No shots provided for scene search")
            return []

        all_scenes: List[ThreeDEScene] = []
        logger.info(f"Searching for 3DE scenes across {len(shots)} shots")

        for workspace_path, show, sequence, shot in shots:
            scenes = ThreeDESceneFinder.find_scenes_for_shot(
                workspace_path, show, sequence, shot, excluded_users
            )
            all_scenes.extend(scenes)

        logger.info(f"Found total of {len(all_scenes)} 3DE scenes across all shots")
        return all_scenes

    @staticmethod
    def find_scenes_progressive(
        user_path: Path,
        show: str,
        sequence: str,
        shot: str,
        user_name: str,
        batch_size: Optional[int] = None,
        excluded_users: Optional[Set[str]] = None,
    ) -> Generator[List[ThreeDEScene], None, None]:
        """Yield 3DE scenes in batches for responsive UI updates.

        This generator-based approach processes .3de files incrementally,
        yielding batches of discovered scenes to prevent UI blocking during
        large scans.

        Args:
            user_path: User's directory path to scan
            show: Show name for scene creation
            sequence: Sequence name for scene creation
            shot: Shot name for scene creation
            user_name: User name for scene creation
            batch_size: Number of scenes per batch (uses config default if None)
            excluded_users: Set of users to exclude (not used in single-user scan)

        Yields:
            Lists of ThreeDEScene objects in batches
        """
        if batch_size is None:
            batch_size = Config.PROGRESSIVE_SCAN_BATCH_SIZE

        # Validate batch size
        batch_size = max(
            Config.PROGRESSIVE_SCAN_MIN_BATCH_SIZE,
            min(batch_size, Config.PROGRESSIVE_SCAN_MAX_BATCH_SIZE),
        )

        logger.debug(
            f"Starting progressive scan of {user_path} with batch size {batch_size}"
        )

        batch = []
        processed_count = 0

        try:
            # Use rglob for recursive search - handle both cases
            # Combine both lowercase and uppercase extensions
            threede_files = itertools.chain(
                user_path.rglob("*.3de"), user_path.rglob("*.3DE")
            )

            for threede_file in threede_files:
                # Verify file exists and is accessible
                if not ThreeDESceneFinder.verify_scene_exists(threede_file):
                    logger.debug(f"Skipping inaccessible file: {threede_file}")
                    continue

                # Extract meaningful plate/grouping from path
                plate = ThreeDESceneFinder.extract_plate_from_path(
                    threede_file, user_path
                )

                # Create scene object
                scene = ThreeDEScene(
                    show=show,
                    sequence=sequence,
                    shot=shot,
                    workspace_path=str(user_path.parent.parent),  # Back up to shot root
                    user=user_name,
                    plate=plate,
                    scene_path=threede_file,
                )

                batch.append(scene)
                processed_count += 1

                logger.debug(
                    f"Added to batch: {user_name}/{plate} -> {threede_file.name}"
                )

                # Yield batch when it reaches target size
                if len(batch) >= batch_size:
                    logger.debug(f"Yielding batch of {len(batch)} scenes")
                    yield batch
                    batch = []

                    # Yield to other threads periodically
                    if processed_count % Config.PROGRESSIVE_IO_YIELD_INTERVAL == 0:
                        time.sleep(0.001)  # Brief yield to prevent thread starvation

        except PermissionError as e:
            logger.warning(f"Permission denied accessing {user_path}: {e}")
        except Exception as e:
            logger.error(f"Error during progressive scan of {user_path}: {e}")

        # Yield remaining scenes if any
        if batch:
            logger.debug(f"Yielding final batch of {len(batch)} scenes")
            yield batch

        logger.debug(f"Progressive scan complete: processed {processed_count} files")

    @staticmethod
    def find_all_scenes_progressive(
        shots: List[Tuple[str, str, str, str]],
        excluded_users: Optional[Set[str]] = None,
        batch_size: Optional[int] = None,
    ) -> Generator[Tuple[List[ThreeDEScene], int, int, str], None, None]:
        """Progressive discovery of 3DE scenes across multiple shots.

        This method provides detailed progress information and yields results
        in batches for responsive UI updates during large-scale discovery operations.

        Args:
            shots: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude
            batch_size: Number of scenes per batch

        Yields:
            Tuples of (scene_batch, current_shot, total_shots, status_message)
        """
        if batch_size is None:
            batch_size = Config.PROGRESSIVE_SCAN_BATCH_SIZE

        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        total_shots = len(shots)
        current_shot_index = 0

        logger.info(f"Starting progressive scan of {total_shots} shots")

        for workspace_path, show, sequence, shot in shots:
            current_shot_index += 1

            # Create status message
            status_msg = f"Scanning shot {show}/{sequence}/{shot}"

            user_dir = PathUtils.build_path(workspace_path, "user")

            # Check if user directory exists
            if not PathUtils.validate_path_exists(user_dir, "User directory"):
                logger.debug(f"User directory missing for {show}/{sequence}/{shot}")
                # Yield empty batch with progress info
                yield ([], current_shot_index, total_shots, f"{status_msg} (no users)")
                continue

            logger.debug(f"Scanning users in {user_dir}")

            try:
                # Iterate through user directories
                for user_path in user_dir.iterdir():
                    if not user_path.is_dir():
                        continue

                    user_name = user_path.name

                    # Skip excluded users
                    if user_name in excluded_users:
                        logger.debug(f"Skipping excluded user: {user_name}")
                        continue

                    # Use progressive scanning for this user
                    user_status = f"{status_msg} - user {user_name}"

                    # Generator for this user's scenes
                    for scene_batch in ThreeDESceneFinder.find_scenes_progressive(
                        user_path,
                        show,
                        sequence,
                        shot,
                        user_name,
                        batch_size,
                        excluded_users,
                    ):
                        # Yield the batch with current progress
                        yield (
                            scene_batch,
                            current_shot_index,
                            total_shots,
                            user_status,
                        )

            except PermissionError:
                logger.warning(
                    f"Permission denied accessing user directories for {show}/{sequence}/{shot}"
                )
                yield (
                    [],
                    current_shot_index,
                    total_shots,
                    f"{status_msg} (access denied)",
                )
            except Exception as e:
                logger.error(f"Error scanning shot {show}/{sequence}/{shot}: {e}")
                yield ([], current_shot_index, total_shots, f"{status_msg} (error)")

        logger.info("Progressive scan complete")

    @staticmethod
    def _create_scene(
        threede_file: Path,
        user_path: Path,
        show: str,
        sequence: str,
        shot: str,
        user_name: str,
        workspace_path: str,
    ) -> ThreeDEScene:
        """Helper method to create a ThreeDEScene object.

        Args:
            threede_file: Path to the .3de file
            user_path: User's directory path
            show: Show name
            sequence: Sequence name
            shot: Shot name
            user_name: User name
            workspace_path: Shot workspace path

        Returns:
            Created ThreeDEScene object
        """
        # Extract meaningful plate/grouping from path
        plate = ThreeDESceneFinder.extract_plate_from_path(threede_file, user_path)

        return ThreeDEScene(
            show=show,
            sequence=sequence,
            shot=shot,
            workspace_path=workspace_path,
            user=user_name,
            plate=plate,
            scene_path=threede_file,
        )

    @staticmethod
    def estimate_scan_size(
        shots: List[Tuple[str, str, str, str]],
        excluded_users: Optional[Set[str]] = None,
    ) -> Tuple[int, int]:
        """Estimate the number of users and files to scan for progress calculation.

        This performs a quick directory listing without accessing files to provide
        accurate progress estimation for the progressive scan.

        Args:
            shots: List of (workspace_path, show, sequence, shot) tuples
            excluded_users: Set of usernames to exclude

        Returns:
            Tuple of (estimated_users, estimated_files)
        """
        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        total_users = 0
        total_files_estimate = 0

        for workspace_path, show, sequence, shot in shots:
            user_dir = PathUtils.build_path(workspace_path, "user")

            if not PathUtils.validate_path_exists(user_dir, "User directory"):
                continue

            try:
                # Count users and estimate files
                shot_users = 0
                for user_path in user_dir.iterdir():
                    if not user_path.is_dir():
                        continue

                    user_name = user_path.name
                    if user_name in excluded_users:
                        continue

                    shot_users += 1

                    # Quick estimate of .3de files (using glob count without reading)
                    try:
                        # Use a simple count - don't verify files yet
                        # Count both lowercase and uppercase extensions
                        file_count = len(list(user_path.rglob("*.3de"))) + len(
                            list(user_path.rglob("*.3DE"))
                        )
                        total_files_estimate += file_count
                    except (PermissionError, OSError):
                        # Estimate based on average if we can't access
                        total_files_estimate += 5  # Conservative estimate

                total_users += shot_users

            except (PermissionError, OSError):
                # Estimate based on typical shot structure
                total_users += 3  # Estimate 3 users per shot
                total_files_estimate += 10  # Estimate 10 files total

        logger.debug(
            f"Scan estimation: {total_users} users, ~{total_files_estimate} files"
        )
        return total_users, total_files_estimate

    @staticmethod
    def verify_scene_exists(scene_path: Path) -> bool:
        """Verify that a 3DE scene file exists and is readable.

        Args:
            scene_path: Path to the .3de file

        Returns:
            True if file exists and is readable
        """
        if not scene_path:
            logger.debug("Empty scene path provided")
            return False

        try:
            # Use PathUtils for consistent validation
            if not PathUtils.validate_path_exists(scene_path, "3DE scene file"):
                return False

            # Additional checks for file type and readability
            if not scene_path.is_file():
                logger.debug(f"Path is not a file: {scene_path}")
                return False

            if not os.access(scene_path, os.R_OK):
                logger.debug(f"File is not readable: {scene_path}")
                return False

            # Check file extension
            if scene_path.suffix.lower() not in [
                ext.lower() for ext in Config.THREEDE_EXTENSIONS
            ]:
                logger.debug(f"File does not have 3DE extension: {scene_path}")
                return False

            logger.debug(f"3DE scene file verified: {scene_path}")
            return True

        except Exception as e:
            logger.warning(f"Error verifying 3DE scene file {scene_path}: {e}")
            return False

    @staticmethod
    def find_all_3de_files_in_show(
        show_root: str,
        show: str,
        sequences: Optional[Set[str]] = None,
        timeout_seconds: int = 30,
    ) -> List[Path]:
        """Efficiently find ALL .3de files in a show using a single find command.

        This is the new efficient approach - find files first, then extract shots.
        Much faster than discovering all shots then checking each one.

        Args:
            show_root: Root directory for shows (e.g., /shows)
            show: Show name
            sequences: Optional set of sequences to limit search to (for performance)
            timeout_seconds: Maximum time for find command

        Returns:
            List of all .3de file paths found in the show/sequences
        """
        import subprocess

        show_path = Path(show_root) / show / "shots"
        if not show_path.exists():
            logger.warning(f"Show shots directory does not exist: {show_path}")
            return []

        # Determine search paths based on sequences parameter
        search_paths = []
        if sequences:
            # Limit to specific sequences for performance
            logger.info(
                f"Efficiently finding .3de files in {len(sequences)} sequences of {show}"
            )
            for seq in sequences:
                seq_path = show_path / seq
                if seq_path.exists():
                    search_paths.append(str(seq_path))
            if not search_paths:
                logger.warning(f"No valid sequence paths found in {show}")
                return []
        else:
            # Search entire show
            logger.info(f"Efficiently finding all .3de files in {show}")
            search_paths = [str(show_path)]

        try:
            # Use find to get all .3de files in one command (very fast)
            # Include both .3de and .3DE extensions
            cmd = (
                ["find"]
                + search_paths
                + ["-type", "f", "(", "-name", "*.3de", "-o", "-name", "*.3DE", ")"]
            )
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_seconds
            )

            if result.returncode != 0:
                logger.warning(f"Find command failed: {result.stderr}")
                return []

            # Parse output into Path objects
            threede_files = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    threede_files.append(Path(line))

            logger.info(f"Found {len(threede_files)} .3de files in {show}")
            return threede_files

        except subprocess.TimeoutExpired:
            logger.error(f"Find command timed out after {timeout_seconds}s")
            return []
        except FileNotFoundError:
            logger.error("'find' command not available - falling back to slower method")
            # Fall back to recursive glob (slower but works everywhere)
            threede_files = list(show_path.rglob("*.3de"))
            threede_files.extend(list(show_path.rglob("*.3DE")))
            return threede_files
        except Exception as e:
            logger.error(f"Error finding .3de files: {e}")
            return []

    @staticmethod
    def extract_shot_info_from_path(
        file_path: Path,
    ) -> Optional[Tuple[str, str, str, str]]:
        """Extract shot information from a .3de file path.

        Expected pattern: /shows/{show}/shots/{sequence}/{shot}/user/{username}/.../*.3de

        Args:
            file_path: Path to .3de file

        Returns:
            Tuple of (workspace_path, sequence, shot, username) or None if invalid
        """
        try:
            parts = file_path.parts

            # Find the shots directory index
            if "shots" not in parts:
                logger.debug(f"No 'shots' in path: {file_path}")
                return None

            shots_idx = parts.index("shots")

            # Need at least: shots/{sequence}/{shot}/user/{username}/...
            if len(parts) < shots_idx + 5:
                logger.debug(f"Path too short: {file_path}")
                return None

            # Extract components
            sequence = parts[shots_idx + 1]
            shot = parts[shots_idx + 2]

            # Verify user directory exists
            if parts[shots_idx + 3] != "user":
                logger.debug(f"No 'user' directory in expected position: {file_path}")
                return None

            username = parts[shots_idx + 4]

            # Build workspace path (up to shot directory)
            workspace_path = str(Path(*parts[: shots_idx + 3]))

            return (workspace_path, sequence, shot, username)

        except (IndexError, ValueError) as e:
            logger.debug(f"Could not extract shot info from {file_path}: {e}")
            return None

    @staticmethod
    def find_all_scenes_in_shows_efficient(
        user_shots: List[Any],  # List of Shot objects
        excluded_users: Optional[Set[str]] = None,
    ) -> List[ThreeDEScene]:
        """Efficient version of find_all_scenes_in_shows using file-first discovery.

        Instead of discovering all shots then checking each, this:
        1. Finds all .3de files in the show first (respecting scan mode)
        2. Extracts shot information from the paths
        3. Only processes shots that actually have .3de files

        This is orders of magnitude faster for shows with many shots.

        Args:
            user_shots: User's assigned shots (used to determine which shows to search)
            excluded_users: Set of usernames to exclude

        Returns:
            List of all ThreeDEScene objects found
        """
        if not user_shots:
            logger.info("No user shots provided for show-wide search")
            return []

        if excluded_users is None:
            excluded_users = ValidationUtils.get_excluded_users()

        # Check scan mode configuration
        scan_mode = (
            Config.THREEDE_SCAN_MODE
            if hasattr(Config, "THREEDE_SCAN_MODE")
            else "smart"
        )
        max_shots = (
            Config.THREEDE_MAX_SHOTS_TO_SCAN
            if hasattr(Config, "THREEDE_MAX_SHOTS_TO_SCAN")
            else 200
        )

        # For backwards compatibility with old find_all_scenes_in_shows
        if not Config.THREEDE_FILE_FIRST_DISCOVERY:
            logger.info("File-first discovery disabled, using old method")
            return ThreeDESceneFinder.find_all_scenes_in_shows(
                user_shots, excluded_users
            )

        # Extract unique shows and their roots
        shows_to_search = set()
        show_roots = {}
        user_sequences = {}  # show -> set of sequences

        for shot in user_shots:
            shows_to_search.add(shot.show)
            # Extract show root from workspace path
            workspace_parts = Path(shot.workspace_path).parts
            if "shows" in workspace_parts:
                shows_idx = workspace_parts.index("shows")
                show_root = "/".join(workspace_parts[: shows_idx + 1])
                show_roots[shot.show] = show_root

            # Track user's sequences for each show
            if shot.show not in user_sequences:
                user_sequences[shot.show] = set()
            user_sequences[shot.show].add(shot.sequence)

        if not show_roots:
            # Use default if we couldn't extract
            default_root = (
                Config.SHOWS_ROOT if hasattr(Config, "SHOWS_ROOT") else "/shows"
            )
            for show in shows_to_search:
                show_roots[show] = default_root

        logger.info(
            f"Efficient 3DE search across shows: {shows_to_search} (mode: {scan_mode})"
        )

        all_scenes = []
        total_shots_processed = 0

        for show in shows_to_search:
            show_root = show_roots.get(show, "/shows")

            # Determine which sequences to search based on scan mode
            sequences_to_search = None
            if scan_mode == "user_sequences" and Config.THREEDE_SCAN_RELATED_SEQUENCES:
                sequences_to_search = user_sequences.get(show, set())
                logger.info(
                    f"Limiting search to user's {len(sequences_to_search)} sequences in {show}"
                )

            # Step 1: Find .3de files (respecting sequence limits)
            threede_files = ThreeDESceneFinder.find_all_3de_files_in_show(
                show_root,
                show,
                sequences_to_search,
                timeout_seconds=Config.THREEDE_SCAN_TIMEOUT_SECONDS,
            )

            if not threede_files:
                logger.info(f"No .3de files found in {show}")
                continue

            logger.info(f"Processing {len(threede_files)} .3de files in {show}")

            # Step 2: Group files by shot for efficient processing
            shots_with_files = {}  # (sequence, shot) -> list of (username, file_path)

            for file_path in threede_files:
                # Extract shot info from path
                shot_info = ThreeDESceneFinder.extract_shot_info_from_path(file_path)
                if not shot_info:
                    continue

                workspace_path, sequence, shot_name, username = shot_info

                # Skip excluded users
                if username in excluded_users:
                    continue

                shot_key = (sequence, shot_name)
                if shot_key not in shots_with_files:
                    shots_with_files[shot_key] = {
                        "workspace_path": workspace_path,
                        "files": [],
                    }
                shots_with_files[shot_key]["files"].append((username, file_path))

            # Check if we're approaching the max shots limit
            shots_to_process = len(shots_with_files)
            if total_shots_processed + shots_to_process > max_shots:
                remaining = max_shots - total_shots_processed
                logger.warning(
                    f"Reached max shots limit ({max_shots}). "
                    f"Processing only {remaining} of {shots_to_process} shots in {show}"
                )
                # Limit the shots we process
                shots_with_files = dict(list(shots_with_files.items())[:remaining])

            # Step 3: Create ThreeDEScene objects for each file
            for (sequence, shot_name), shot_data in shots_with_files.items():
                workspace_path = shot_data["workspace_path"]

                for username, file_path in shot_data["files"]:
                    # Extract plate info
                    user_path = file_path.parent
                    while user_path.name != username and user_path.parent != user_path:
                        user_path = user_path.parent

                    plate = ThreeDESceneFinder.extract_plate_from_path(
                        file_path, user_path
                    )

                    # Create scene object
                    scene = ThreeDEScene(
                        show=show,
                        sequence=sequence,
                        shot=shot_name,
                        workspace_path=workspace_path,
                        user=username,
                        plate=plate,
                        scene_path=file_path,
                    )
                    all_scenes.append(scene)

            total_shots_processed += len(shots_with_files)
            logger.info(
                f"Found {len(all_scenes)} scenes in {show} from {len(shots_with_files)} shots "
                f"(total shots processed: {total_shots_processed})"
            )

            # Early exit if we've hit the limit
            if total_shots_processed >= max_shots:
                logger.info(
                    f"Reached maximum shot limit ({max_shots}), stopping search"
                )
                break

        logger.info(
            f"Efficient search complete: {len(all_scenes)} total scenes from {total_shots_processed} shots"
        )
        return all_scenes
