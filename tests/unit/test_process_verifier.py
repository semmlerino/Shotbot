"""Unit tests for ProcessVerifier."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import psutil
import pytest

from launch.process_verifier import ProcessVerifier, ProcessVerificationError


pytestmark = [pytest.mark.unit]


class TestProcessVerifier:
    """Test process verification functionality."""

    @pytest.fixture
    def mock_logger(self) -> Mock:
        """Create a mock logger."""
        logger = Mock()
        logger.debug = Mock()
        logger.info = Mock()
        logger.warning = Mock()
        return logger

    @pytest.fixture
    def verifier(self, mock_logger: Mock) -> ProcessVerifier:
        """Create a ProcessVerifier instance with mocked logger."""
        with patch("pathlib.Path.mkdir"):  # Don't actually create directories
            return ProcessVerifier(mock_logger)

    def test_initialization(self, mock_logger: Mock) -> None:
        """Test ProcessVerifier initialization."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            verifier = ProcessVerifier(mock_logger)

            assert verifier.logger == mock_logger
            # Should try to create PID directory
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_is_gui_app_detects_known_apps(self, verifier: ProcessVerifier) -> None:
        """Test GUI app detection."""
        # Known GUI apps
        assert verifier._is_gui_app("nuke -t test.nk")
        assert verifier._is_gui_app("3de -open scene.3de")
        assert verifier._is_gui_app("maya test.ma")
        assert verifier._is_gui_app("NUKE -t test.nk")  # Case insensitive

        # Non-GUI commands
        assert not verifier._is_gui_app("ls -la")
        assert not verifier._is_gui_app("echo hello")
        assert not verifier._is_gui_app("python script.py")

    def test_extract_app_name(self, verifier: ProcessVerifier) -> None:
        """Test app name extraction."""
        assert verifier._extract_app_name("nuke -t test.nk") == "nuke"
        assert verifier._extract_app_name("3de -open scene.3de") == "3de"
        assert verifier._extract_app_name("maya test.ma") == "maya"
        assert verifier._extract_app_name("NUKE -t test.nk") == "nuke"  # Case insensitive
        assert verifier._extract_app_name("ls -la") is None

    def test_non_gui_command_skips_verification(self, verifier: ProcessVerifier) -> None:
        """Test that non-GUI commands skip verification."""
        success, message = verifier.wait_for_process("ls -la")

        assert success is True
        assert "Non-GUI command" in message

    def test_unknown_app_skips_verification(self, verifier: ProcessVerifier) -> None:
        """Test that unknown app names skip verification."""
        success, message = verifier.wait_for_process("unknown_command --arg")

        assert success is True
        # Unknown commands are treated as non-GUI
        assert "Non-GUI command" in message

    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_wait_for_process_timeout(
        self, mock_exists: MagicMock, mock_glob: MagicMock, verifier: ProcessVerifier
    ) -> None:
        """Test verification timeout when PID file not found."""
        # Setup: PID directory exists but no matching PID files
        mock_exists.return_value = True
        mock_glob.return_value = []

        # Use very short timeout for test
        success, message = verifier.wait_for_process("nuke test.nk", timeout_sec=0.1)

        assert success is False
        assert "PID file not found" in message

    @patch("psutil.pid_exists")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_wait_for_process_success(
        self,
        mock_exists: MagicMock,
        mock_glob: MagicMock,
        mock_read_text: MagicMock,
        mock_pid_exists: MagicMock,
        verifier: ProcessVerifier,
    ) -> None:
        """Test successful process verification."""
        # Setup: PID file exists and process is running
        mock_exists.return_value = True

        # Create mock PID file
        mock_pid_file = MagicMock()
        mock_pid_file.stat.return_value.st_mtime = time.time()
        mock_pid_file.read_text.return_value = "12345"
        mock_glob.return_value = [mock_pid_file]
        mock_pid_exists.return_value = True

        success, message = verifier.wait_for_process("nuke test.nk")

        assert success is True
        assert "Process verified" in message
        assert "PID: 12345" in message

    @patch("psutil.pid_exists")
    @patch("pathlib.Path.read_text")
    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_wait_for_process_crashed_immediately(
        self,
        mock_exists: MagicMock,
        mock_glob: MagicMock,
        mock_read_text: MagicMock,
        mock_pid_exists: MagicMock,
        verifier: ProcessVerifier,
    ) -> None:
        """Test detection of immediately crashed process."""
        # Setup: PID file exists but process is not running
        mock_exists.return_value = True

        # Create mock PID file
        mock_pid_file = MagicMock()
        mock_pid_file.stat.return_value.st_mtime = time.time()
        mock_glob.return_value = [mock_pid_file]
        mock_read_text.return_value = "12345"
        mock_pid_exists.return_value = False  # Process not found

        success, message = verifier.wait_for_process("nuke test.nk")

        assert success is False
        assert "not found" in message

    @patch("pathlib.Path.unlink")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.glob")
    @patch("pathlib.Path.exists")
    def test_cleanup_old_pid_files(
        self,
        mock_exists: MagicMock,
        mock_glob: MagicMock,
        mock_stat: MagicMock,
        mock_unlink: MagicMock,
    ) -> None:
        """Test cleanup of old PID files."""
        # Setup: Directory exists with old PID files
        mock_exists.return_value = True

        # Create mock old PID file (25 hours old)
        old_pid_file = MagicMock()
        old_pid_file.stat.return_value.st_mtime = time.time() - (25 * 3600)

        # Create mock recent PID file (1 hour old)
        recent_pid_file = MagicMock()
        recent_pid_file.stat.return_value.st_mtime = time.time() - 3600

        mock_glob.return_value = [old_pid_file, recent_pid_file]

        # Run cleanup (24 hour threshold)
        ProcessVerifier.cleanup_old_pid_files(max_age_hours=24)

        # Old file should be deleted, recent file should not
        old_pid_file.unlink.assert_called_once()
        recent_pid_file.unlink.assert_not_called()
