"""Unit tests for shot_parser.py.

Tests cover:
- parse_workspace_line(): standard, non-prefix, short names, no underscore, None cases
- parse_shot_path(): path-only equivalents of the above
- Pattern cache isolation when Config.Paths.SHOWS_ROOT changes
- Multiple-underscore sequence/shot names with prefix extraction vs rfind fallback
"""

from __future__ import annotations

import pytest

from shots import shot_parser
from shots.shot_parser import OptimizedShotParser


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_pattern_cache() -> None:
    """Clear the module-level pattern cache before every test for isolation."""
    shot_parser._PATTERN_CACHE.clear()


# ---------------------------------------------------------------------------
# parse_workspace_line — standard naming (seq prefix stripping)
# ---------------------------------------------------------------------------


class TestParseWorkspaceLineStandard:
    """Standard workspace lines where shot_dir starts with sequence name + '_'."""

    def test_standard_seq_shot(self) -> None:
        """workspace /shows/root/demo/shots/seq01/seq01_0010 → shot=0010."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace /shows/demo/shots/seq01/seq01_0010"
        )

        assert result is not None
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"
        assert result.workspace_path == "/shows/demo/shots/seq01/seq01_0010"

    def test_workspace_path_matches_parsed_path(self) -> None:
        """workspace_path field equals the full path captured from the line."""
        parser = OptimizedShotParser()
        line = "workspace /shows/myshow/shots/A01/A01_0230"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.workspace_path == "/shows/myshow/shots/A01/A01_0230"

    def test_show_with_underscore(self) -> None:
        """Show names containing underscores are parsed correctly."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace /shows/jack_ryan/shots/100/100_0010"
        )

        assert result is not None
        assert result.show == "jack_ryan"
        assert result.sequence == "100"
        assert result.shot == "0010"


# ---------------------------------------------------------------------------
# parse_workspace_line — non-prefix / rfind fallback
# ---------------------------------------------------------------------------


class TestParseWorkspaceLineNonPrefix:
    """Cases where shot_dir does NOT start with sequence name + '_', so rfind is used."""

    def test_brx_sequence_rfind_fallback(self) -> None:
        """workspace .../broken_eggs/shots/BRX/BRX_166 → shot=166 via rfind."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace /shows/broken_eggs/shots/BRX/BRX_166"
        )

        assert result is not None
        assert result.show == "broken_eggs"
        assert result.sequence == "BRX"
        assert result.shot == "166"

    def test_short_shot_name_after_numeric_seq(self) -> None:
        """workspace .../gator/shots/012/012_DC → shot=DC (short suffix)."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("workspace /shows/gator/shots/012/012_DC")

        assert result is not None
        assert result.show == "gator"
        assert result.sequence == "012"
        assert result.shot == "DC"

    def test_different_prefix_uses_rfind(self) -> None:
        """When shot_dir prefix differs from sequence, rfind picks last underscore."""
        parser = OptimizedShotParser()
        # sequence='seq', shot_dir='other_prefix_0010' — does NOT start with 'seq'
        result = parser.parse_workspace_line(
            "workspace /shows/myshow/shots/seq/other_prefix_0010"
        )

        assert result is not None
        assert result.shot == "0010"


# ---------------------------------------------------------------------------
# parse_workspace_line — multiple underscores (compound names)
# ---------------------------------------------------------------------------


