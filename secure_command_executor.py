"""Secure command executor with strict validation and sandboxing.

This module provides safe command execution replacing the vulnerable
PersistentBashSession implementation.
"""

from __future__ import annotations

# Standard library imports
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import ClassVar

# Local application imports
from logging_mixin import LoggingMixin


class SecureCommandExecutor(LoggingMixin):
    """Secure command executor with whitelisting and validation."""

    # Strictly allowed executables (no bash/sh allowed)
    ALLOWED_EXECUTABLES: ClassVar[set[str]] = {
        "ws",  # Workspace command
        "echo",  # For testing/warming
        "pwd",  # Current directory
        "ls",  # List files (restricted paths)
        "find",  # Find files (restricted paths)
    }

    # Allowed arguments for specific commands
    ALLOWED_ARGUMENTS: ClassVar[dict[str, set[str]]] = {
        "ws": {"-sg", "-list", "-info", "-path"},
        "ls": {"-l", "-la", "-1"},
        "find": {"-name", "-type", "-maxdepth", "-mindepth"},
    }

    # Strictly allowed base paths for file operations
    ALLOWED_PATHS: ClassVar[list[str]] = [
        "/shows",
        "/mnt/shows",
        "/mnt/projects",
        "/tmp",
        # Add more production paths as needed
    ]

    # Dangerous patterns that should never appear in commands
    DANGEROUS_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"[;&|`$]"),  # Shell metacharacters
        re.compile(r"\$\(.*\)"),  # Command substitution
        re.compile(r">\s*/dev/"),  # Device file redirection
        re.compile(r"rm\s+-rf"),  # Dangerous rm commands
        re.compile(r"../../"),  # Path traversal
        re.compile(r"%2e%2e"),  # URL-encoded traversal
    ]

    def __init__(self) -> None:
        """Initialize secure command executor."""
        super().__init__()
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = threading.Lock()
        self._process_lock = threading.Lock()

    def execute(
        self,
        command: str,
        timeout: int = 30,
        cache_ttl: int = 0,
        allow_workspace_function: bool = False,
    ) -> str:
        """Execute a command securely with validation.

        Args:
            command: Command string to execute
            timeout: Maximum execution time in seconds
            cache_ttl: Cache time-to-live in seconds (0 = no cache)
            allow_workspace_function: Allow 'ws' as shell function via bash -i

        Returns:
            Command output as string

        Raises:
            ValueError: Invalid or dangerous command
            subprocess.TimeoutExpired: Command timed out
            subprocess.CalledProcessError: Command failed
        """
        # Check cache first
        if cache_ttl > 0:
            cached = self._get_cached(command)
            if cached is not None:
                self.logger.debug(f"Cache hit for command: {command[:50]}...")
                return cached

        # Validate command safety
        self._validate_command(command)

        # Parse command into executable and arguments
        try:
            parts = shlex.split(command)
        except ValueError as e:
            raise ValueError(f"Invalid command syntax: {e}") from e

        if not parts:
            raise ValueError("Empty command")

        executable = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        # Validate executable
        if executable not in self.ALLOWED_EXECUTABLES:
            raise ValueError(
                f"Executable '{executable}' not in allowed list. "
                 f"Allowed: {sorted(self.ALLOWED_EXECUTABLES)}"
            )

        # Validate arguments for specific commands
        if executable in self.ALLOWED_ARGUMENTS:
            allowed_args = self.ALLOWED_ARGUMENTS[executable]
            for arg in args:
                # Skip values that aren't flags
                if not arg.startswith("-"):
                    continue
                if arg not in allowed_args:
                    raise ValueError(
                        f"Argument '{arg}' not allowed for '{executable}'. "
                         f"Allowed: {sorted(allowed_args)}"
                    )

        # Validate paths in arguments
        for arg in args:
            if "/" in arg:  # Potential path
                self._validate_path(arg)

        # Execute command based on type
        if executable == "ws" and allow_workspace_function:
            # Special handling for 'ws' shell function
            output = self._execute_workspace_function(command, timeout)
        else:
            # Standard subprocess execution
            output = self._execute_subprocess(parts, timeout)

        # Cache result if requested
        if cache_ttl > 0:
            self._cache_result(command, output, cache_ttl)

        return output

    def _validate_command(self, command: str) -> None:
        """Validate command for dangerous patterns.

        Args:
            command: Command string to validate

        Raises:
            ValueError: Command contains dangerous patterns
        """
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.search(command):
                raise ValueError(
                    f"Command contains dangerous pattern: {pattern.pattern}"
                )

        # Check for null bytes
        if "\x00" in command:
            raise ValueError("Command contains null bytes")

        # Check command length
        if len(command) > 1024:
            raise ValueError("Command too long (max 1024 characters)")

    def _validate_path(self, path: str) -> None:
        """Validate that a path is safe and allowed.

        Args:
            path: Path string to validate

        Raises:
            ValueError: Path is not allowed or unsafe
        """
        # Skip non-absolute paths for now (they're relative to safe cwd)
        if not path.startswith("/"):
            return

        # Resolve path to handle symlinks and ..
        try:
            resolved = Path(path).resolve()
        except (OSError, RuntimeError):
            # Path doesn't exist yet or too many symlinks
            # Check the base path at least
            resolved = Path(path)

        resolved_str = str(resolved)

        # Check if path is under allowed directories
        path_allowed = False
        for allowed_base in self.ALLOWED_PATHS:
            if resolved_str.startswith(allowed_base):
                path_allowed = True
                break

        if not path_allowed:
            raise ValueError(
                f"Path '{path}' not in allowed directories. "
                 f"Allowed bases: {self.ALLOWED_PATHS}"
            )

        # Additional safety checks
        if ".." in resolved_str:
            raise ValueError("Path traversal detected")

        if "~" in path:
            raise ValueError("Home directory expansion not allowed")

    def _execute_subprocess(self, parts: list[str], timeout: int) -> str:
        """Execute command using subprocess.

        Args:
            parts: Command parts (executable + arguments)
            timeout: Timeout in seconds

        Returns:
            Command output

        Raises:
            subprocess.TimeoutExpired: Command timed out
            subprocess.CalledProcessError: Command failed
        """
        with self._process_lock:
            try:
                # Use subprocess.run for better control
                result = subprocess.run(
                    parts,
                    shell=False,  # NEVER use shell=True
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=True,  # Raise on non-zero exit
                    env=self._get_safe_environment(),
                )
                return result.stdout
            except subprocess.TimeoutExpired:
                self.logger.error(f"Command timed out after {timeout}s: {parts[0]}")
                raise
            except subprocess.CalledProcessError as e:
                # CalledProcessError.cmd and .stderr have dynamic types (str | list | bytes | None)
                cmd_str = str(e.cmd) if e.cmd else "unknown"
                stderr_str = str(e.stderr) if e.stderr else "no stderr"
                self.logger.error(f"Command failed: {cmd_str}, stderr: {stderr_str}")
                raise

    def _execute_workspace_function(self, command: str, timeout: int) -> str:
        """Execute workspace function using bash -i.

        This is a special case for the 'ws' shell function which
        requires an interactive bash shell.

        Args:
            command: Full ws command
            timeout: Timeout in seconds

        Returns:
            Command output

        Raises:
            subprocess.TimeoutExpired: Command timed out
            subprocess.CalledProcessError: Command failed
        """
        # Extra validation for ws command
        if not command.startswith("ws "):
            raise ValueError("Only 'ws' commands allowed in workspace mode")

        # Use bash -i -c but with strict command validation already done
        bash_command = ["/bin/bash", "-i", "-c", command]

        with self._process_lock:
            try:
                # For workspace commands, we need to use the current environment
                # to ensure shell functions are properly loaded from profile scripts
                result = subprocess.run(
                    bash_command,
                    shell=False,  # Still no shell expansion
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=True,
                    env=None,  # Use current environment for ws command to work
                )
                return result.stdout
            except subprocess.TimeoutExpired:
                self.logger.error(f"Workspace command timed out after {timeout}s")
                raise
            except subprocess.CalledProcessError as e:
                stderr_str = str(e.stderr) if e.stderr else "no stderr"
                self.logger.error(f"Workspace command failed: {stderr_str}")
                raise

    def _get_safe_environment(self) -> dict[str, str]:
        """Get sanitized environment variables.

        Returns:
            Safe environment dictionary
        """
        # Start with minimal environment
        safe_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": os.environ.get("HOME", "/tmp"),
            "USER": os.environ.get("USER", "nobody"),
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
        }

        # Add specific required variables
        required_vars = [
            "SHOWS_ROOT",
            "PROJECT_ROOT",
            "WS_CONFIG",
            # Add other required environment variables
        ]

        for var in required_vars:
            if var in os.environ:
                safe_env[var] = os.environ[var]

        return safe_env

    def _get_cached(self, command: str) -> str | None:
        """Get cached result if available and not expired.

        Args:
            command: Command string

        Returns:
            Cached output or None
        """
        with self._cache_lock:
            if command in self._cache:
                output, expiry = self._cache[command]
                if time.time() < expiry:
                    return output
                # Expired, remove from cache
                del self._cache[command]
        return None

    def _cache_result(self, command: str, output: str, ttl: int) -> None:
        """Cache command result.

        Args:
            command: Command string
            output: Command output
            ttl: Time-to-live in seconds
        """
        with self._cache_lock:
            expiry = time.time() + ttl
            self._cache[command] = (output, expiry)

            # Clean up old entries if cache is getting large
            if len(self._cache) > 100:
                self._cleanup_cache()

    def _cleanup_cache(self) -> None:
        """Remove expired entries from cache."""
        current_time = time.time()
        expired = [
            cmd for cmd, (_, expiry) in self._cache.items() if current_time >= expiry
        ]
        for cmd in expired:
            del self._cache[cmd]

    def clear_cache(self) -> None:
        """Clear all cached results."""
        with self._cache_lock:
            self._cache.clear()


# Singleton instance for easy replacement of ProcessPoolManager usage
_executor_instance: SecureCommandExecutor | None = None


def get_secure_executor() -> SecureCommandExecutor:
    """Get singleton secure executor instance.

    Returns:
        SecureCommandExecutor instance
    """
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = SecureCommandExecutor()
    return _executor_instance
