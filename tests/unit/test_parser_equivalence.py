"""Verify OptimizedShotParser produces same results as regex-based overrides.

Phase 4A equivalence check: confirms the base class parser can replace
the subclass overrides in TargetedShotsFinder and PreviousShotsFinder.
"""

from __future__ import annotations

import re

import pytest

from config import Config
from paths.shot_dir_parser import build_workspace_path, parse_shot_from_dir
from shots.shot_parser import OptimizedShotParser


pytestmark = [pytest.mark.unit]


# Representative production paths (all start with Config.Paths.SHOWS_ROOT)
PRODUCTION_PATHS = [
    # Standard VFX naming: {sequence}_{shot}
    f"{Config.Paths.SHOWS_ROOT}/feature_film/shots/010_opening/010_opening_0010/user/testuser",
    f"{Config.Paths.SHOWS_ROOT}/feature_film/shots/020_chase/020_chase_0020/user/testuser",
    f"{Config.Paths.SHOWS_ROOT}/commercial/shots/sq010/sq010_sh020/user/testuser",
    # Trailing slash variants
    f"{Config.Paths.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1/",
    # No trailing content after shot dir
    f"{Config.Paths.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1",
    # Deep nested content after shot dir
    f"{Config.Paths.SHOWS_ROOT}/show1/shots/seq1/seq1_shot1/user/artist/3de4/scenes",
]


def _targeted_parse(path: str) -> tuple[str, str, str, str] | None:
    """Reproduce TargetedShotsFinder._parse_shot_from_path logic."""
    shows_root_escaped = re.escape(Config.Paths.SHOWS_ROOT)
    pattern = re.compile(rf"{shows_root_escaped}/([^/]+)/shots/([^/]+)/([^/]+)/")
    match = pattern.search(path)
    if not match:
        return None
    show, sequence, shot_dir = match.groups()
    shot = parse_shot_from_dir(sequence, shot_dir)
    if not shot:
        return None
    workspace_path = str(build_workspace_path(Config.Paths.SHOWS_ROOT, show, sequence, shot))
    return (show, sequence, shot, workspace_path)


def _previous_parse(path: str) -> tuple[str, str, str, str] | None:
    """Reproduce PreviousShotsFinder._parse_shot_from_path logic."""
    pattern = re.compile(r"(.*?/shows/([^/]+)/shots/([^/]+)/([^/]+))(?:/|$)")
    match = pattern.search(path)
    if not match:
        return None
    workspace_path, show, sequence, shot_dir = match.groups()
    shot = parse_shot_from_dir(sequence, shot_dir)
    if not shot:
        return None
    return (show, sequence, shot, workspace_path)


def _base_class_parse(path: str) -> tuple[str, str, str, str] | None:
    """Reproduce base class _parse_shot_from_path logic (via OptimizedShotParser)."""
    parser = OptimizedShotParser()
    result = parser.parse_shot_path(path)
    if not result or not result.shot:
        return None
    return (result.show, result.sequence, result.shot, result.workspace_path)


@pytest.mark.parametrize("path", PRODUCTION_PATHS)
class TestParserEquivalence:
    def test_base_matches_targeted(self, path: str) -> None:
        """OptimizedShotParser matches TargetedShotsFinder regex for all production paths."""
        base_result = _base_class_parse(path)
        targeted_result = _targeted_parse(path)
        # Both may be None for paths without trailing slash (targeted requires /)
        if targeted_result is not None:
            assert base_result is not None, (
                f"Base returned None but targeted returned {targeted_result}"
            )
            assert base_result == targeted_result, (
                f"Mismatch:\n  base:     {base_result}\n  targeted: {targeted_result}"
            )

    def test_base_matches_previous(self, path: str) -> None:
        """OptimizedShotParser matches PreviousShotsFinder regex for all production paths."""
        base_result = _base_class_parse(path)
        previous_result = _previous_parse(path)
        if previous_result is not None:
            assert base_result is not None, (
                f"Base returned None but previous returned {previous_result}"
            )
            assert base_result == previous_result, (
                f"Mismatch:\n  base:     {base_result}\n  previous: {previous_result}"
            )
