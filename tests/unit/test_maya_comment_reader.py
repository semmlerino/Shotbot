"""Tests for the Maya version-up comment reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from discovery import load_maya_comments, save_maya_comment
from discovery.maya_comment_reader import _parse_base


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


class TestSaveMayaComment:
    """Tests for save_maya_comment — writing to ~/.maya_version_up/."""

    def test_creates_dir_and_file(self, tmp_path: Path) -> None:
        """Creates the comments directory and JSON file when they don't exist."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            save_maya_comment(Path("/shot/scene_v001.ma"), "New layout")

            json_path = comments_dir / "scene.json"
            assert json_path.exists()
            data = json.loads(json_path.read_text())
            assert data == {"/shot/scene_v001.ma": "New layout"}
        finally:
            mod._COMMENTS_DIR = original

    def test_preserves_existing_entries(self, tmp_path: Path) -> None:
        """Preserves other entries in the JSON file when adding a new comment."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_path = comments_dir / "scene.json"
        json_path.write_text(json.dumps({"/shot/scene_v001.ma": "Old comment"}))

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            save_maya_comment(Path("/shot/scene_v002.ma"), "Second version")

            data = json.loads(json_path.read_text())
            assert data == {
                "/shot/scene_v001.ma": "Old comment",
                "/shot/scene_v002.ma": "Second version",
            }
        finally:
            mod._COMMENTS_DIR = original

    def test_overwrites_existing_comment(self, tmp_path: Path) -> None:
        """Overwrites an existing comment for the same path."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_path = comments_dir / "scene.json"
        json_path.write_text(json.dumps({"/shot/scene_v001.ma": "Old comment"}))

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            save_maya_comment(Path("/shot/scene_v001.ma"), "Updated comment")

            data = json.loads(json_path.read_text())
            assert data == {"/shot/scene_v001.ma": "Updated comment"}
        finally:
            mod._COMMENTS_DIR = original

    def test_empty_comment_removes_entry(self, tmp_path: Path) -> None:
        """Empty comment removes the entry from the JSON file."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        comments_dir.mkdir()
        json_path = comments_dir / "scene.json"
        json_path.write_text(
            json.dumps({
                "/shot/scene_v001.ma": "Will be removed",
                "/shot/scene_v002.ma": "Stays",
            })
        )

        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            save_maya_comment(Path("/shot/scene_v001.ma"), "")

            data = json.loads(json_path.read_text())
            assert data == {"/shot/scene_v002.ma": "Stays"}
        finally:
            mod._COMMENTS_DIR = original

    def test_no_version_token_is_noop(self, tmp_path: Path) -> None:
        """Paths without a version token are silently ignored."""
        import discovery.maya_comment_reader as mod

        comments_dir = tmp_path / ".maya_version_up"
        original = mod._COMMENTS_DIR
        mod._COMMENTS_DIR = comments_dir
        try:
            save_maya_comment(Path("/shot/no_version.ma"), "Should not write")
            assert not comments_dir.exists()
        finally:
            mod._COMMENTS_DIR = original
