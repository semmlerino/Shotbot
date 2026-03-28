"""Command building and validation for application launching.

This module handles command assembly, validation, and transformation:
- Path validation and shell escaping
- Workspace command wrapping
- Rez environment wrapping
- Environment fixes for specific applications
- Logging redirection
"""

import logging
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from config import Config
else:
    import config

    Config = config.Config


logger = logging.getLogger(__name__)

# Dangerous characters that could enable command injection
DANGEROUS_CHARS: Final[tuple[str, ...]] = (
    ";",
    "&&",
    "||",
    "|",  # Command separators
    ">",
    "<",
    ">>",
    ">&",  # Redirections
    "`",
    "$(",  # Command substitution
    "\n",
    "\r",  # Newlines that could break out
    "${",
    "$((",  # Variable/arithmetic expansion
)


def validate_path(path: str) -> str:
    """Validate and escape a path for safe use in shell commands.

    Args:
        path: Path to validate and escape

    Returns:
        Safely escaped normalized path string using shlex.quote()

    Raises:
        ValueError: If path is empty, invalid, or contains dangerous
                   characters that could allow command injection

    Notes:
        - Normalizes path first (resolves .., ., symlinks)
        - Checks normalized path for command injection characters
        - Uses shlex.quote() for safe shell escaping
        - Path traversal patterns (..) are safe after normalization

    """
    if not path:
        msg = "Path cannot be empty"
        raise ValueError(msg)

    # Normalize path FIRST (resolves .., ., symlinks, makes absolute)
    # Use strict=False to avoid hanging on stale NFS mounts or inaccessible paths.
    # With strict=False, the path is resolved lexically without accessing the filesystem
    # for parts that don't exist, preventing hangs on stale NFS mounts.
    try:
        normalized = str(Path(path).resolve(strict=False))
    except (OSError, RuntimeError) as e:
        msg = f"Invalid path: {e}"
        raise ValueError(msg) from e

    # Check for command injection attempts in NORMALIZED path
    # (After normalization, .. and . are resolved, so we only check
    # for actual command injection characters, not path traversal)
    for char in DANGEROUS_CHARS:
        if char in normalized:
            msg = f"Path contains dangerous character '{char}' that could allow command injection: {normalized[:100]}"
            raise ValueError(msg)

    # Use shlex.quote for safe shell escaping
    return shlex.quote(normalized)


def build_workspace_command(workspace: str, app_command: str) -> str:
    """Build command that switches to workspace and runs app command.

    Args:
        workspace: Workspace path (already validated/escaped)
        app_command: Application command to run (with any env fixes)

    Returns:
        Command string: "ws {workspace} && {app_command}"

    Notes:
        - Workspace path must be pre-validated with validate_path()
        - Command assumes 'ws' function is available in shell

    """
    return f"ws {workspace} && {app_command}"


def wrap_with_rez(command: str, packages: list[str]) -> str:
    """Wrap command with Rez environment.

    Args:
        command: Command to wrap
        packages: List of Rez packages to load

    Returns:
        Rez-wrapped command: 'rez env {packages} -- bash -lc {quoted_command}'

    Notes:
        - Uses bash -lc for shell features inside the resolved Rez context
        - The command should not include studio shell functions like 'ws'
        - Workspace bootstrapping should happen outside the Rez wrapper
        - Uses shlex.quote() to safely escape the command for shell
        - Handles commands containing quotes, spaces, and special characters

    """
    packages_str = " ".join(packages)
    logger.debug(f"Wrapping command with rez packages: {packages_str}")
    # CRITICAL FIX: Use shlex.quote() to properly escape the command
    # This prevents shell injection and handles commands with quotes/special chars
    quoted_command = shlex.quote(command)
    return f"rez env {packages_str} -- bash -lc {quoted_command}"


def apply_nuke_environment_fixes(command: str, config: "type[Config]") -> str:
    """Apply Nuke-specific environment fixes to prevent crashes.

    Args:
        command: Base Nuke command
        config: Application configuration class (not instance)

    Returns:
        Command with environment variable prefixes applied

    Notes:
        Applies the following fixes based on Config:
        - NUKE_SKIP_PROBLEMATIC_PLUGINS: Filter NUKE_PATH at runtime
        - NUKE_OCIO_FALLBACK_CONFIG: Set OCIO fallback config
        - Always disables crash reporting (NUKE_CRASH_REPORTS=0)

    """
    env_fixes: list[str] = []

    # Runtime NUKE_PATH filtering (removes problematic plugins)
    # Uses IFS-based approach to safely handle paths with spaces
    if config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
        env_fixes.append(
            'NUKE_PATH=$(IFS=":"; for p in $NUKE_PATH; do '
            'case "$p" in */problematic_plugins*) ;; *) printf "%s:" "$p" ;; esac; '
            'done | sed "s/:$//")'
        )

    # OCIO fallback configuration (quote path to handle spaces/special chars)
    if config.NUKE_OCIO_FALLBACK_CONFIG:
        quoted_ocio = shlex.quote(config.NUKE_OCIO_FALLBACK_CONFIG)
        env_fixes.append(f"OCIO={quoted_ocio}")

    # Disable crash reports (always applied)
    env_fixes.append("NUKE_CRASH_REPORTS=0")

    if env_fixes:
        env_prefix = " && ".join(env_fixes) + " && "
        logger.debug(f"Applied Nuke environment fixes: {env_fixes}")
        return f"{env_prefix}{command}"

    return command


