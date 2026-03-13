"""Shared crash recovery workflow for controllers.

Extracts the common crash file scanning, dialog presentation, and recovery
execution logic used by both ShotSelectionController and ThreeDEController.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def execute_crash_recovery(
    workspace_path: str | Path,
    display_name: str,
    parent_widget: QWidget,
    post_recovery_callback: Callable[[], None] | None = None,
) -> None:
    """Run the crash-file scan → dialog → recover-and-archive workflow.

    Args:
        workspace_path: Directory to scan for crash files.
        display_name: Shot or scene name shown in user-facing messages.
        parent_widget: Qt parent for dialogs.
        post_recovery_callback: Optional callback invoked after successful recovery
            (e.g., refresh 3DE scenes).

    """
    from notification_manager import NotificationManager
    from threede_recovery import CrashFileInfo, ThreeDERecoveryManager
    from threede_recovery_dialog import (
        ThreeDERecoveryDialog,
        ThreeDERecoveryResultDialog,
    )

    recovery_manager = ThreeDERecoveryManager()

    try:
        crash_files = recovery_manager.find_crash_files(workspace_path, recursive=True)
    except Exception:
        logger.exception("Error scanning for crash files")
        NotificationManager.error(
            "Scan Error",
            f"Failed to scan for crash files in {workspace_path}"
        )
        return

    if not crash_files:
        NotificationManager.info(
            f"No 3DE crash files found in workspace for {display_name}."
        )
        return

    logger.info(f"Found {len(crash_files)} crash file(s), showing recovery dialog")
    dialog = ThreeDERecoveryDialog(crash_files, parent=parent_widget)

    def on_recovery_requested(crash_info: CrashFileInfo) -> None:
        logger.info(f"Recovery requested for: {crash_info.crash_path.name}")
        try:
            recovered_path, archived_path = recovery_manager.recover_and_archive(crash_info)

            result_dialog = ThreeDERecoveryResultDialog(
                success=True,
                recovered_path=recovered_path,
                archived_path=archived_path,
                parent=parent_widget,
            )
            _ = result_dialog.exec()

            if post_recovery_callback is not None:
                post_recovery_callback()

            NotificationManager.success(f"Recovered: {recovered_path.name}")

        except Exception as e:
            logger.exception("Failed to recover crash file")
            result_dialog = ThreeDERecoveryResultDialog(
                success=False,
                error_message=str(e),
                parent=parent_widget,
            )
            _ = result_dialog.exec()

            NotificationManager.error(
                "Recovery Failed",
                f"Failed to recover crash file: {e}"
            )

    _ = dialog.recovery_requested.connect(on_recovery_requested)
    _ = dialog.exec()
