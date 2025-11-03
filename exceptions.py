"""Standardized exception hierarchy for ShotBot application.

This module provides a comprehensive error handling system with specific
exception types for different failure scenarios, enabling better error
tracking, debugging, and user feedback.

Following best practices for exception design:
- Clear hierarchy with base ShotBotError
- Specific exceptions for each subsystem
- Useful error messages and context
- Integration with logging system
"""

from __future__ import annotations

from typing_compat import override


class ShotBotError(Exception):
    """Base exception for all ShotBot errors.

    This is the root of the exception hierarchy. All custom exceptions
    in the ShotBot application should inherit from this class.

    Attributes:
        message: Human-readable error message
        details: Optional additional error details
        error_code: Optional error code for categorization
    """

    def __init__(
        self,
        message: str,
        details: dict[str, str | int | None] | None = None,
        error_code: str | None = None,
    ) -> None:
        """Initialize ShotBot error.

        Args:
            message: Error message
            details: Optional dictionary with additional context
            error_code: Optional error code for categorization
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.error_code = error_code or "SHOTBOT_ERROR"

    @override
    def __str__(self) -> str:
        """String representation of the error."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class WorkspaceError(ShotBotError):
    """Exception for workspace-related errors.

    Raised when workspace commands fail, workspace paths are invalid,
    or workspace operations cannot be completed.
    """

    def __init__(
        self,
        message: str,
        workspace_path: str | None = None,
        command: str | None = None,
        details: dict[str, str | int | None] | None = None,
    ) -> None:
        """Initialize workspace error.

        Args:
            message: Error message
            workspace_path: The workspace path involved
            command: The workspace command that failed
            details: Additional error context
        """
        error_details = details or {}
        if workspace_path:
            error_details["workspace_path"] = workspace_path
        if command:
            error_details["command"] = command

        super().__init__(
            message=message, details=error_details, error_code="WORKSPACE_ERROR"
        )


class ThumbnailError(ShotBotError):
    """Exception for thumbnail processing errors.

    Raised when thumbnail generation fails, cache operations fail,
    or image processing encounters errors.
    """

    def __init__(
        self,
        message: str,
        image_path: str | None = None,
        thumbnail_path: str | None = None,
        reason: str | None = None,
        details: dict[str, str | int | None] | None = None,
    ) -> None:
        """Initialize thumbnail error.

        Args:
            message: Error message
            image_path: Source image path
            thumbnail_path: Destination thumbnail path
            reason: Specific reason for failure
            details: Additional error context
        """
        error_details = details or {}
        if image_path:
            error_details["image_path"] = image_path
        if thumbnail_path:
            error_details["thumbnail_path"] = thumbnail_path
        if reason:
            error_details["reason"] = reason

        super().__init__(
            message=message, details=error_details, error_code="THUMBNAIL_ERROR"
        )


class SecurityError(ShotBotError):
    """Exception for security-related errors.

    Raised when security violations are detected, such as:
    - Command injection attempts
    - Path traversal attempts
    - Unauthorized command execution
    - Invalid input sanitization
    """

    def __init__(
        self,
        message: str,
        violation_type: str | None = None,
        attempted_command: str | None = None,
        details: dict[str, str | int | None] | None = None,
    ) -> None:
        """Initialize security error.

        Args:
            message: Error message
            violation_type: Type of security violation
            attempted_command: The command that was blocked
            details: Additional security context
        """
        error_details = details or {}
        if violation_type:
            error_details["violation_type"] = violation_type
        if attempted_command:
            error_details["attempted_command"] = attempted_command

        super().__init__(
            message=message, details=error_details, error_code="SECURITY_ERROR"
        )


class LauncherError(ShotBotError):
    """Exception for application launcher errors.

    Raised when application launching fails, custom launchers
    have errors, or launcher configuration is invalid.
    """

    def __init__(
        self,
        message: str,
        launcher_name: str | None = None,
        launcher_command: str | None = None,
        exit_code: int | None = None,
        details: dict[str, str | int | None] | None = None,
    ) -> None:
        """Initialize launcher error.

        Args:
            message: Error message
            launcher_name: Name of the launcher
            launcher_command: The command that failed
            exit_code: Process exit code if available
            details: Additional launcher context
        """
        error_details = details or {}
        if launcher_name:
            error_details["launcher_name"] = launcher_name
        if launcher_command:
            error_details["launcher_command"] = launcher_command
        if exit_code is not None:
            error_details["exit_code"] = exit_code

        super().__init__(
            message=message, details=error_details, error_code="LAUNCHER_ERROR"
        )


class CacheError(ShotBotError):
    """Exception for cache-related errors.

    Raised when cache operations fail, cache corruption is detected,
    or cache validation fails.
    """

    def __init__(
        self,
        message: str,
        cache_key: str | None = None,
        cache_file: str | None = None,
        operation: str | None = None,
        details: dict[str, str | int | None] | None = None,
    ) -> None:
        """Initialize cache error.

        Args:
            message: Error message
            cache_key: The cache key involved
            cache_file: The cache file path
            operation: The operation that failed (read/write/validate)
            details: Additional cache context
        """
        error_details = details or {}
        if cache_key:
            error_details["cache_key"] = cache_key
        if cache_file:
            error_details["cache_file"] = cache_file
        if operation:
            error_details["operation"] = operation

        super().__init__(
            message=message, details=error_details, error_code="CACHE_ERROR"
        )
