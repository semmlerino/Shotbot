"""Nuke init.py - Loaded via NUKE_PATH to update SGTK context.

This file is loaded by Nuke on startup when NUKE_PATH includes its directory.
It registers an onScriptLoad callback that updates SGTK context with Task/Step,
which triggers full app loading (publish, loader, etc.)
"""

import os


def _shotbot_update_sgtk_context():
    """Update SGTK context from the opened script path."""
    try:
        import sgtk

        import nuke

        engine = sgtk.platform.current_engine()
        if not engine:
            return

        # Skip if we already have a task
        if engine.context.task:
            return

        # Get the script path
        script_path = nuke.root().name() if nuke.root() else None
        if not script_path:
            return

        # Get context from path
        new_context = engine.sgtk.context_from_path(script_path)
        if new_context and new_context.task:
            print(f"[Shotbot] Updating SGTK context to include Task: {new_context.task}")
            sgtk.platform.change_context(new_context)
            print("[Shotbot] Context updated - full apps now available")

    except Exception as e:  # noqa: BLE001
        # Silently fail - don't break Nuke startup
        print(f"[Shotbot] Note: Could not update SGTK context: {e}")


# Only register callback if launched via Shotbot (SGTK_FILE_TO_OPEN is set)
if os.environ.get("SGTK_FILE_TO_OPEN"):
    try:
        import nuke
        nuke.addOnScriptLoad(_shotbot_update_sgtk_context)
        print("[Shotbot] Registered SGTK context update callback")
    except ImportError:
        pass  # Not running in Nuke
