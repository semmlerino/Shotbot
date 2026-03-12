#!/usr/bin/env python
"""Trigger SGTK context change based on the currently opened file.

This derives the full context (including Task/Step) from the file path,
which causes SGTK to load the full set of apps (publish, loader, etc.)

Run in Maya Script Editor after file is loaded:
    exec(open(os.environ.get('SHOTBOT_SCRIPTS_DIR', str(Path.home() / 'Python/Shotbot/scripts')) + '/sgtk_context_from_file.py').read())

Or import and call:
    from sgtk_context_from_file import update_context_from_current_file
    update_context_from_current_file()
"""



def update_context_from_current_file():
    """Update SGTK context based on the currently open Maya scene."""
    try:
        import sgtk
        from maya import cmds
    except ImportError as e:
        print(f"Error importing: {e}")
        return False

    engine = sgtk.platform.current_engine()
    if not engine:
        print("No SGTK engine running")
        return False

    # Get current scene path
    scene_path = cmds.file(query=True, sceneName=True)
    if not scene_path:
        print("No scene currently open")
        return False

    print(f"Current scene: {scene_path}")
    print(f"Current context: {engine.context}")
    print(f"Current task: {engine.context.task}")

    # If we already have a task, we're good
    if engine.context.task:
        print("Context already has task - no change needed")
        return True

    # Try to get context from the file path
    try:
        tk = engine.sgtk
        new_context = tk.context_from_path(scene_path)
        print(f"Context from path: {new_context}")
        print(f"New task: {new_context.task}")
        print(f"New step: {new_context.step}")

        if new_context.task:
            print("Changing context...")
            sgtk.platform.change_context(new_context)
            print("Context changed successfully!")
            print(f"New context: {engine.context}")

            # List newly available apps
            print("\nRegistered apps after context change:")
            for name in sorted(engine.apps.keys()):
                print(f"  {name}")

            return True
        print("Could not determine task from file path")
        print("File may not match SGTK templates")
        return False

    except Exception as e:  # noqa: BLE001
        print(f"Error getting context from path: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__" or not hasattr(__builtins__, "__IPYTHON__"):
    # Running as script
    update_context_from_current_file()
