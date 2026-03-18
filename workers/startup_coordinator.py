"""Startup coordination for initial data loading."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from timeout_config import TimeoutConfig
from typing_compat import override
from workers.thread_safe_worker import ThreadSafeWorker


if TYPE_CHECKING:
    from protocols import ProcessPoolInterface

logger = logging.getLogger(__name__)


class StartupCoordinator(ThreadSafeWorker):
    """Background thread for pre-warming bash sessions without blocking UI.

    This thread runs during idle time after the UI is displayed, initializing
    the bash environment and 'ws' function in the background. This prevents
    the ~8 second freeze that would occur if this initialization happened
    on the main thread during the first actual command execution.
    """

    def __init__(self, process_pool: ProcessPoolInterface) -> None:
        """Initialize session warmer with process pool.

        Args:
            process_pool: ProcessPoolInterface instance to warm up

        """
        super().__init__()
        self._process_pool: ProcessPoolInterface = process_pool

    @override
    def do_work(self) -> None:
        """Pre-warm bash sessions in background thread.

        Called by ThreadSafeWorker.run() to perform actual work.
        """
        try:
            # Check if we should stop before starting
            if self.should_stop():
                return

            logger.debug("Starting background session pre-warming")
            start_time = time.time()

            # Check if we should stop before executing
            if self.should_stop():
                return

            _ = self._process_pool.execute_workspace_command(
                "echo warming",
                cache_ttl=1,  # Short TTL since this is just for warming
                timeout=TimeoutConfig.BASH_WARMUP_SEC,  # Give enough time for first initialization
                use_login_shell=True,  # Use bash -l to avoid terminal blocking
            )
            duration = time.time() - start_time
            logger.info(
                f"Bash session pre-warming completed successfully ({duration:.2f}s)"
            )
        except Exception:  # noqa: BLE001
            # Don't fail the app if pre-warming fails
            logger.warning("Session pre-warming failed (non-critical)", exc_info=True)
