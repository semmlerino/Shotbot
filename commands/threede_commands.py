"""3DEqualizer command building utilities."""

from __future__ import annotations


def build_threede_scripts_export(scripts_dir: str) -> str:
    """Return the PYTHON_CUSTOM_SCRIPTS_3DE4 export prefix for 3DE launch commands.

    Prepends scripts_dir to the existing PYTHON_CUSTOM_SCRIPTS_3DE4 variable so
    that Shotbot's hook scripts are discovered by 3DEqualizer on startup.

    Args:
        scripts_dir: Absolute path to the directory containing 3DE hook scripts
            (typically Config.SCRIPTS_DIR).

    Returns:
        Shell fragment of the form
        ``"export PYTHON_CUSTOM_SCRIPTS_3DE4=<scripts_dir>:$PYTHON_CUSTOM_SCRIPTS_3DE4 && "``
        ready to be prepended to a 3DE launch command.

    """
    return (
        f"export PYTHON_CUSTOM_SCRIPTS_3DE4={scripts_dir}:"
        "$PYTHON_CUSTOM_SCRIPTS_3DE4 && "
    )
