"""RV command building utilities."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def build_rv_command(command: str, sequence_path: str | None) -> str | None:
    """Build the RV playback command with default flags and optional sequence path.

    Appends standard RV playback flags and, when a sequence path is provided,
    validates and appends it to the command.

    Args:
        command: Base RV command string (e.g. "rv").
        sequence_path: Optional path to sequence; validated and appended if present.

    Returns:
        Complete RV command string, or None if the sequence path is invalid.

    """
    from launch.command_builder import validate_path

    command = f"{command} -fps 12 -play -eval 'setPlayMode(2)'"
    if sequence_path:
        try:
            safe_sequence_path = validate_path(sequence_path)
            command = f"{command} {safe_sequence_path}"
        except ValueError:
            logger.error("Cannot launch RV: Invalid sequence path '%s'", sequence_path)
            return None
    return command
