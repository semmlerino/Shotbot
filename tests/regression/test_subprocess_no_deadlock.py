#!/usr/bin/env python3
"""Test that subprocess with large output doesn't deadlock."""

# Standard library imports
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

# Standard library imports
import subprocess
import tempfile
import threading
import time
from pathlib import Path


# Local imports


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
            except Exception:  # noqa: BLE001
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


if __name__ == "__main__":
    print("=" * 60)
    print("Testing subprocess deadlock prevention")
    print("=" * 60)

    # Test basic subprocess behavior
    test_subprocess_with_large_output_no_deadlock()

    print("\n" + "=" * 60)
    print("✓✓✓ ALL TESTS PASSED - No deadlock risk!")
    print("=" * 60)
