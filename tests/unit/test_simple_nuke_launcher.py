"""Test the simplified Nuke launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from nuke.simple_launcher import SimpleNukeLauncher
from type_definitions import Shot


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

    def test_open_latest_script_found(
        self, mocker, simple_launcher, mock_shot
    ) -> None:
        """Test opening latest script when scripts exist."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mock_exists.return_value = True
        mock_script = Mock(spec=Path)
        mock_script.name = "TEST_0010_mm-default_FG01_scene_v003.nk"
        mock_script.__str__ = lambda _self: (
            "/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v003.nk"
        )
        mock_glob.return_value = [mock_script]

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=False
        )

        assert "NUKE_PATH" in command
        assert "SGTK_FILE_TO_OPEN=" in command
        assert "nuke" in command
        assert "TEST_0010_mm-default_FG01_scene_v003.nk" in command
        assert any("Opening:" in msg for msg in messages)

    def test_open_latest_script_not_found(
        self, mocker, simple_launcher, mock_shot
    ) -> None:
        """Test opening latest script when no scripts exist."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_exists.return_value = False

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=False
        )

        assert command == "nuke"
        assert any("Opening empty Nuke" in msg for msg in messages)

    def test_open_latest_script_create_v001(
        self,
        mocker,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test creating v001 when no scripts exist and create_if_missing=True."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mocker.patch("nuke.simple_launcher.Path.mkdir")
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mock_open = mocker.patch("builtins.open", create=True)
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.open_latest_script(
            mock_shot, "FG01", create_if_missing=True
        )

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("export NUKE_PATH=")
        assert " && nuke --script " in command
        assert ".py" in command  # Temporary Python script
        assert any("v001.nk" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    def test_create_new_version(
        self, mocker, simple_launcher, mock_shot
    ) -> None:
        """Test creating a new version when scripts exist."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mocker.patch("nuke.simple_launcher.Path.mkdir")
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mock_open = mocker.patch("builtins.open", create=True)
        mock_exists.return_value = True
        # Create proper path mocks
        mock_script_v002 = Path(
            "/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v002.nk"
        )
        mock_script_v003 = Path(
            "/test/workspace/user/testuser/mm/nuke/scripts/FG01/TEST_0010_mm-default_FG01_scene_v003.nk"
        )
        mock_glob.return_value = [mock_script_v002, mock_script_v003]
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("export NUKE_PATH=")
        assert " && nuke --script " in command
        assert ".py" in command
        assert any("v004" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    def test_create_new_version_first(
        self,
        mocker,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test creating first version when no scripts exist."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mocker.patch("nuke.simple_launcher.Path.mkdir")
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mock_open = mocker.patch("builtins.open", create=True)
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Now uses Nuke's API via startup script (no -t flag, keeps GUI open)
        assert command.startswith("export NUKE_PATH=")
        assert " && nuke --script " in command
        assert ".py" in command
        assert any("v001" in msg for msg in messages)
        assert any("onCreate hooks" in msg for msg in messages)

    def test_create_directory_if_missing(
        self,
        mocker,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test that script directory is created if it doesn't exist."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mocker.patch("nuke.simple_launcher.Path.mkdir")
        mock_open = mocker.patch("builtins.open", create=True)
        mock_exists.return_value = False
        mock_glob.return_value = []
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        command, _log_messages = simple_launcher.create_new_version(mock_shot, "FG01")

        # Verify a valid nuke command was produced (directory creation succeeded)
        assert command.startswith("export NUKE_PATH=")

    def test_create_fails_gracefully(
        self,
        mocker,
        simple_launcher,
        mock_shot,
    ) -> None:
        """Test that creation failures are handled gracefully."""
        mocker.patch.dict("os.environ", {"USER": "testuser"})
        mock_glob = mocker.patch("nuke.simple_launcher.Path.glob")
        mock_exists = mocker.patch("nuke.simple_launcher.Path.exists")
        mock_mkdir = mocker.patch("nuke.simple_launcher.Path.mkdir")
        mock_exists.return_value = False
        mock_glob.return_value = []
        # Make mkdir raise an error to simulate failure
        mock_mkdir.side_effect = OSError("Permission denied")

        command, messages = simple_launcher.create_new_version(mock_shot, "FG01")

        assert command == "nuke"
        assert any("error" in msg.lower() for msg in messages)

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

        # Extract temp script path from command
        temp_script_path = Path(
            command.split(" && nuke --script ", 1)[1].strip().strip("'")
        )

        # Verify temp file was created
        assert temp_script_path.exists(), "Temp startup script should exist"
        assert str(temp_script_path).startswith(tempfile.gettempdir())
        assert "nuke_create_" in temp_script_path.name

        # Read the generated script and verify it contains self-cleanup code
        script_content = temp_script_path.read_text()

        # Must contain cleanup code
        assert "os.remove(" in script_content, "Script should contain os.remove() call"
        assert str(temp_script_path) in script_content, (
            "Script should reference its own path for cleanup"
        )
        assert "context_from_path(script_path)" in script_content
        assert "sgtk.platform.change_context(new_context)" in script_content

        # Clean up the temp file ourselves (normally Nuke would do this)
        temp_script_path.unlink()


class TestNukeLaunchHandler:
    """Test the NukeLaunchHandler class."""

    @pytest.fixture
    def nuke_handler(self) -> NukeLaunchHandler:  # noqa: F821
        from nuke.launch_handler import NukeLaunchHandler

        return NukeLaunchHandler()

    def test_get_environment_fixes_disabled(self, mocker, nuke_handler) -> None:
        """Test environment fixes when disabled."""
        mocker.patch("nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", False)
        fixes = nuke_handler.get_environment_fixes()
        assert fixes == ""

    def test_get_environment_fixes_with_problematic_plugins(self, mocker, nuke_handler) -> None:
        """Test environment fixes with problematic plugin paths."""
        mocker.patch("nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", True)
        mocker.patch("nuke.launch_handler.Config.NUKE_SKIP_PROBLEMATIC_PLUGINS", True)
        mocker.patch(
            "nuke.launch_handler.Config.NUKE_PROBLEMATIC_PLUGIN_PATHS",
            ["/bad/plugin1", "/bad/plugin2"],
        )
        fixes = nuke_handler.get_environment_fixes()

        assert "FILTERED_NUKE_PATH" in fixes
        assert "grep -v" in fixes
        assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes

    def test_get_environment_fixes_with_ocio_fallback(self, mocker, nuke_handler) -> None:
        """Test environment fixes with OCIO fallback config."""
        mocker.patch("nuke.launch_handler.Config.NUKE_FIX_OCIO_CRASH", True)
        mocker.patch(
            "nuke.launch_handler.Config.NUKE_OCIO_FALLBACK_CONFIG",
            "/test/ocio/config.ocio",
        )
        mock_exists = mocker.patch("pathlib.Path.exists")
        mock_exists.return_value = True
        fixes = nuke_handler.get_environment_fixes()

        assert 'export OCIO="/test/ocio/config.ocio"' in fixes
        assert "NUKE_DISABLE_CRASH_REPORTING=1" in fixes