def get_nuke_fix_summary(config: "type[Config]") -> list[str]:
    """Get human-readable summary of Nuke environment fixes.

    Args:
        config: Application configuration class (not instance)

    Returns:
        List of fix descriptions for user display

    Notes:
        Used for UI notifications about applied environment fixes

    """
    fix_details: list[str] = []

    if config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
        fix_details.append("runtime NUKE_PATH filtering")

    if config.NUKE_OCIO_FALLBACK_CONFIG:
        fix_details.append("OCIO fallback")

    fix_details.append("crash reporting disabled")

    return fix_details


def add_logging(command: str, config: "type[Config] | None" = None, *, app_name: str = "") -> str:
    """Add logging redirection to capture command output.

    Args:
        command: Command to add logging to
        config: Application configuration (optional for backward compatibility)
        app_name: Application name, used to check LAUNCH_LOGGING_TEE_BYPASS_APPS.
                  If the app is in the bypass set, uses >> redirect instead of tee.

    Returns:
        Command with logging redirection and exit code preservation:
        "set -o pipefail; {command} 2>&1 | tee -a {logfile}"
        Or "{command} >> {logfile} 2>&1" if app is in tee bypass set.
        Or original command if logging is disabled or setup fails

    Notes:
        - Uses pipefail to preserve exit code from the command (not tee's exit code)
        - Creates ~/.shotbot/logs/ directory if needed
        - Logs to ~/.shotbot/logs/dispatcher.out
        - Uses tee to capture output while showing in terminal
        - Quotes log file path to handle spaces/special chars
        - Rotates log file if it exceeds configured size
        - Gracefully degrades if logging setup fails

    """
    # Check if logging is enabled (default to True for backward compatibility)
    if config is not None and not config.ENABLE_LAUNCH_LOGGING:
        logger.debug("Launch logging disabled via config")
        return command

    log_dir = Path.home() / ".shotbot" / "logs"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dispatcher.out"

        # Rotate log if it exceeds max size
        max_size_mb = config.LAUNCH_LOG_MAX_SIZE_MB if config else 10
        if max_size_mb > 0 and log_file.exists():
            size_mb = log_file.stat().st_size / (1024 * 1024)
            if size_mb >= max_size_mb:
                # Rotate: rename current to .old, truncate current
                old_log = log_dir / "dispatcher.out.old"
                if old_log.exists():
                    old_log.unlink()
                _ = log_file.rename(old_log)
                logger.info(f"Rotated log file (was {size_mb:.1f}MB)")

        # Quote log file path to handle spaces/special chars
        quoted_log_file = shlex.quote(str(log_file))
        logger.debug(f"Adding logging redirection to: {log_file}")

        if app_name and config is not None and app_name in config.LAUNCH_LOGGING_TEE_BYPASS_APPS:
            return f"{command} >> {quoted_log_file} 2>&1"

        # Use pipefail to preserve exit code from command before pipe
        # Without pipefail, pipeline returns tee's exit code (always 0), hiding app failures
        return f"set -o pipefail; {command} 2>&1 | tee -a {quoted_log_file}"
    except (OSError, PermissionError) as e:
        # Gracefully degrade: return command without tee if setup fails
        logger.warning(
            f"Failed to setup command logging at {log_dir}: {e}. "
            f"Commands will execute without logging."
        )
        return command


def wrap_for_background(command: str) -> str:
    """Wrap command to run in background and exit terminal immediately.

    Args:
        command: Command to wrap

    Returns:
        Command wrapped with backgrounding: "({command}) & disown; exit"

    Notes:
        - Subshell (...) groups the command for clean backgrounding
        - `&` runs the subshell in background
        - `disown` removes it from shell's job table (prevents SIGHUP on exit)
        - `exit` closes the terminal immediately
        - Useful for GUI apps where terminal window is unwanted clutter
        - Output is lost after exit - ensure logging is set up before this

    """
    logger.debug("Wrapping command for background execution")
    return f"({command}) & disown; exit"
