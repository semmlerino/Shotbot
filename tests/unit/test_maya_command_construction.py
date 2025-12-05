"""Tests for Maya command construction in CommandLauncher.

TDD approach: First demonstrate the bug, then fix it.

The bug: When Maya launch commands pass through bash -ilc, the nested
quote escaping breaks. The base64-encoded script is embedded directly
in the -c argument, causing quote escaping issues through multiple shell layers.
"""

from __future__ import annotations

import base64
import re
import shlex

import pytest


# Mark as unit tests
pytestmark = [pytest.mark.unit]


class TestMayaCommandMustSurviveBashParsing:
    """Test that Maya commands must survive bash -ilc parsing.

    This is the core requirement: commands built by CommandLauncher must
    work when passed through ProcessExecutor's bash -ilc wrapper.

    The OLD implementation FAILS this test.
    The NEW implementation should PASS this test.
    """

    def test_command_base64_survives_bash_layer(self) -> None:
        """Command's base64 payload must survive bash -ilc parsing.

        This is what we NEED to work:
        1. Build a command with base64-encoded Python
        2. Wrap it in bash -ilc (as ProcessExecutor does)
        3. Parse what bash receives
        4. Extract and decode the base64
        5. Verify it matches the original

        CURRENTLY FAILS with old implementation (demonstrates the bug).
        Will PASS when we implement the env var approach.
        """
        # Import the real command launcher to test actual implementation
        from command_launcher import CommandLauncher

        # We need to test the launch_with_file method's Maya handling
        # For now, test the helper method if it exists, otherwise use old logic
        launcher = CommandLauncher.__new__(CommandLauncher)

        context_script = "print('hello')"
        file_path = "/shows/test/scene.ma"

        # Check if new helper method exists
        if hasattr(launcher, "_build_maya_context_command"):
            # NEW implementation
            command = launcher._build_maya_context_command("maya", file_path, context_script)
        else:
            # OLD implementation (this is what we're testing against)
            encoded = base64.b64encode(context_script.encode()).decode()
            mel_cmd = f'python "import base64; exec(base64.b64decode(\\"{encoded}\\").decode())"'
            command = f"maya -file {file_path} -c {shlex.quote(mel_cmd)}"

        # Wrap for bash -ilc (as ProcessExecutor does)
        wrapped = f"bash -ilc {shlex.quote(command)}"

        # Parse the wrapped command
        parts = shlex.split(wrapped)
        inner_command = parts[-1]

        # Parse the inner command
        inner_parts = shlex.split(inner_command)

        # Find the base64 content - could be in -c arg OR in env var export
        base64_found = False
        decoded_script = None

        # Check for env var approach (new)
        env_match = re.search(r"SHOTBOT_MAYA_SCRIPT=(\S+)", inner_command)
        if env_match:
            b64_value = env_match.group(1).rstrip(" &")
            try:
                decoded_script = base64.b64decode(b64_value).decode()
                base64_found = True
            except Exception:
                pass

        # Check for -c argument approach (old)
        if not base64_found:
            for i, part in enumerate(inner_parts):
                if part == "-c" and i + 1 < len(inner_parts):
                    c_arg = inner_parts[i + 1]
                    # Look for base64.b64decode("...") or base64.b64decode('...')
                    b64_match = re.search(r'base64\.b64decode\(["\']([^"\']+)["\']', c_arg)
                    if b64_match:
                        try:
                            decoded_script = base64.b64decode(b64_match.group(1)).decode()
                            base64_found = True
                        except Exception:
                            pass
                    break

        # The test requirement: base64 must decode to original script
        assert base64_found, (
            f"Could not find/decode base64 payload in command.\n"
            f"Original: {command}\n"
            f"Wrapped: {wrapped}\n"
            f"Inner parts: {inner_parts}"
        )
        assert decoded_script == context_script, (
            f"Base64 decoded to wrong value.\n"
            f"Expected: {context_script!r}\n"
            f"Got: {decoded_script!r}"
        )


class TestNewMayaCommandConstruction:
    """Tests for the NEW fixed implementation using environment variables.

    The fix: Move the base64-encoded script to an environment variable,
    and use only static code in the -c argument.
    """

    def _build_new_maya_command(self, file_path: str, context_script: str) -> str:
        """Build Maya command using the NEW env var approach."""
        encoded = base64.b64encode(context_script.encode()).decode()
        # Static bootstrap - reads from env var, no dynamic content in -c argument
        mel_bootstrap = (
            'python("import os,base64;'
            "s=os.environ.get('SHOTBOT_MAYA_SCRIPT','');"
            'exec(base64.b64decode(s).decode()) if s else None")'
        )
        return (
            f"export SHOTBOT_MAYA_SCRIPT={encoded} && "
            f"maya -file {file_path} -c {shlex.quote(mel_bootstrap)}"
        )

    def test_new_command_survives_bash_parsing(self) -> None:
        """NEW implementation: Command should survive bash -ilc parsing."""
        context_script = "print('hello')"
        file_path = "/shows/test/scene.ma"

        command = self._build_new_maya_command(file_path, context_script)

        # The new approach should survive shlex.split (simulates bash parsing)
        try:
            parts = shlex.split(command)
            # Should parse without error
            assert len(parts) > 0
        except ValueError as e:
            pytest.fail(f"New command failed shlex parsing: {e}")

    def test_new_command_has_static_c_argument(self) -> None:
        """NEW implementation: The -c argument should be static (no base64 payload)."""
        context_script = "print('hello')"
        encoded = base64.b64encode(context_script.encode()).decode()

        command = self._build_new_maya_command("/path/file.ma", context_script)

        # Extract the -c argument
        c_index = command.find(" -c ")
        assert c_index != -1
        c_arg = command[c_index + 4:]

        # The base64 payload should NOT be in the -c argument
        # It should only be in the env var export
        assert encoded not in c_arg, "Base64 should not be in -c argument"

        # But it should be in the env var export
        assert f"SHOTBOT_MAYA_SCRIPT={encoded}" in command

    def test_new_command_env_var_contains_valid_base64(self) -> None:
        """NEW implementation: SHOTBOT_MAYA_SCRIPT should contain valid base64."""
        context_script = "print('hello world')"

        command = self._build_new_maya_command("/path/file.ma", context_script)

        # Extract the env var value
        match = re.search(r"export SHOTBOT_MAYA_SCRIPT=(\S+)", command)
        assert match is not None

        b64_value = match.group(1).rstrip(" &")
        decoded = base64.b64decode(b64_value).decode()

        assert decoded == context_script

    def test_new_command_bootstrap_reads_env_var(self) -> None:
        """NEW implementation: Bootstrap should read SHOTBOT_MAYA_SCRIPT."""
        command = self._build_new_maya_command("/path/file.ma", "x=1")

        # The bootstrap code in -c should reference the env var
        assert "SHOTBOT_MAYA_SCRIPT" in command.split(" -c ")[1]
        assert "os.environ.get" in command
