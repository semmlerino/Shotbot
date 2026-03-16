"""Test the unified Nuke launch handler."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nuke.launch_handler import NukeLaunchHandler


@pytest.fixture
def nuke_handler():
    """Create a NukeLaunchHandler instance for testing."""
    return NukeLaunchHandler()


class TestNukeLaunchHandler:
    """Test the NukeLaunchHandler class."""

    def test_get_environment_fixes_disabled(self, nuke_handler) -> None:
        """Test environment fixes when disabled."""
        with patch("nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", False):
            fixes = nuke_handler.get_environment_fixes()
            assert fixes == ""

    def test_get_environment_fixes_with_problematic_plugins(self, nuke_handler) -> None:
        """Test environment fixes with problematic plugin paths."""
        with patch(
            "nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", True
        ), patch(
            "nuke.launch_handler.Config.NUKE_SKIP_PROBLEMATIC_PLUGINS", True
        ), patch(
            "nuke.launch_handler.Config.NUKE_PROBLEMATIC_PLUGIN_PATHS",
            ["/bad/plugin1", "/bad/plugin2"],
        ):
            fixes = nuke_handler.get_environment_fixes()

            assert "FILTERED_NUKE_PATH" in fixes
            assert "grep -v" in fixes
            assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

    def test_get_environment_fixes_with_ocio_fallback(self, nuke_handler) -> None:
        """Test environment fixes with OCIO fallback config."""
        with patch(
            "nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", True
        ), patch(
            "nuke.launch_handler.Config.NUKE_OCIO_FALLBACK_CONFIG",
            "/test/ocio/config.ocio",
        ), patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = True
            fixes = nuke_handler.get_environment_fixes()

            assert 'export OCIO="/test/ocio/config.ocio"' in fixes
            assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

