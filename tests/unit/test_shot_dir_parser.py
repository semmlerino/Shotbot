"""Tests for the canonical shot directory parser."""

from __future__ import annotations

from pathlib import Path

from paths.shot_dir_parser import (
    build_workspace_path,
    parse_shot_from_dir,
    parse_workspace_path,
    resolve_shows_root,
)


class TestParseShotFromDir:
    """Tests for parse_shot_from_dir."""

    def test_standard_naming(self) -> None:
        assert parse_shot_from_dir("SQ010", "SQ010_0010") == "0010"

    def test_numeric_sequence(self) -> None:
        assert parse_shot_from_dir("012", "012_DC") == "DC"

    def test_multi_underscore_sequence(self) -> None:
        """Regression test for the _shot_key.py split('_', 1) bug."""
        assert parse_shot_from_dir("multi_part", "multi_part_0010") == "0010"

    def test_no_underscore(self) -> None:
        assert parse_shot_from_dir("SEQ", "SHOT") == "SHOT"

    def test_sequence_not_prefix(self) -> None:
        """When shot_dir doesn't start with sequence, fall back to rsplit."""
        assert parse_shot_from_dir("ABC", "XYZ_0010") == "0010"

    def test_empty_shot_after_prefix(self) -> None:
        """Edge case: sequence_ with nothing after."""
        assert parse_shot_from_dir("SEQ", "SEQ_") == ""

    def test_multiple_underscores_in_shot(self) -> None:
        """When dir has multiple underscores and sequence matches prefix."""
        assert parse_shot_from_dir("SEQ", "SEQ_sub_0010") == "sub_0010"


class TestParseWorkspacePath:
    """Tests for parse_workspace_path."""

    def test_standard_path(self) -> None:
        result = parse_workspace_path("/shows/demo/shots/seq01/seq01_0010")
        assert result == ("demo", "seq01", "0010")

    def test_multi_underscore_sequence(self) -> None:
        result = parse_workspace_path("/shows/demo/shots/multi_part/multi_part_0010")
        assert result == ("demo", "multi_part", "0010")

    def test_deeply_nested(self) -> None:
        result = parse_workspace_path("/mnt/shows/demo/shots/SEQ/SEQ_0020/user/bob")
        assert result == ("demo", "SEQ", "0020")

    def test_invalid_path(self) -> None:
        assert parse_workspace_path("/some/random/path") is None

    def test_too_short(self) -> None:
        assert parse_workspace_path("/shows/demo/shots") is None


class TestBuildWorkspacePath:
    """Tests for build_workspace_path."""

    def test_build_workspace_path_basic(self) -> None:
        result = build_workspace_path("/shows", "PROJ", "sq010", "sh020")
        assert result == Path("/shows/PROJ/shots/sq010/sq010_sh020")

    def test_build_workspace_path_with_suffix(self) -> None:
        result = build_workspace_path("/shows", "PROJ", "sq010", "sh020", "3d", "maya")
        assert result == Path("/shows/PROJ/shots/sq010/sq010_sh020/3d/maya")


class TestResolveShowsRoot:
    """Tests for resolve_shows_root."""

    def test_resolve_shows_root_with_string(self) -> None:
        result = resolve_shows_root("/custom/shows")
        assert result == Path("/custom/shows")
        assert isinstance(result, Path)

    def test_resolve_shows_root_with_path(self) -> None:
        result = resolve_shows_root(Path("/custom/shows"))
        assert result == Path("/custom/shows")
        assert isinstance(result, Path)

    def test_resolve_shows_root_none_uses_config(self, mocker) -> None:
        mocker.patch("config.Config.Paths.SHOWS_ROOT", "/default/shows")
        result = resolve_shows_root(None)
        assert result == Path("/default/shows")
