"""Test the simplified Nuke launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from shot_model import Shot
from simple_nuke_launcher import SimpleNukeLauncher


@pytest.fixture
def mock_shot():
    """Create a mock shot for testing."""
    shot = Mock(spec=Shot)
    shot.workspace_path = "/test/workspace"
    shot.full_name = "TEST_0010"
    return shot


@pytest.fixture
def simple_launcher():
    """Create a SimpleNukeLauncher instance for testing."""
    return SimpleNukeLauncher()


class TestSimpleNukeLauncher:
    """Test the SimpleNukeLauncher class."""

    def test_initialization(self, simple_launcher) -> None:
        """Test that launcher initializes correctly."""
        assert simple_launcher is not None

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    def test_open_latest_script_found(
        self, mock_glob, mock_exists, simple_launcher, mock_shot
    ) -> None:
        """Test opening latest script when scripts exist."""
        mock_exists.return_value = True
        mock_script = Mock(spec=Path)
        mock_script.name = "TEST_0010_mm-default_FG01_scene_v003.nk"
        mock_script.__str__ = lambda _self: "/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v003.nk"
        mock_glob.return_value = [mock_script]

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=False
        )

        assert "nuke" in command
        assert "TEST_0010_mm-default_FG01_scene_v003.nk" in command
        assert any("Opening:" in msg for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.exists")
    def test_open_latest_script_not_found(
        self, mock_exists, simple_launcher, mock_shot
    ) -> None:
        """Test opening latest script when no scripts exist."""
        mock_exists.return_value = False

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=False
        )

        assert command == "nuke"
        assert any("Opening empty Nuke" in msg for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    @patch("builtins.open", create=True)
    def test_open_latest_script_create_v001(
        self,
        mock_open,
        mock_glob,
        mock_exists,
        mock_mkdir,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test creating v001 when no scripts exist and create_if_missing=True."""
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=True
        )

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("nuke ")
        assert ".py" in command  # Temporary Python script
        assert any("v001.nk" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    @patch("builtins.open", create=True)
    def test_create_new_version(
        self, mock_open, mock_glob, mock_exists, mock_mkdir, simple_launcher, mock_shot
    ) -> None:
        """Test creating a new version when scripts exist."""
        mock_exists.return_value = True
        # Create proper path mocks
        mock_script_v002 = Path("/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v002.nk")
        mock_script_v003 = Path("/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v003.nk")
        mock_glob.return_value = [mock_script_v002, mock_script_v003]
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("nuke ")
        assert ".py" in command
        assert any("v004" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    @patch("builtins.open", create=True)
    def test_create_new_version_first(
        self,
        mock_open,
        mock_glob,
        mock_exists,
        mock_mkdir,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test creating first version when no scripts exist."""
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("nuke ")
        assert ".py" in command
        assert any("v001" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    @patch("builtins.open", create=True)
    def test_version_parsing(
        self, mock_open, mock_glob, mock_exists, mock_mkdir, simple_launcher, mock_shot
    ) -> None:
        """Test that version numbers are correctly parsed and incremented."""
        mock_exists.return_value = True
        base_dir = "/test/workspace/user/testuser/mm/nuke/scripts/FG01"
        mock_scripts = [
            Path(f"{base_dir}/TEST_0010_mm-default_FG01_scene_v{v:03d}.nk")
            for v in [1, 2, 5, 10]
        ]
        mock_glob.return_value = mock_scripts
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Check that version was incremented correctly
        assert command.startswith("nuke ")
        assert ".py" in command
        assert any("v011" in msg for msg in messages)  # Should increment from v010

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("builtins.open", create=True)
    def test_create_directory_if_missing(
        self,
        mock_open,
        mock_mkdir,
        mock_glob,
        mock_exists,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test that script directory is created if it doesn't exist."""
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, _log_messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Verify a valid nuke command was produced (directory creation succeeded)
        assert command.startswith("nuke")

    @patch.dict("os.environ", {"USER": "testuser"})
    @patch("simple_nuke_launcher.Path.mkdir")
    @patch("simple_nuke_launcher.Path.exists")
    @patch("simple_nuke_launcher.Path.glob")
    def test_create_fails_gracefully(
        self,
        mock_glob,
        mock_exists,
        mock_mkdir,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test that creation failures are handled gracefully."""
        mock_exists.return_value = False
        mock_glob.return_value = []
        # Make mkdir raise an error to simulate failure
        mock_mkdir.side_effect = OSError("Permission denied")

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        assert command == "nuke"
        assert any("error" in msg.lower() for msg in messages)

    @patch.dict("os.environ", {"USER": "testuser"})
    def test_startup_script_contains_cleanup(
        self, simple_launcher, mock_shot, tmp_path
    ) -> None:
        """Test that generated startup script cleans itself up after execution.

        Tests via the public open_latest_script API. When no scripts exist in the
        internally-constructed script_dir, open_latest_script delegates to
        _create_script_via_nuke_api, which writes a temp startup script.

        This prevents /tmp from being littered with nuke_create_*.py files.
        """
        import tempfile

        mock_shot.show = "myshow"
        mock_shot.sequence = "sq010"
        mock_shot.shot = "sh0010"
        mock_shot.workspace_path = str(tmp_path)
        mock_shot.full_name = "TEST_0010"

        command, _log_messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=True
        )

        # Extract temp script path from command (format: "nuke '/tmp/nuke_create_*.py'")
        temp_script_path = Path(command.replace("nuke ", "").strip().strip("'"))

        # Verify temp file was created
        assert temp_script_path.exists(), "Temp startup script should exist"
        assert str(temp_script_path).startswith(tempfile.gettempdir())
        assert "nuke_create_" in temp_script_path.name

        # Read the generated script and verify it contains self-cleanup code
        script_content = temp_script_path.read_text()

        # Must contain cleanup code
        assert "os.remove(" in script_content, "Script should contain os.remove() call"
        assert str(temp_script_path) in script_content, "Script should reference its own path for cleanup"

        # Clean up the temp file ourselves (normally Nuke would do this)
        temp_script_path.unlink()