class TestParseWorkspaceLineMultipleUnderscores:
    """Shot directories and sequence names that contain multiple underscores."""

    def test_compound_sequence_prefix_extraction(self) -> None:
        """A_B sequence with A_B_C_D shot_dir uses prefix stripping → shot=C_D."""
        parser = OptimizedShotParser()
        # sequence='A_B', shot_dir='A_B_C_D' — starts with 'A_B_', so strip prefix
        result = parser.parse_workspace_line("workspace /shows/show/shots/A_B/A_B_C_D")

        assert result is not None
        assert result.sequence == "A_B"
        assert result.shot == "C_D"

    def test_compound_sequence_real_world_db_271(self) -> None:
        """DB_271 sequence with DB_271_1760 shot_dir → shot=1760 via prefix strip."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace /shows/jack_ryan/shots/DB_271/DB_271_1760"
        )

        assert result is not None
        assert result.sequence == "DB_271"
        assert result.shot == "1760"

    def test_compound_sequence_brx_166(self) -> None:
        """BRX_166 sequence with BRX_166_0010 shot_dir → shot=0010 via prefix strip."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace /shows/broken_eggs/shots/BRX_166/BRX_166_0010"
        )

        assert result is not None
        assert result.sequence == "BRX_166"
        assert result.shot == "0010"


# ---------------------------------------------------------------------------
# parse_workspace_line — edge cases (no underscore, None returns)
# ---------------------------------------------------------------------------


class TestParseWorkspaceLineEdgeCases:
    """Edge cases: no underscore in shot_dir, invalid/non-matching lines."""

    def test_no_underscore_uses_full_directory(self) -> None:
        """shot_dir with no underscore → shot equals the full directory name."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("workspace /shows/show/shots/seq/shotonly")

        assert result is not None
        assert result.shot == "shotonly"

    def test_non_matching_line_returns_none(self) -> None:
        """Line without 'workspace' prefix returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("/shows/demo/shots/seq01/seq01_0010")

        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("")

        assert result is None

    def test_arbitrary_text_returns_none(self) -> None:
        """Random text with no valid path structure returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("some random text without a path")

        assert result is None

    def test_wrong_shows_root_returns_none(self) -> None:
        """Path whose root does not match Config.Paths.SHOWS_ROOT returns None."""
        parser = OptimizedShotParser()
        # Config.Paths.SHOWS_ROOT is /shows (set by unit conftest); this uses /wrong
        result = parser.parse_workspace_line(
            "workspace /wrong/root/demo/shots/seq01/seq01_0010"
        )

        assert result is None

    def test_partial_path_missing_shots_segment_returns_none(self) -> None:
        """Path without /shots/ segment returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line("workspace /shows/demo")

        assert result is None

    def test_extra_whitespace_after_workspace_keyword(self) -> None:
        """Multiple spaces after 'workspace' keyword are accepted."""
        parser = OptimizedShotParser()
        result = parser.parse_workspace_line(
            "workspace   /shows/demo/shots/seq01/seq01_0010"
        )

        assert result is not None
        assert result.shot == "0010"


# ---------------------------------------------------------------------------
# parse_shot_path — mirrors workspace line tests but with path-only input
# ---------------------------------------------------------------------------


