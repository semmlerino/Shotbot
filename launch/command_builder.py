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


class CommandBuilder:
    """Builds and validates shell commands for application launching.

    This class provides composable functions for constructing safe,
    properly escaped shell commands with various wrappers and transformations.
    All methods are stateless for maximum testability.
    """

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
        "$((", # Variable/arithmetic expansion
    )

    @staticmethod
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
            raise ValueError("Path cannot be empty")

        # Normalize path FIRST (resolves .., ., symlinks, makes absolute)
        # Use strict=False to avoid hanging on stale NFS mounts or inaccessible paths.
        # With strict=False, the path is resolved lexically without accessing the filesystem
        # for parts that don't exist, preventing hangs on stale NFS mounts.
        try:
            normalized = str(Path(path).resolve(strict=False))
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Invalid path: {e}") from e

        # Check for command injection attempts in NORMALIZED path
        # (After normalization, .. and . are resolved, so we only check
        # for actual command injection characters, not path traversal)
        for char in CommandBuilder.DANGEROUS_CHARS:
            if char in normalized:
                raise ValueError(
                    f"Path contains dangerous character '{char}' that could allow command injection: {normalized[:100]}"
                )

        # Use shlex.quote for safe shell escaping
        return shlex.quote(normalized)

    @staticmethod
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

    @staticmethod
    def wrap_with_rez(command: str, packages: list[str]) -> str:
        """Wrap command with Rez environment.

        Args:
            command: Command to wrap
            packages: List of Rez packages to load

        Returns:
            Rez-wrapped command: 'rez env {packages} -- bash -ilc {quoted_command}'

        Notes:
            - Uses bash -ilc (interactive login shell) to ensure shell functions are available
            - Shell functions like 'ws' are defined in .bashrc, which requires -i flag
            - Without -i, bash -lc may not source .bashrc (depends on .bash_profile setup)
            - The minor startup overhead (~50ms) is worth the reliability gain
            - Uses shlex.quote() to safely escape the command for shell
            - Handles commands containing quotes, spaces, and special characters
        """
        packages_str = " ".join(packages)
        logger.debug(f"Wrapping command with rez packages: {packages_str}")
        # CRITICAL FIX: Use shlex.quote() to properly escape the command
        # This prevents shell injection and handles commands with quotes/special chars
        quoted_command = shlex.quote(command)
        return f"rez env {packages_str} -- bash -ilc {quoted_command}"

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def add_logging(command: str, config: "type[Config] | None" = None) -> str:
        """Add logging redirection to capture command output.

        Args:
            command: Command to add logging to
            config: Application configuration (optional for backward compatibility)

        Returns:
            Command with logging redirection: "{command} 2>&1 | tee -a {logfile}"
            Or original command if logging is disabled or setup fails

        Notes:
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
            return f"{command} 2>&1 | tee -a {quoted_log_file}"
        except (OSError, PermissionError) as e:
            # Gracefully degrade: return command without tee if setup fails
            logger.warning(
                f"Failed to setup command logging at {log_dir}: {e}. "
                f"Commands will execute without logging."
            )
            return command

    @staticmethod
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

    @staticmethod
    def build_full_command(
        app_command: str,
        workspace: str | None,
        config: "type[Config]",
        rez_packages: list[str] | None = None,
        apply_nuke_fixes: bool = False,
        add_logging_redirect: bool = True,
        run_in_background: bool = False,
    ) -> str:
        """Build complete command with all transformations applied.

        This is a convenience method that applies all transformations in order:
        1. Nuke environment fixes (if requested)
        2. Workspace wrapping (if workspace provided)
        3. Rez environment wrapping (if packages provided)
        4. Logging redirection (if requested)
        5. Background wrapping (if requested) - must be last

        Args:
            app_command: Base application command
            workspace: Optional workspace path (already validated)
            config: Application configuration class (not instance)
            rez_packages: Optional Rez packages to load
            apply_nuke_fixes: Whether to apply Nuke environment fixes
            add_logging_redirect: Whether to add logging redirection
            run_in_background: Whether to background app and exit terminal

        Returns:
            Fully assembled command ready for execution

        Notes:
            - Transformations are applied in the order listed above
            - Workspace path must be pre-validated with validate_path()
            - Order matters: workspace -> rez -> logging -> background
            - Background wrapping must be last since it adds `& disown; exit`
        """
        command = app_command

        # 1. Apply Nuke fixes if requested
        if apply_nuke_fixes:
            command = CommandBuilder.apply_nuke_environment_fixes(command, config)

        # 2. Wrap with workspace if provided
        if workspace:
            command = CommandBuilder.build_workspace_command(workspace, command)

        # 3. Wrap with Rez if packages provided
        if rez_packages:
            command = CommandBuilder.wrap_with_rez(command, rez_packages)

        # 4. Add logging redirection if requested
        if add_logging_redirect:
            command = CommandBuilder.add_logging(command)

        # 5. Wrap for background if requested (must be last)
        if run_in_background:
            command = CommandBuilder.wrap_for_background(command)

        return command
