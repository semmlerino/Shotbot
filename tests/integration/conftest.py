"""Configuration and fixtures for integration tests."""

# Standard library imports
from pathlib import Path

# Third-party imports
import pytest

# Local application imports
from type_definitions import Shot


# Markers are registered in pyproject.toml [tool.pytest.ini_options] markers


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Modify test collection to handle custom markers."""
    # Add integration marker to all tests in this directory
    for item in items:
        if "integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


# NOTE: Singleton isolation is handled by reset_caches autouse fixture +
# _qt_auto_fixtures dispatcher (activates qt_cleanup and cleanup_state_heavy
# for detected Qt tests). See tests/conftest.py.


def create_test_vfx_structure(
    shows_root: Path,
    show_names: list[str] | None = None,
    users: list[str] | None = None,
    user_subdirs: list[str] | None = None,
) -> tuple[Path, list[Shot]]:
    """Create a realistic VFX directory structure for integration testing.

    Creates a multi-show hierarchy with sequences, shots, user directories,
    and 3DE scene files. Callers pass their own ``shows_root`` path (typically
    derived from ``tmp_path``) so each test gets an isolated tree.

    Args:
        shows_root: Root directory under which show directories are created.
        show_names: List of show names to create. Defaults to
            ``["TESTSHOW", "ANOTHERSHOW"]``.
        users: List of user directory names to create per shot. Defaults to
            ``["artist1", "artist2", "supervisor"]``.
        user_subdirs: List of subdirectory paths (relative to the per-user
            directory) in which ``.3de`` files are written. Defaults to
            ``["3de/scenes", "matchmove/3de/FG01", "matchmove/3de", "tracking"]``.

    Returns:
        A tuple of ``(shows_root, shots)`` where ``shows_root`` is the path
        passed in and ``shots`` is the list of :class:`Shot` objects created.

    """
    if show_names is None:
        show_names = ["TESTSHOW", "ANOTHERSHOW"]
    if users is None:
        users = ["artist1", "artist2", "supervisor"]
    if user_subdirs is None:
        # Union of all subdirs used across the two original helpers
        user_subdirs = ["3de/scenes", "matchmove/3de/FG01", "matchmove/3de", "tracking"]

    seq_names = [f"seq{n:03d}" for n in range(1, 3)]  # seq001, seq002
    shot_numbers = [f"{n:04d}" for n in [10, 20, 30]]  # 0010, 0020, 0030

    test_shots: list[Shot] = []

    for show_name in show_names:
        show_dir = shows_root / show_name / "shots"

        for seq_name in seq_names:
            for shot_number in shot_numbers:
                shot_path = show_dir / seq_name / f"{seq_name}_{shot_number}"

                for user in users:
                    for subdir in user_subdirs:
                        work_dir = shot_path / "user" / user / subdir
                        work_dir.mkdir(parents=True, exist_ok=True)
                        scene_file = (
                            work_dir
                            / f"{show_name}_{seq_name}_{shot_number}_BG01.3de"
                        )
                        scene_file.write_text(
                            f"# 3DE Scene\nversion 1.0\nshow: {show_name}"
                        )

                shot = Shot(
                    show=show_name,
                    sequence=seq_name,
                    shot=shot_number,
                    workspace_path=str(shot_path),
                )
                test_shots.append(shot)

    return shows_root, test_shots
