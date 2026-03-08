#
# 3DE4.script.name:     Shotbot SGTK Context Callback
# 3DE4.script.version:  v1.0
# 3DE4.script.startup:  true
# 3DE4.script.hide:     true
# 3DE4.script.comment:  Registers callback to update SGTK context when project opens
#

"""Shotbot SGTK Context Callback for 3DEqualizer.

This startup script registers a callback that runs when a project is opened.
It updates the SGTK context with Task/Step from the project path, which
triggers full app loading (publish, loader, etc.)

Installation:
    Copy to ~/.3dequalizer/py_scripts/ or add to PYTHON_CUSTOM_SCRIPTS_3DE4 path
"""

import os


def _shotbot_update_sgtk_context():
    """Callback to update SGTK context when project opens."""
    try:
        import sgtk

        engine = sgtk.platform.current_engine()
        if not engine:
            return

        # Skip if we already have a task
        if engine.context.task:
            return

        # Get the project path
        project_path = tde4.getProjectPath()  # noqa: F821 (3DE builtin)
        if not project_path:
            return

        # Get context from path
        new_context = engine.sgtk.context_from_path(project_path)
        if new_context and new_context.task:
            print(f"[Shotbot] Updating SGTK context to include Task: {new_context.task}")
            engine.change_context(new_context)
            print("[Shotbot] Context updated - full apps now available")

    except Exception as e:  # noqa: BLE001
        # Silently fail - don't break 3DE
        print(f"[Shotbot] Note: Could not update SGTK context: {e}")


def _register_callback():
    """Register the project open callback."""
    # Only register if launched via Shotbot (SGTK_FILE_TO_OPEN is set)
    if os.environ.get("SGTK_FILE_TO_OPEN"):
        tde4.setOpenProjectCallbackFunction("_shotbot_update_sgtk_context")  # noqa: F821 (3DE builtin)
        print("[Shotbot] Registered SGTK context callback for project open")


# Register on startup
_register_callback()
