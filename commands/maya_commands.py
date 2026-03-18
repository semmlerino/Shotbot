"""Maya command building utilities."""

from __future__ import annotations

import base64
import shlex


# Maya bootstrap script that upgrades SGTK context from Shot → Shot+Task.
# Uses a background thread to poll for SGTK engine availability with real
# time.sleep() delays (immune to event-loop blocking during plugin loading),
# then dispatches the context update to the main thread.
MAYA_BOOTSTRAP_SCRIPT = """
import maya.cmds
import maya.utils
import traceback
import threading
import time

def _shotbot_wait_for_sgtk():
    for _ in range(50):
        time.sleep(0.5)
        try:
            import sgtk
            if sgtk.platform.current_engine():
                maya.utils.executeDeferred(_shotbot_update_context)
                return
        except ImportError:
            return
    maya.utils.executeDeferred(
        lambda: print("[Shotbot] No SGTK engine available after retries")
    )

def _shotbot_update_context():
    try:
        import sgtk
    except ImportError:
        return

    engine = sgtk.platform.current_engine()
    if not engine:
        return

    scene_path = maya.cmds.file(query=True, sceneName=True)
    if not scene_path:
        # File not yet loaded — hook into Maya's scene-open event
        maya.cmds.scriptJob(
            event=["SceneOpened", _shotbot_update_context],
            runOnce=True,
        )
        return

    if engine.context.task:
        return

    try:
        new_context = engine.sgtk.context_from_path(scene_path)
    except Exception as e:
        print(f"[Shotbot] Error deriving context from path: {e}")
        return

    if not new_context:
        print(f"[Shotbot] Could not derive context from: {scene_path}")
        return

    if not new_context.task:
        print(f"[Shotbot] File path doesn't match task template: {scene_path}")
        return

    try:
        sgtk.platform.change_context(new_context)
        print(f"[Shotbot] Context updated to: {new_context}")
    except Exception as e:
        print(f"[Shotbot] Error changing context: {e}")
        traceback.print_exc()

threading.Thread(target=_shotbot_wait_for_sgtk, daemon=True).start()
"""


def build_maya_context_command(
    base_command: str,
    file_path: str,
    context_script: str | None = None,
) -> str:
    """Build Maya launch command with SGTK context update.

    Uses environment variable approach to avoid complex quote escaping.
    The base64-encoded script is passed via SHOTBOT_MAYA_SCRIPT env var,
    and a static bootstrap command reads and executes it.

    Args:
        base_command: Base maya command (e.g., "maya")
        file_path: Path to Maya file to open
        context_script: Python script to execute after file loads.
                        If None, uses MAYA_BOOTSTRAP_SCRIPT.

    Returns:
        Full command string with env var export and maya invocation

    """
    script_to_run = context_script if context_script is not None else MAYA_BOOTSTRAP_SCRIPT
    encoded = base64.b64encode(script_to_run.encode()).decode()
    # Static bootstrap - reads from env var, no dynamic content in -c argument
    # This avoids the quote escaping nightmare when passing through bash -ilc
    mel_bootstrap = (
        'python("import os,base64;'
        "s=os.environ.get('SHOTBOT_MAYA_SCRIPT','');"
        'exec(base64.b64decode(s).decode()) if s else None")'
    )
    return (
        f"export SHOTBOT_MAYA_SCRIPT={encoded} && "
        f"{base_command} -file {file_path} -c {shlex.quote(mel_bootstrap)}"
    )
