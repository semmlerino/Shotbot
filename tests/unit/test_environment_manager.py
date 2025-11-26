"""Tests for EnvironmentManager component.

This test suite provides comprehensive coverage of environment detection:
- Rez availability checking
- Rez package mapping
- Terminal emulator detection
- Cache management
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from launch.environment_manager import EnvironmentManager


@pytest.fixture
def env_manager() -> EnvironmentManager:
    """Create a fresh EnvironmentManager instance."""
    return EnvironmentManager()


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object with default settings."""
    config = MagicMock(spec=Config)
    config.USE_REZ_ENVIRONMENT = True
    config.REZ_AUTO_DETECT = True
    config.REZ_FORCE_WRAP = False
    config.REZ_NUKE_PACKAGES = ["nuke", "nuke-plugins"]
    config.REZ_MAYA_PACKAGES = ["maya", "maya-plugins"]
    config.REZ_3DE_PACKAGES = ["3de"]
    return config


class TestRezAvailability:
    """Tests for Rez availability detection."""

    def test_rez_disabled_in_config(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test that Rez is not used when disabled in config."""
        mock_config.USE_REZ_ENVIRONMENT = False

        assert env_manager.is_rez_available(mock_config) is False

    def test_rez_skipped_when_already_in_rez_environment(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test that rez wrapping is skipped when REZ_USED is set.

        When REZ_USED is set, we're already in a rez environment.
        Returning False avoids double-wrapping commands.
        """
        mock_config.REZ_AUTO_DETECT = True
        mock_config.REZ_FORCE_WRAP = False

        with patch.dict(os.environ, {"REZ_USED": "1"}):
            assert env_manager.is_rez_available(mock_config) is False

    @patch("shutil.which")
    def test_rez_force_wrap_overrides_rez_used(
        self,
        mock_which: MagicMock,
        env_manager: EnvironmentManager,
        mock_config: MagicMock,
    ) -> None:
        """Test that REZ_FORCE_WRAP=True allows wrapping even when REZ_USED is set.

        Some base rez environments need additional app packages added.
        REZ_FORCE_WRAP=True bypasses the REZ_USED check to allow this.
        """
        mock_config.REZ_AUTO_DETECT = True
        mock_config.REZ_FORCE_WRAP = True
        mock_which.return_value = "/usr/bin/rez"

        with patch.dict(os.environ, {"REZ_USED": "1"}):
            # With REZ_FORCE_WRAP=True, should proceed to check rez command
            assert env_manager.is_rez_available(mock_config) is True
            mock_which.assert_called_once_with("rez")

    def test_rez_not_detected_when_auto_detect_disabled(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test that REZ_USED is ignored when REZ_AUTO_DETECT is False."""
        mock_config.REZ_AUTO_DETECT = False

        with patch.dict(os.environ, {"REZ_USED": "1"}), patch(
            "shutil.which", return_value=None
        ):
            # Should not detect via environment, should check command
            assert env_manager.is_rez_available(mock_config) is False

    @patch("shutil.which")
    def test_rez_available_via_command(
        self,
        mock_which: MagicMock,
        env_manager: EnvironmentManager,
        mock_config: MagicMock,
    ) -> None:
        """Test Rez detection via 'rez' command availability."""
        mock_config.REZ_AUTO_DETECT = False
        mock_which.return_value = "/usr/bin/rez"

        with patch.dict(os.environ, {}, clear=True):
            assert env_manager.is_rez_available(mock_config) is True
            mock_which.assert_called_once_with("rez")

    @patch("shutil.which")
    def test_rez_not_available_via_command(
        self,
        mock_which: MagicMock,
        env_manager: EnvironmentManager,
        mock_config: MagicMock,
    ) -> None:
        """Test Rez not detected when command not found."""
        mock_config.REZ_AUTO_DETECT = False
        mock_which.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            assert env_manager.is_rez_available(mock_config) is False
            mock_which.assert_called_once_with("rez")

    @patch("shutil.which")
    def test_rez_availability_caching(
        self,
        mock_which: MagicMock,
        env_manager: EnvironmentManager,
        mock_config: MagicMock,
    ) -> None:
        """Test that Rez availability is cached after first check."""
        mock_config.REZ_AUTO_DETECT = False
        mock_which.return_value = "/usr/bin/rez"

        with patch.dict(os.environ, {}, clear=True):
            # First call - should check
            result1 = env_manager.is_rez_available(mock_config)
            assert result1 is True
            assert mock_which.call_count == 1

            # Second call - should use cache
            result2 = env_manager.is_rez_available(mock_config)
            assert result2 is True
            assert mock_which.call_count == 1  # Not called again

    def test_cache_reset_clears_rez_availability(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test that reset_cache clears Rez availability cache."""
        mock_config.REZ_AUTO_DETECT = False

        with patch("shutil.which", return_value="/usr/bin/rez"), patch.dict(
            os.environ, {}, clear=True
        ):
            # Cache result
            env_manager.is_rez_available(mock_config)
            assert env_manager._rez_available_cache is True

            # Reset cache
            env_manager.reset_cache()
            assert env_manager._rez_available_cache is None


class TestRezPackages:
    """Tests for Rez package mapping."""

    def test_nuke_packages(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test Rez packages for Nuke."""
        packages = env_manager.get_rez_packages("nuke", mock_config)
        assert packages == ["nuke", "nuke-plugins"]

    def test_maya_packages(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test Rez packages for Maya."""
        packages = env_manager.get_rez_packages("maya", mock_config)
        assert packages == ["maya", "maya-plugins"]

    def test_3de_packages(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test Rez packages for 3DEqualizer."""
        packages = env_manager.get_rez_packages("3de", mock_config)
        assert packages == ["3de"]

    def test_unknown_app_returns_empty_list(
        self, env_manager: EnvironmentManager, mock_config: MagicMock
    ) -> None:
        """Test that unknown apps return empty package list."""
        packages = env_manager.get_rez_packages("unknown_app", mock_config)
        assert packages == []


class TestTerminalDetection:
    """Tests for terminal emulator detection."""

    @patch("shutil.which")
    def test_gnome_terminal_detected(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test gnome-terminal detection (highest preference)."""
        mock_which.side_effect = lambda cmd: (
            "/usr/bin/gnome-terminal" if cmd == "gnome-terminal" else None
        )

        terminal = env_manager.detect_terminal()
        assert terminal == "gnome-terminal"

    @patch("shutil.which")
    def test_konsole_detected(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test konsole detection (second preference)."""
        mock_which.side_effect = lambda cmd: (
            "/usr/bin/konsole" if cmd == "konsole" else None
        )

        terminal = env_manager.detect_terminal()
        assert terminal == "konsole"

    @patch("shutil.which")
    def test_xterm_detected(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test xterm detection (third preference)."""
        mock_which.side_effect = lambda cmd: "/usr/bin/xterm" if cmd == "xterm" else None

        terminal = env_manager.detect_terminal()
        assert terminal == "xterm"

    @patch("shutil.which")
    def test_x_terminal_emulator_detected(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test x-terminal-emulator detection (lowest preference)."""
        mock_which.side_effect = lambda cmd: (
            "/usr/bin/x-terminal-emulator" if cmd == "x-terminal-emulator" else None
        )

        terminal = env_manager.detect_terminal()
        assert terminal == "x-terminal-emulator"

    @patch("shutil.which")
    def test_preference_order(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test that terminals are checked in preference order."""
        # All terminals available - should return gnome-terminal
        mock_which.return_value = "/usr/bin/some-terminal"

        terminal = env_manager.detect_terminal()
        assert terminal == "gnome-terminal"

    @patch("shutil.which")
    def test_no_terminal_found(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test behavior when no terminal is found."""
        mock_which.return_value = None

        terminal = env_manager.detect_terminal()
        assert terminal is None

    @patch("shutil.which")
    def test_terminal_detection_caching(
        self, mock_which: MagicMock, env_manager: EnvironmentManager
    ) -> None:
        """Test that terminal detection is cached after first check."""
        mock_which.side_effect = lambda cmd: (
            "/usr/bin/gnome-terminal" if cmd == "gnome-terminal" else None
        )

        # First call - should check
        terminal1 = env_manager.detect_terminal()
        assert terminal1 == "gnome-terminal"
        initial_call_count = mock_which.call_count

        # Second call - should use cache
        terminal2 = env_manager.detect_terminal()
        assert terminal2 == "gnome-terminal"
        assert mock_which.call_count == initial_call_count  # Not called again

    def test_cache_reset_clears_terminal_detection(
        self, env_manager: EnvironmentManager
    ) -> None:
        """Test that reset_cache clears terminal detection cache."""
        with patch("shutil.which", return_value="/usr/bin/gnome-terminal"):
            # Cache result
            env_manager.detect_terminal()
            assert env_manager._available_terminal_cache == "gnome-terminal"

            # Reset cache
            env_manager.reset_cache()
            assert env_manager._available_terminal_cache is None


class TestCacheManagement:
    """Tests for cache management functionality."""

    @patch("shutil.which")
    def test_reset_cache_clears_all_caches(
        self,
        mock_which: MagicMock,
        env_manager: EnvironmentManager,
        mock_config: MagicMock,
    ) -> None:
        """Test that reset_cache clears all cached values."""
        mock_config.REZ_AUTO_DETECT = False
        mock_which.return_value = "/usr/bin/rez"

        with patch.dict(os.environ, {}, clear=True):
            # Cache Rez availability
            env_manager.is_rez_available(mock_config)
            assert env_manager._rez_available_cache is not None

        mock_which.return_value = "/usr/bin/gnome-terminal"
        # Cache terminal detection
        env_manager.detect_terminal()
        assert env_manager._available_terminal_cache is not None

        # Reset all caches
        env_manager.reset_cache()
        assert env_manager._rez_available_cache is None
        assert env_manager._available_terminal_cache is None

    def test_independent_cache_instances(self) -> None:
        """Test that separate instances have independent caches."""
        manager1 = EnvironmentManager()
        manager2 = EnvironmentManager()

        with patch("shutil.which", return_value="/usr/bin/gnome-terminal"):
            # Cache in manager1
            manager1.detect_terminal()
            assert manager1._available_terminal_cache == "gnome-terminal"

            # manager2 should have empty cache
            assert manager2._available_terminal_cache is None
