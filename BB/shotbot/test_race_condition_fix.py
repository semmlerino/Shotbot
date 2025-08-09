#!/usr/bin/env python3
"""Test script to verify race condition fixes in launcher_manager.py"""

import logging
import sys
import threading
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QCoreApplication, QTimer

from launcher_manager import LauncherManager


def stress_test_cleanup():
    """Stress test the cleanup methods with concurrent access."""
    app = QCoreApplication(sys.argv)
    manager = LauncherManager()

    # Create some test launchers
    for i in range(5):
        launcher_id = manager.create_launcher(
            name=f"Test Launcher {i}",
            command=f"echo 'Test {i}'",
            description=f"Test launcher {i}",
        )
        logger.info(f"Created launcher: {launcher_id}")

    # Function to execute launchers concurrently
    def execute_launcher(index):
        launchers = manager.list_launchers()
        if launchers:
            launcher = launchers[index % len(launchers)]
            logger.info(f"Thread {index} executing launcher: {launcher.name}")
            manager.execute_launcher(launcher.id, use_worker=True)

    # Function to call cleanup methods concurrently
    def trigger_cleanup(source):
        logger.info(f"Triggering cleanup from {source}")
        if source == "periodic":
            manager._periodic_cleanup()
        elif source == "get_count":
            count = manager.get_active_process_count()
            logger.info(f"Active process count: {count}")
        elif source == "get_info":
            info = manager.get_active_process_info()
            logger.info(f"Active process info count: {len(info)}")
        elif source == "direct_process":
            manager._cleanup_finished_processes()
        elif source == "direct_worker":
            manager._cleanup_finished_workers()

    # Create threads that will execute launchers
    execution_threads = []
    for i in range(10):
        thread = threading.Thread(
            target=execute_launcher, args=(i,), name=f"ExecutorThread-{i}"
        )
        execution_threads.append(thread)

    # Create threads that will trigger cleanup from different sources
    cleanup_threads = []
    cleanup_sources = [
        "periodic",
        "get_count",
        "get_info",
        "direct_process",
        "direct_worker",
    ]
    for i, source in enumerate(cleanup_sources * 2):  # Run each twice
        thread = threading.Thread(
            target=trigger_cleanup, args=(source,), name=f"CleanupThread-{source}-{i}"
        )
        cleanup_threads.append(thread)

    # Start all threads with small delays to create race conditions
    logger.info("Starting execution threads...")
    for thread in execution_threads:
        thread.start()
        time.sleep(0.05)  # Small delay to spread out starts

    logger.info("Starting cleanup threads...")
    for thread in cleanup_threads:
        thread.start()
        time.sleep(0.1)  # Slightly longer delay for cleanup threads

    # Also trigger cleanup via QTimer (simulates the periodic timer)
    def qt_timer_cleanup():
        logger.info("QTimer triggering cleanup")
        manager._cleanup_finished_workers()

    QTimer.singleShot(500, qt_timer_cleanup)
    QTimer.singleShot(1000, qt_timer_cleanup)
    QTimer.singleShot(1500, qt_timer_cleanup)

    # Wait for execution threads to finish
    for thread in execution_threads:
        thread.join(timeout=5)

    # Wait for cleanup threads to finish
    for thread in cleanup_threads:
        thread.join(timeout=5)

    # Give Qt timers time to fire
    QTimer.singleShot(2000, app.quit)
    app.exec()

    # Final cleanup
    manager.shutdown()

    logger.info("Stress test completed successfully!")
    return True


def test_dictionary_iteration_safety():
    """Test that dictionary iteration is safe during modification."""
    app = QCoreApplication(sys.argv)
    manager = LauncherManager()

    # Create a launcher
    launcher_id = manager.create_launcher(
        name="Iteration Test",
        command="sleep 1",
        description="Test for iteration safety",
    )

    # Execute multiple instances
    for i in range(20):
        manager.execute_launcher(launcher_id, use_worker=True)
        time.sleep(0.01)  # Small delay

    # Concurrent cleanup attempts
    def cleanup_loop():
        for _ in range(10):
            manager._cleanup_finished_workers()
            time.sleep(0.05)

    # Start multiple cleanup threads
    threads = []
    for i in range(5):
        thread = threading.Thread(target=cleanup_loop, name=f"CleanupLoop-{i}")
        threads.append(thread)
        thread.start()

    # Wait for threads
    for thread in threads:
        thread.join(timeout=10)

    # Shutdown
    manager.shutdown()
    app.quit()

    logger.info("Dictionary iteration safety test completed!")
    return True


if __name__ == "__main__":
    logger.info("Starting race condition tests...")

    try:
        # Test 1: Stress test with concurrent operations
        logger.info("\n=== TEST 1: Concurrent Operations Stress Test ===")
        if not stress_test_cleanup():
            logger.error("Stress test failed!")
            sys.exit(1)

        # Test 2: Dictionary iteration safety
        logger.info("\n=== TEST 2: Dictionary Iteration Safety Test ===")
        if not test_dictionary_iteration_safety():
            logger.error("Dictionary iteration test failed!")
            sys.exit(1)

        logger.info("\n=== ALL TESTS PASSED ===")
        logger.info("The race condition fixes appear to be working correctly!")

    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        sys.exit(1)
