#!/usr/bin/env python3
"""Test that subprocess with large output doesn't deadlock."""

# Standard library imports
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

# Standard library imports
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# Local imports
from tests.helpers.synchronization import wait_for_condition


@pytest.mark.real_subprocess
def test_subprocess_with_large_output_no_deadlock() -> None:
    """Test that subprocess producing large output doesn't deadlock with PIPE + drain threads.

    This simulates what could happen with verbose VFX applications.
    The old DEVNULL approach would deadlock if the app writes >64KB to stdout/stderr.
    """

    # Create a Python script that generates large output
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "verbose_app.py"

        # Script that writes 1MB to both stdout and stderr
        script_content = """
import sys
# Write 1MB to stdout (would fill OS buffer and deadlock with DEVNULL)
for i in range(1024):
    print("X" * 1024)  # 1KB per line

# Write 1MB to stderr
for i in range(1024):
    print("E" * 1024, file=sys.stderr)  # 1KB per line
"""
        script_path.write_text(script_content)

        # Test 1: OLD WAY - DEVNULL (would deadlock without fix)
        print("Testing DEVNULL approach (deadlock prone)...")
        start = time.time()

        # This would deadlock if output > buffer size
        proc_devnull = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Set a timeout - if it takes >5 seconds, likely deadlocked
        try:
            proc_devnull.wait(timeout=5)
            print(f"DEVNULL completed in {time.time() - start:.2f}s")
        except subprocess.TimeoutExpired:
            print("DEVNULL approach DEADLOCKED (as expected)!")
            proc_devnull.kill()
            proc_devnull.wait()

        # Test 2: NEW WAY - PIPE with drain threads (should not deadlock)
        print("\nTesting PIPE with drain threads (fix)...")
        start = time.time()

        proc_pipe = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Drain threads to consume output
        def drain_stream(stream) -> None:
            try:
                for _line in stream:
                    pass  # Discard
            except Exception:
                pass

        stdout_thread = threading.Thread(
            target=drain_stream, args=(proc_pipe.stdout,), daemon=True
        )
        stderr_thread = threading.Thread(
            target=drain_stream, args=(proc_pipe.stderr,), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        # Should complete quickly without deadlock
        try:
            proc_pipe.wait(timeout=5)
            elapsed = time.time() - start
            print(f"PIPE + drain threads completed in {elapsed:.2f}s")
            assert elapsed < 5, "Took too long, possible deadlock"
            print("✓ No deadlock with PIPE + drain threads!")
        except subprocess.TimeoutExpired:
            proc_pipe.kill()
            proc_pipe.wait()
            pytest.fail("PIPE approach also deadlocked - fix failed!")


@pytest.mark.real_subprocess
def test_launcher_worker_no_deadlock() -> None:
    """Test that the actual LauncherWorker doesn't deadlock with verbose apps."""

    # Third-party imports
    from PySide6.QtCore import (
        QCoreApplication,
    )

    # Local application imports
    from launcher.worker import (
        LauncherWorker,
    )
    from tests.helpers.synchronization import (
        process_qt_events,
    )

    app = QCoreApplication.instance() or QCoreApplication([])

    # Create a command that generates lots of output
    if sys.platform == "win32":
        # Windows: dir /s generates lots of output
        command = "dir /s C:\\Windows\\System32"
    else:
        # Linux/Mac: find generates lots of output
        command = "find /usr -type f 2>&1 | head -10000"

    worker = LauncherWorker(
        launcher_id="test_verbose", command=command, working_dir=None
    )

    finished = False

    def on_finished(launcher_id, success, return_code) -> None:
        nonlocal finished
        finished = True
        print(f"LauncherWorker finished: success={success}, code={return_code}")

    worker.command_finished.connect(on_finished)

    # Start worker
    worker.start()
    try:
        # Wait up to 10 seconds
        start = time.time()
        timeout_sec = 10
        while not finished and time.time() - start < timeout_sec:
            process_qt_events(app, 10)
            # Use wait_for_condition instead of sleep to avoid blocking
            wait_for_condition(lambda: finished, timeout_ms=100, poll_interval_ms=50)

        # Check result
        assert finished, "LauncherWorker deadlocked or timed out!"
        print(f"✓ LauncherWorker completed in {time.time() - start:.2f}s")
    finally:
        # Always cleanup worker resources
        worker.request_stop()
        worker.wait(1000)


if __name__ == "__main__":
    print("=" * 60)
    print("Testing subprocess deadlock prevention")
    print("=" * 60)

    # Test basic subprocess behavior
    result1 = test_subprocess_with_large_output_no_deadlock()

    print("\n" + "=" * 60)
    print("Testing LauncherWorker implementation")
    print("=" * 60)

    # Test actual LauncherWorker
    result2 = test_launcher_worker_no_deadlock()

    print("\n" + "=" * 60)
    if result1 and result2:
        print("✓✓✓ ALL TESTS PASSED - No deadlock risk!")
    else:
        print("✗✗✗ TESTS FAILED - Deadlock risk remains!")
