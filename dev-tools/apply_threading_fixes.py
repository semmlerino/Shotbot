#!/usr/bin/env python3
"""Apply critical threading fixes to ShotBot codebase"""

# Standard library imports
import sys
from pathlib import Path


def patch_threede_scene_worker() -> bool:
    """Apply threading fixes to threede_scene_worker.py"""

    file_path = Path("threede_scene_worker.py")
    if not file_path.exists():
        print(f"Warning: {file_path} not found")
        return False

    with file_path.open() as f:
        content = f.read()

    # Check if already patched
    if "_finished_mutex" in content:
        print("threede_scene_worker.py already patched")
        return True

    # Add mutex to __init__
    init_patch = """        self._all_scenes: list[ThreeDEScene] = []
        self._files_processed = 0

        # Thread safety for finished signal emission
        self._finished_mutex = QMutex()
        self._finished_emitted = False"""

    content = content.replace(
        """        self._all_scenes: list[ThreeDEScene] = []
        self._files_processed = 0""",
        init_patch,
    )

    # Fix run() method
    run_patch = '''    @Slot()
    def run(self) -> None:
        """Override run to ensure finished signal is always emitted.

        This ensures that the finished signal is emitted even when the thread
        is interrupted via requestInterruption(), not just when stopped normally.
        """
        # Initialize flag with thread-safe access
        with QMutexLocker(self._finished_mutex):
            self._finished_emitted = False

        try:
            # Call parent's run() which manages state and calls do_work()
            super().run()
        finally:
            # Thread-safe check and emit
            should_emit = False
            scenes_to_emit = []

            with QMutexLocker(self._finished_mutex):
                if not self._finished_emitted:
                    should_emit = True
                    self._finished_emitted = True
                    scenes_to_emit = self._all_scenes.copy() if self._all_scenes else []

            # Emit outside the lock to prevent deadlocks
            if should_emit:
                if not scenes_to_emit:
                    logger.debug(
                        "Worker finishing, emitting finished signal with empty list"
                    )
                    self.finished.emit([])
                else:
                    logger.debug(
                        f"Worker finishing, emitting finished signal with {len(scenes_to_emit)} scenes"
                    )
                    self.finished.emit(scenes_to_emit)'''

    # Find and replace the run method
    # Standard library imports
    import re

    run_pattern = r"@Slot\(\)\s+def run\(self\) -> None:.*?(?=\n    def )"
    content = re.sub(run_pattern, run_patch + "\n", content, flags=re.DOTALL)

    # Fix do_work method - protect _finished_emitted accesses

    # Pattern 1: Lines around 405-407
    content = content.replace(
        """            self._finished_emitted = True
            self.finished.emit([])""",
        """            with QMutexLocker(self._finished_mutex):
                if not self._finished_emitted:
                    self._finished_emitted = True
                    emit_empty = True
                else:
                    emit_empty = False

            if emit_empty:
                self.finished.emit([])""",
    )

    # Pattern 2: Lines around 425-426
    content = content.replace(
        """                self._finished_emitted = True
                self.finished.emit(self._all_scenes)""",
        """                with QMutexLocker(self._finished_mutex):
                    if not self._finished_emitted:
                        self._finished_emitted = True
                        scenes = self._all_scenes.copy()
                        emit_scenes = True
                    else:
                        emit_scenes = False

                if emit_scenes:
                    self.finished.emit(scenes)""",
    )

    # Pattern 3: Line 432
    content = content.replace(
        """            self._finished_emitted = True
            self.finished.emit(scenes)""",
        """            with QMutexLocker(self._finished_mutex):
                if not self._finished_emitted:
                    self._finished_emitted = True
                    emit_final = True
                else:
                    emit_final = False

            if emit_final:
                self.finished.emit(scenes)""",
    )

    # Add QMutexLocker import if not present
    if "QMutexLocker" not in content:
        content = content.replace(
            "from PySide6.QtCore import (",
            "from PySide6.QtCore import (\n    QMutexLocker,",
        )

    # Write back
    with file_path.open("w") as f:
        f.write(content)

    print(f"✓ Patched {file_path}")
    return True


def verify_patches() -> bool:
    """Verify that critical files have proper thread safety"""

    checks: list[tuple[str, bool]] = []

    # Check ThreeDESceneWorker
    worker_file = Path("threede_scene_worker.py")
    if worker_file.exists():
        content = worker_file.read_text()
        has_mutex = "_finished_mutex" in content
        has_locker = "QMutexLocker" in content
        checks.append(("ThreeDESceneWorker mutex protection", has_mutex and has_locker))

    # Check PreviousShotsModel
    model_file = Path("previous_shots_model.py")
    if model_file.exists():
        content = model_file.read_text()
        has_lock = "_scan_lock" in content
        has_cleanup = "_cleanup_worker_safely" in content
        checks.append(("PreviousShotsModel thread safety", has_lock and has_cleanup))

    # Check CacheManager
    cache_file = Path("cache_manager.py")
    if cache_file.exists():
        content = cache_file.read_text()
        has_rlock = "threading.RLock" in content
        checks.append(("CacheManager RLock usage", has_rlock))

    # Check ProcessPoolManager
    pool_file = Path("workers/process_pool_manager.py")
    if pool_file.exists():
        content = pool_file.read_text()
        has_singleton_lock = "_lock = threading.RLock()" in content
        has_condition = "threading.Condition" in content
        checks.append(
            ("ProcessPoolManager thread safety", has_singleton_lock or has_condition)
        )

    print("\n=== Thread Safety Verification ===")
    all_pass = True
    for name, status in checks:
        symbol = "✓" if status else "✗"
        print(f"{symbol} {name}: {'PASS' if status else 'FAIL'}")
        if not status:
            all_pass = False

    return all_pass


def main() -> int:
    """Apply threading fixes to the codebase"""

    print("Applying critical threading fixes to ShotBot...")
    print("=" * 50)

    # Apply patches
    success = True

    # Patch ThreeDESceneWorker
    if not patch_threede_scene_worker():
        success = False

    # Verify all patches
    print("\nVerifying thread safety...")
    if not verify_patches():
        print("\n⚠️ Some thread safety checks failed!")
        print("Manual intervention may be required.")
        success = False
    else:
        print("\n✅ All thread safety checks passed!")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
