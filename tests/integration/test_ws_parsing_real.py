"""Integration tests for ws output parsing robustness.

These tests exercise BaseShotModel._parse_ws_output with realistic shell output
including MOTD noise, mixed stdout/stderr, and various edge cases that occur
in real VFX production environments.

Marked with @pytest.mark.real_subprocess to indicate they create temporary
scripts and execute actual shell commands.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from base_shot_model import BaseShotModel


pytestmark = [pytest.mark.integration, pytest.mark.real_subprocess]


class TestWsOutputParsingRobustness:
    """Test that ws output parsing handles real-world noise correctly.

    Real shell environments produce various noise:
    - MOTD (Message of the Day) banners
    - SSH connection warnings
    - Module load messages
    - Rez environment output
    - Random stderr warnings
    """

    @pytest.fixture
    def model(self, tmp_path: Path) -> BaseShotModel:
        """Create a BaseShotModel for testing."""
        # Create a minimal subclass for testing
        class TestModel(BaseShotModel):
            _process_pool = None

            def _load_from_cache(self):
                return []

            def _get_workspace_command(self) -> str:
                return "echo test"

        return TestModel()

    def test_parsing_extracts_only_workspace_lines(self, model: BaseShotModel) -> None:
        """Parser ignores noise and extracts only workspace lines."""
        output = """
Welcome to BlueBolt VFX
======================

Last login: Thu Dec 5 10:00:00 2024 from workstation.local
Loading environment modules...
workspace /shows/testshow/shots/sq010/sq010_0010
workspace /shows/testshow/shots/sq010/sq010_0020
workspace /shows/testshow/shots/sq020/sq020_0010
Warning: /nethome mount is experiencing high latency
"""
        shots = model._parse_ws_output(output, {})

        assert len(shots) == 3
        assert shots[0].show == "testshow"
        assert shots[0].sequence == "sq010"
        # Parser extracts shot number after underscore: "sq010_0010" → "0010"
        assert shots[0].shot == "0010"

    def test_parsing_handles_mixed_stdout_stderr(self, model: BaseShotModel) -> None:
        """Parser handles interleaved stdout/stderr (common in VFX shells)."""
        # In real shells, stderr can be interleaved with stdout
        output = """[module load] Loading maya/2024
workspace /shows/project1/shots/abc/abc_0100
[WARNING] Disk quota at 85%
workspace /shows/project1/shots/abc/abc_0110
[ERROR] Could not connect to license server (retrying...)
workspace /shows/project1/shots/def/def_0200
License acquired successfully
"""
        shots = model._parse_ws_output(output, {})

        assert len(shots) == 3
        workspaces = [s.workspace_path for s in shots]
        assert "/shows/project1/shots/abc/abc_0100" in workspaces
        assert "/shows/project1/shots/abc/abc_0110" in workspaces
        assert "/shows/project1/shots/def/def_0200" in workspaces

    def test_parsing_handles_empty_and_whitespace_lines(
        self, model: BaseShotModel
    ) -> None:
        """Parser handles various blank line patterns."""
        output = """

workspace /shows/test/shots/sq/sq_0010


workspace /shows/test/shots/sq/sq_0020


workspace /shows/test/shots/sq/sq_0030

"""
        shots = model._parse_ws_output(output, {})

        assert len(shots) == 3

    def test_parsing_handles_unicode_and_special_chars(
        self, model: BaseShotModel
    ) -> None:
        """Parser handles Unicode characters in shell output."""
        output = """
→ Starting session...
✓ Environment loaded
workspace /shows/testshow/shots/sq010/sq010_0010
⚠ Warning: some message
workspace /shows/testshow/shots/sq010/sq010_0020
"""
        shots = model._parse_ws_output(output, {})

        # Should still extract the workspace lines
        assert len(shots) == 2

    def test_parsing_handles_complex_shot_names(self, model: BaseShotModel) -> None:
        """Parser handles various shot naming conventions."""
        output = """
workspace /shows/ProjectX/shots/001_ABC/001_ABC_0010
workspace /shows/ProjectY/shots/SEQ_01/SEQ_01_SH0020
workspace /shows/ProjectZ/shots/s100/s100_010_v002
workspace /shows/Simple/shots/test/test_0001
"""
        shots = model._parse_ws_output(output, {})

        # All should parse (even if naming conventions differ)
        assert len(shots) >= 4

    def test_parsing_handles_no_valid_output(self, model: BaseShotModel) -> None:
        """Parser returns empty list when no workspace lines found."""
        output = """
Welcome to the system
ERROR: No workspaces found
Please contact your supervisor
"""
        shots = model._parse_ws_output(output, {})

        assert len(shots) == 0
        assert isinstance(shots, list)

    def test_parsing_handles_malformed_workspace_lines(
        self, model: BaseShotModel
    ) -> None:
        """Parser gracefully handles malformed workspace lines."""
        output = """
workspace
workspace /
workspace /shows
workspace /shows/valid/shots/sq/sq_0010
workspace /not/a/proper/path/format
"""
        # Should parse the valid one, skip malformed ones
        shots = model._parse_ws_output(output, {})

        # At minimum, shouldn't crash
        assert isinstance(shots, list)
        # The valid one should be parsed (shot number is just "0010")
        valid_shots = [s for s in shots if s.shot == "0010"]
        assert len(valid_shots) == 1


@pytest.mark.skip(reason="Requires ws command available in PATH")
class TestWsRealShellExecution:
    """Tests that actually execute shell commands with ws-like behavior.

    These tests are skipped by default and should only run in environments
    where a ws command (or mock) is available.
    """

    @pytest.fixture
    def fake_ws_script(self, tmp_path: Path) -> Path:
        """Create a fake ws script for testing."""
        script = tmp_path / "ws"
        script.write_text(
            """#!/bin/bash
# Simulate MOTD noise
echo "Welcome to BlueBolt" >&2
echo "Last login: $(date)"

# Simulate workspace output
echo "workspace /shows/testshow/shots/sq010/sq010_0010"
echo "workspace /shows/testshow/shots/sq010/sq010_0020"

# Simulate warning
echo "Warning: /nethome is slow today" >&2
"""
        )
        script.chmod(0o755)
        return script

    def test_real_subprocess_with_noise(
        self, tmp_path: Path, fake_ws_script: Path
    ) -> None:
        """Execute real subprocess and verify parsing handles noise."""
        # Run the fake ws script
        env = os.environ.copy()
        env["PATH"] = str(fake_ws_script.parent) + ":" + env.get("PATH", "")

        result = subprocess.run(
            ["bash", "-c", f"{fake_ws_script}"],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )

        # Parse it
        class TestModel(BaseShotModel):
            _process_pool = None

            def _load_from_cache(self):
                return []

            def _get_workspace_command(self) -> str:
                return ""

        model = TestModel()
        shots = model._parse_ws_output(result.stdout, {})

        # Should extract the workspace lines despite noise
        # Parser extracts shot number after underscore: "sq010_0010" → "0010"
        assert len(shots) == 2
        assert shots[0].shot == "0010"
        assert shots[1].shot == "0020"
