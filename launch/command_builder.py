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
from typing import Final

from config import Config


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

    # Dangerous path patterns
    DANGEROUS_PATTERNS: Final[tuple[str, ...]] = (
        "../",  # Path traversal
        "/..",  # Path traversal variant
        "~/.",  # Hidden file access attempts
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
        try:
            normalized = str(Path(path).resolve())
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
            Rez-wrapped command: 'rez env {packages} -- bash -ilc "{command}"'

        Notes:
            - Uses bash -ilc (interactive + login) for workspace function loading
            - Safe in terminal context (persistent terminal or GUI terminal has TTY)
            - Double quotes command to preserve it as single argument
        """
        packages_str = " ".join(packages)
        logger.debug(f"Wrapping command with rez packages: {packages_str}")
        return f'rez env {packages_str} -- bash -ilc "{command}"'

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
        if config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
            env_fixes.append(
                "NUKE_PATH=$(echo $NUKE_PATH | tr ':' '\\n' | "
                "grep -v '/problematic_plugins' | tr '\\n' ':' | sed 's/:$//')"
            )

        # OCIO fallback configuration
        if config.NUKE_OCIO_FALLBACK_CONFIG:
            env_fixes.append(f"OCIO={config.NUKE_OCIO_FALLBACK_CONFIG}")

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
    def add_logging(command: str) -> str:
        """Add logging redirection to capture command output.

        Args:
            command: Command to add logging to

        Returns:
            Command with logging redirection: "{command} 2>&1 | tee -a {logfile}"
            Or original command if logging directory cannot be created

        Notes:
            - Creates ~/.shotbot/logs/ directory if needed
            - Logs to ~/.shotbot/logs/dispatcher.out
            - Uses tee to capture output while showing in terminal
            - Quotes log file path to handle spaces/special chars
            - Gracefully degrades if logging setup fails
        """
        log_dir = Path.home() / ".shotbot" / "logs"

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "dispatcher.out"
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
    def build_full_command(
        app_command: str,
        workspace: str | None,
        config: "type[Config]",
        rez_packages: list[str] | None = None,
        apply_nuke_fixes: bool = False,
        add_logging_redirect: bool = True,
    ) -> str:
        """Build complete command with all transformations applied.

        This is a convenience method that applies all transformations in order:
        1. Nuke environment fixes (if requested)
        2. Workspace wrapping (if workspace provided)
        3. Rez environment wrapping (if packages provided)
        4. Logging redirection (if requested)

        Args:
            app_command: Base application command
            workspace: Optional workspace path (already validated)
            config: Application configuration class (not instance)
            rez_packages: Optional Rez packages to load
            apply_nuke_fixes: Whether to apply Nuke environment fixes
            add_logging_redirect: Whether to add logging redirection

        Returns:
            Fully assembled command ready for execution

        Notes:
            - Transformations are applied in the order listed above
            - Workspace path must be pre-validated with validate_path()
            - Order matters: workspace -> rez -> logging
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

        return command
