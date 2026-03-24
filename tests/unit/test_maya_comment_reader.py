"""Tests for the Maya version-up comment reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from discovery.maya_comment_reader import _parse_base, load_maya_comments

pytestmark = [pytest.mark.unit]


class TestParseBase:
    """Tests for _parse_base — extracting filename base before version token."""

    def test_underscore_separator(self) -> None:
        assert _parse_base("cameratrackBG01_v003") == "cameratrackBG01"

    def test_hyphen_separator(self) -> None:
        assert _parse_base("matchmove-v009") == "matchmove"

    def test_no_separator(self) -> None:
        assert _parse_base("shotv001") == "shot"

    def test_no_version(self) -> None:
        assert _parse_base("no_version_here") is None

    def test_multi_underscore(self) -> None:
        assert _parse_base("shot_comp_final_v012") == "shot_comp_final"

    def test_single_digit_version(self) -> None:
        assert _parse_base("scene_v1") == "scene"

    def test_long_padding(self) -> None:
        assert _parse_base("scene_v00007") == "scene"


class TestLoadMayaComments:
    """Tests for load_maya_comments — reading from ~/.maya_version_up/."""

    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        """Returns empty dict when comments directory doesn't exist."""
        import discovery.maya_comment_reader as mod

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = tmp_path / "nonexistent"
        try:
            result = load_maya_comments([Path("/shot/scene_v001.ma")])
            assert result == {}
        finally:
            mod._COMMENTS_DIR = original

    def test_loads_comment_for_matching_path(self, tmp_path: Path) -> None:
        """Returns comment when path matches an entry in the JSON file."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_file = comments_dir / "scene.json"
        json_file.write_text(json.dumps({"/shot/scene_v001.ma": "Initial layout"}))

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            result = load_maya_comments([Path("/shot/scene_v001.ma")])
            assert result == {"/shot/scene_v001.ma": "Initial layout"}
        finally:
            mod._COMMENTS_DIR = original

    def test_returns_empty_for_unmatched_path(self, tmp_path: Path) -> None:
        """Returns empty dict when the path is not in the JSON."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_file = comments_dir / "scene.json"
        json_file.write_text(json.dumps({"/shot/scene_v001.ma": "comment"}))

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            result = load_maya_comments([Path("/shot/scene_v002.ma")])
            assert result == {}
        finally:
            mod._COMMENTS_DIR = original

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        """Skips JSON files that are corrupt without crashing."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_file = comments_dir / "scene.json"
        json_file.write_text("not valid json {{{{")

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            result = load_maya_comments([Path("/shot/scene_v001.ma")])
            assert result == {}
        finally:
            mod._COMMENTS_DIR = original

    def test_multiple_files_different_bases(self, tmp_path: Path) -> None:
        """Loads comments from multiple JSON files for different bases."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()

        (comments_dir / "sceneA.json").write_text(
            json.dumps({"/shot/sceneA_v001.ma": "comment A"})
        )
        (comments_dir / "sceneB.json").write_text(
            json.dumps({"/shot/sceneB_v003.ma": "comment B"})
        )

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            result = load_maya_comments(
                [Path("/shot/sceneA_v001.ma"), Path("/shot/sceneB_v003.ma")]
            )
            assert result == {
                "/shot/sceneA_v001.ma": "comment A",
                "/shot/sceneB_v003.ma": "comment B",
            }
        finally:
            mod._COMMENTS_DIR = original