class TestParseShotPath:
    """parse_shot_path() tests — no 'workspace ' prefix, just the filesystem path."""

    def test_standard_path(self) -> None:
        """/shows/demo/shots/seq01/seq01_0010 → show=demo, seq=seq01, shot=0010."""
        parser = OptimizedShotParser()
        path = "/shows/demo/shots/seq01/seq01_0010"

        result = parser.parse_shot_path(path)

        assert result is not None
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"
        assert result.workspace_path == path

    def test_non_prefix_sequence(self) -> None:
        """/shows/broken_eggs/shots/BRX/BRX_166 → shot=166."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/shows/broken_eggs/shots/BRX/BRX_166")

        assert result is not None
        assert result.show == "broken_eggs"
        assert result.sequence == "BRX"
        assert result.shot == "166"

    def test_short_shot_name(self) -> None:
        """/shows/gator/shots/012/012_DC → shot=DC."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/shows/gator/shots/012/012_DC")

        assert result is not None
        assert result.shot == "DC"

    def test_no_underscore_in_shot_dir(self) -> None:
        """shot_dir without underscore → shot equals the full directory name."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/shows/show/shots/seq/shotonly")

        assert result is not None
        assert result.shot == "shotonly"

    def test_invalid_path_returns_none(self) -> None:
        """Path not matching SHOWS_ROOT structure returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/some/random/path")

        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("")

        assert result is None

    def test_path_with_trailing_slash(self) -> None:
        """Trailing slash in path is handled correctly."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path("/shows/demo/shots/seq01/seq01_0010/")

        assert result is not None
        assert result.shot == "0010"

    def test_path_with_subdirectory(self) -> None:
        """Path with subdirectories after shot_dir still parses correctly."""
        parser = OptimizedShotParser()
        result = parser.parse_shot_path(
            "/shows/demo/shots/seq01/seq01_0010/user/3de/scene.3de"
        )

        assert result is not None
        assert result.show == "demo"
        assert result.sequence == "seq01"
        assert result.shot == "0010"

    def test_workspace_path_reconstructed_from_shows_root(self) -> None:
        """workspace_path field is built from Config.Paths.SHOWS_ROOT, show, seq, shot_dir."""
        parser = OptimizedShotParser()
        path = "/shows/demo/shots/seq01/seq01_0010/user/artist"

        result = parser.parse_shot_path(path)

        assert result is not None
        # workspace_path should not include the trailing subdirectory
        assert result.workspace_path == "/shows/demo/shots/seq01/seq01_0010"


# ---------------------------------------------------------------------------
# Pattern cache isolation
# ---------------------------------------------------------------------------


class TestPatternCacheIsolation:
    """_PATTERN_CACHE is keyed by SHOWS_ROOT; changing the root creates new entries."""

    def test_new_shows_root_creates_new_cache_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two distinct SHOWS_ROOT values produce two cache entries."""
        monkeypatch.setattr("config.Config.Paths.SHOWS_ROOT", "/test/shows1")
        _ = OptimizedShotParser()
        assert "/test/shows1" in shot_parser._PATTERN_CACHE

        monkeypatch.setattr("config.Config.Paths.SHOWS_ROOT", "/test/shows2")
        _ = OptimizedShotParser()
        assert "/test/shows2" in shot_parser._PATTERN_CACHE

        # Both present simultaneously
        assert len(shot_parser._PATTERN_CACHE) >= 2

    def test_same_shows_root_reuses_cache_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple parsers with the same SHOWS_ROOT share cached pattern objects."""
        monkeypatch.setattr("config.Config.Paths.SHOWS_ROOT", "/test/shared")
        p1 = OptimizedShotParser()
        p2 = OptimizedShotParser()

        # Identity check — same compiled pattern object
        assert p1._ws_pattern is p2._ws_pattern
        assert p1._path_pattern is p2._path_pattern

    def test_parser_respects_custom_shows_root(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Parser uses the custom SHOWS_ROOT when building patterns."""
        custom_root = "/custom/vfx/shows"
        monkeypatch.setattr("config.Config.Paths.SHOWS_ROOT", custom_root)
        # Reload module to pick up the new Config value in pattern compilation
        import importlib

        importlib.reload(shot_parser)
        shot_parser._PATTERN_CACHE.clear()

        parser = shot_parser.OptimizedShotParser()
        line = f"workspace {custom_root}/demo/shots/seq01/seq01_0010"

        result = parser.parse_workspace_line(line)

        assert result is not None
        assert result.show == "demo"
        assert result.workspace_path.startswith(custom_root)

    def test_old_shows_root_does_not_match_new_parser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Parser built with root A rejects paths from root B."""
        import importlib

        monkeypatch.setattr("config.Config.Paths.SHOWS_ROOT", "/root/a")
        importlib.reload(shot_parser)
        shot_parser._PATTERN_CACHE.clear()
        parser_a = shot_parser.OptimizedShotParser()

        # parser_a was compiled for /root/a; a /root/b path should not match
        result = parser_a.parse_workspace_line(
            "workspace /root/b/demo/shots/seq01/seq01_0010"
        )

        assert result is None
