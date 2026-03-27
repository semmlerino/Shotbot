"""Tests for Maya command building utilities."""

from __future__ import annotations

import base64

import pytest

from commands.maya_commands import MAYA_BOOTSTRAP_SCRIPT, build_maya_context_command


pytestmark = [pytest.mark.unit]


class TestMayaBootstrapScript:
    """Test MAYA_BOOTSTRAP_SCRIPT content."""

    def test_bootstrap_contains_scene_opened_retry(self) -> None:
        """Context update retries via SceneOpened event when no scene loaded."""
        assert "SceneOpened" in MAYA_BOOTSTRAP_SCRIPT
        assert "scriptJob" in MAYA_BOOTSTRAP_SCRIPT

    def test_bootstrap_contains_context_update(self) -> None:
        """Bootstrap script updates SGTK context from scene path."""
        assert "context_from_path" in MAYA_BOOTSTRAP_SCRIPT
        assert "change_context" in MAYA_BOOTSTRAP_SCRIPT

    def test_bootstrap_uses_background_thread_for_sgtk_wait(self) -> None:
        """SGTK engine polling runs in a background thread."""
        assert "threading.Thread" in MAYA_BOOTSTRAP_SCRIPT
        assert "_shotbot_wait_for_sgtk" in MAYA_BOOTSTRAP_SCRIPT


class TestBuildMayaContextCommand:
    """Test build_maya_context_command function."""

    def test_returns_command_with_env_var_and_file(self) -> None:
        """Command includes SHOTBOT_MAYA_SCRIPT env var and -file flag."""
        result = build_maya_context_command("maya", "/path/to/scene.ma")
        assert "SHOTBOT_MAYA_SCRIPT=" in result
        assert "-file /path/to/scene.ma" in result
        assert result.startswith("export SHOTBOT_MAYA_SCRIPT=")

    def test_script_is_base64_encoded(self) -> None:
        """Bootstrap script is base64-encoded in the command."""
        result = build_maya_context_command("maya", "/path/to/scene.ma")
        # Extract the encoded part
        encoded = result.split("SHOTBOT_MAYA_SCRIPT=")[1].split(" && ")[0]
        decoded = base64.b64decode(encoded).decode()
        assert "_shotbot_update_context" in decoded

    def test_custom_script_overrides_default(self) -> None:
        """Custom context_script replaces the default bootstrap."""
        custom = "print('custom')"
        result = build_maya_context_command(
            "maya", "/path/to/scene.ma", context_script=custom
        )
        encoded = result.split("SHOTBOT_MAYA_SCRIPT=")[1].split(" && ")[0]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == custom
