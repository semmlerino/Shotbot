#
# 3DE4.script.name:     Shotbot SGTK Context Callback
# 3DE4.script.version:  v1.1
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
import threading
import time


_RETRY_ATTEMPTS = 20
_RETRY_DELAY_SEC = 0.5
_retry_state = {"thread_started": False}


def _get_target_project_path():
    """Return the current project path or Shotbot's requested file path."""
    tde4_module = globals().get("tde4")
    if tde4_module is None or not hasattr(tde4_module, "getProjectPath"):
        return os.environ.get("SGTK_FILE_TO_OPEN")

    try:
        project_path = tde4_module.getProjectPath()
    except RuntimeError:
        project_path = None

    return project_path or os.environ.get("SGTK_FILE_TO_OPEN")


def _contexts_match(current_context, new_context):
    """Return True when the current context already matches the target."""
    current_task = getattr(current_context, "task", None)
    new_task = getattr(new_context, "task", None)
    current_step = getattr(current_context, "step", None)
    new_step = getattr(new_context, "step", None)

    if current_task != new_task:
        return False

    if current_step != new_step:
        return False

    return str(current_context) == str(new_context)


def _attempt_context_update(log_errors=True):
    """Try to promote the current SGTK context from the opened project path.

    Returns:
        "done" when the desired context is already active or was updated.
        "retry" when engine/path state is not ready yet and a retry may help.
        "stop" when the path cannot be resolved to a task context.
    """
    try:
        import sgtk
    except ImportError:
        return "retry"
    except Exception as e:  # noqa: BLE001
        if log_errors:
            print(f"[Shotbot] Note: Could not import sgtk: {e}")
        return "retry"

    engine = sgtk.platform.current_engine()
    if not engine:
        return "retry"

    project_path = _get_target_project_path()
    if not project_path:
        return "retry"

    try:
        new_context = engine.sgtk.context_from_path(project_path)
    except Exception as e:  # noqa: BLE001
        if log_errors:
            print(
                f"[Shotbot] Note: Could not derive SGTK context from {project_path}: {e}"
            )
        return "stop"

    if not new_context or not getattr(new_context, "task", None):
        if log_errors:
            print(
                f"[Shotbot] Note: No task context could be derived from {project_path}"
            )
        return "stop"

    if _contexts_match(engine.context, new_context):
        return "done"

    try:
        print(f"[Shotbot] Updating SGTK context to: {new_context}")
        sgtk.platform.change_context(new_context)
        print("[Shotbot] Context updated - full apps now available")
        return "done"
    except Exception as e:  # noqa: BLE001
        if log_errors:
            print(f"[Shotbot] Note: Could not update SGTK context: {e}")
        return "stop"


def _retry_context_update():
    """Retry context promotion until the engine is ready or attempts are exhausted."""
    try:
        for _ in range(_RETRY_ATTEMPTS):
            result = _attempt_context_update(log_errors=False)
            if result != "retry":
                return
            time.sleep(_RETRY_DELAY_SEC)

        print("[Shotbot] Note: SGTK engine was not ready for 3DE context promotion")
    finally:
        _retry_state["thread_started"] = False


def _start_retry_thread():
    """Start the delayed retry loop once per startup sequence."""
    if _retry_state["thread_started"]:
        return

    _retry_state["thread_started"] = True
    retry_thread = threading.Thread(target=_retry_context_update, daemon=True)
    retry_thread.start()


def _shotbot_update_sgtk_context():
    """Callback to update SGTK context when project opens."""
    result = _attempt_context_update(log_errors=True)
    if result == "retry":
        _start_retry_thread()


def _register_callback():
    """Register the project open callback."""
    # Only register if launched via Shotbot (SGTK_FILE_TO_OPEN is set)
    if os.environ.get("SGTK_FILE_TO_OPEN"):
        tde4.setOpenProjectCallbackFunction("_shotbot_update_sgtk_context")  # noqa: F821 (3DE builtin)
        print("[Shotbot] Registered SGTK context callback for project open")
        _shotbot_update_sgtk_context()


# Register on startup
_register_callback()
