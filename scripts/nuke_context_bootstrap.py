#!/usr/bin/env python
"""Nuke startup script to update SGTK context from opened file.

This script is executed via: nuke -t nuke_context_bootstrap.py script.nk

It registers a callback that runs after the script loads to update
the SGTK context with Task/Step, triggering full app loading.

The script path to open should be passed via SGTK_FILE_TO_OPEN env var.
"""

import os
import sys
from pathlib import Path


def register_context_callback():
    """Register callback to update SGTK context after script loads."""
    import nuke

    def update_sgtk_context():
        """Update SGTK context from the opened script path."""
        try:
            import sgtk

            engine = sgtk.platform.current_engine()
            if not engine:
                return

            # Skip if we already have a task
            if engine.context.task:
                return

            # Get the script path
            script_path = nuke.root().name()
            if not script_path:
                return

            # Get context from path
            new_context = engine.sgtk.context_from_path(script_path)
            if new_context and new_context.task:
                print(f"[Shotbot] Updating SGTK context to: {new_context}")
                sgtk.platform.change_context(new_context)
                print("[Shotbot] Context updated - full apps should now be available")

        except Exception as e:  # noqa: BLE001
            print(f"[Shotbot] Error updating context: {e}")

    # Register callback for after script load
    nuke.addOnScriptLoad(update_sgtk_context)
    print("[Shotbot] Registered SGTK context update callback")


def main():
    """Main entry point - register callback and open script."""
    import nuke

    # Register our callback first
    register_context_callback()

    # Get the script to open from environment or command line
    script_path = os.environ.get("SGTK_FILE_TO_OPEN")

    if not script_path and len(sys.argv) > 1:
        # Script path might be passed as argument
        script_path = sys.argv[-1]
        if not script_path.endswith((".nk", ".nknc")):
            script_path = None

    if script_path and Path(script_path).exists():
        print(f"[Shotbot] Opening script: {script_path}")
        nuke.scriptOpen(script_path)
    else:
        print("[Shotbot] No script path provided, starting with empty session")


# Only run if executed as main script (via -t flag)
if __name__ == "__main__":
    main()
