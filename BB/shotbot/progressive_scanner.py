"""Progressive file scanner with async operations and worker pool.

This module provides optimized file scanning with progressive loading,
parallel processing, and UI-friendly batch updates.
"""

import asyncio
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
)

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal

logger = logging.getLogger(__name__)


class ScanState(Enum):
    """Scanner state enumeration."""

    IDLE = "idle"
    SCANNING = "scanning"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ScanResult:
    """Result from a file scan operation."""

    path: Path
    file_type: str
    size_bytes: int
    modified_time: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ScanProgress:
    """Progress information for a scan operation."""

    total_dirs: int = 0
    scanned_dirs: int = 0
    total_files: int = 0
    scanned_files: int = 0
    current_path: Optional[Path] = None
    elapsed_seconds: float = 0
    estimated_remaining: Optional[float] = None
    state: ScanState = ScanState.IDLE

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_dirs == 0:
            return 0.0
        return (self.scanned_dirs / self.total_dirs) * 100

    @property
    def scan_rate(self) -> float:
        """Calculate scan rate (files per second)."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.scanned_files / self.elapsed_seconds


class FileScanner:
    """Base file scanner with progressive loading."""

    def __init__(
        self,
        root_path: Path,
        file_patterns: List[str],
        exclude_patterns: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
        follow_symlinks: bool = False,
    ):
        self.root_path = root_path
        self.file_patterns = file_patterns
        self.exclude_patterns = exclude_patterns or []
        self.max_depth = max_depth
        self.follow_symlinks = follow_symlinks

        self._state = ScanState.IDLE
        self._should_stop = False
        self._should_pause = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially

    def scan(self) -> Iterator[ScanResult]:
        """Perform synchronous scan with generator pattern."""
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return

        self._state = ScanState.SCANNING
        start_time = time.time()

        try:
            yield from self._scan_directory(self.root_path, 0)
            self._state = ScanState.COMPLETED
        except Exception as e:
            logger.error(f"Scan error: {e}")
            self._state = ScanState.ERROR
            raise
        finally:
            elapsed = time.time() - start_time
            logger.info(f"Scan completed in {elapsed:.2f} seconds")

    def _scan_directory(self, path: Path, depth: int) -> Iterator[ScanResult]:
        """Recursively scan a directory."""
        # Check pause/stop conditions
        self._pause_event.wait()
        if self._should_stop:
            self._state = ScanState.CANCELLED
            return

        # Check depth limit
        if self.max_depth is not None and depth > self.max_depth:
            return

        try:
            entries = list(path.iterdir())
        except PermissionError as e:
            logger.warning(f"Permission denied: {path}")
            yield ScanResult(
                path=path,
                file_type="error",
                size_bytes=0,
                modified_time=datetime.now(),
                error=str(e),
            )
            return

        # Separate files and directories
        files = []
        dirs = []

        for entry in entries:
            try:
                # Skip excluded patterns
                if self._should_exclude(entry):
                    continue

                if entry.is_file(follow_symlinks=self.follow_symlinks):
                    files.append(entry)
                elif entry.is_dir(follow_symlinks=self.follow_symlinks):
                    dirs.append(entry)
            except OSError as e:
                logger.debug(f"Error accessing {entry}: {e}")
                continue

        # Process files in this directory
        for file_path in files:
            if self._matches_pattern(file_path):
                yield self._create_scan_result(file_path)

        # Recursively scan subdirectories
        for dir_path in dirs:
            yield from self._scan_directory(dir_path, depth + 1)

    def _should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded."""
        path_str = str(path)
        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return True
        return False

    def _matches_pattern(self, path: Path) -> bool:
        """Check if file matches any of the patterns."""
        for pattern in self.file_patterns:
            if path.match(pattern):
                return True
        return False

    def _create_scan_result(self, path: Path) -> ScanResult:
        """Create a scan result for a file."""
        try:
            stat = path.stat()
            return ScanResult(
                path=path,
                file_type=path.suffix.lower(),
                size_bytes=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime),
            )
        except OSError as e:
            return ScanResult(
                path=path,
                file_type="error",
                size_bytes=0,
                modified_time=datetime.now(),
                error=str(e),
            )

    def pause(self):
        """Pause the scan."""
        self._should_pause = True
        self._pause_event.clear()
        self._state = ScanState.PAUSED

    def resume(self):
        """Resume the scan."""
        self._should_pause = False
        self._pause_event.set()
        self._state = ScanState.SCANNING

    def cancel(self):
        """Cancel the scan."""
        self._should_stop = True
        self._pause_event.set()  # Unpause to allow cancellation
        self._state = ScanState.CANCELLED


class AsyncFileScanner:
    """Asynchronous file scanner using asyncio."""

    def __init__(
        self,
        root_path: Path,
        file_patterns: List[str],
        batch_size: int = 100,
        max_concurrent: int = 10,
    ):
        self.root_path = root_path
        self.file_patterns = file_patterns
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._results_queue: asyncio.Queue = asyncio.Queue()
        self._cancel_event = asyncio.Event()

    async def scan(self) -> AsyncIterator[List[ScanResult]]:
        """Perform async scan yielding batches of results."""
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return

        # Start scanning task
        scan_task = asyncio.create_task(self._scan_tree())

        # Yield results in batches
        batch = []
        try:
            while not self._cancel_event.is_set():
                try:
                    # Get result with timeout
                    result = await asyncio.wait_for(
                        self._results_queue.get(), timeout=1.0
                    )

                    if result is None:  # Sentinel value
                        if batch:
                            yield batch
                        break

                    batch.append(result)

                    if len(batch) >= self.batch_size:
                        yield batch
                        batch = []

                except asyncio.TimeoutError:
                    # Check if scanning is still running
                    if scan_task.done():
                        if batch:
                            yield batch
                        break
                    continue

        finally:
            # Ensure scan task is cleaned up
            if not scan_task.done():
                scan_task.cancel()
                try:
                    await scan_task
                except asyncio.CancelledError:
                    pass

    async def _scan_tree(self):
        """Scan directory tree asynchronously."""
        try:
            await self._scan_directory(self.root_path)
        finally:
            # Send sentinel value to indicate completion
            await self._results_queue.put(None)

    async def _scan_directory(self, path: Path):
        """Scan a single directory asynchronously."""
        if self._cancel_event.is_set():
            return

        async with self._semaphore:
            # Run directory listing in executor
            loop = asyncio.get_event_loop()

            try:
                entries = await loop.run_in_executor(None, self._list_directory, path)
            except Exception as e:
                logger.warning(f"Error listing directory {path}: {e}")
                return

            # Process entries
            tasks = []
            for entry in entries:
                if entry.is_file():
                    # Check if file matches patterns
                    for pattern in self.file_patterns:
                        if entry.match(pattern):
                            result = await loop.run_in_executor(
                                None, self._create_scan_result, entry
                            )
                            await self._results_queue.put(result)
                            break
                elif entry.is_dir():
                    # Recursively scan subdirectory
                    task = asyncio.create_task(self._scan_directory(entry))
                    tasks.append(task)

            # Wait for subdirectory scans
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _list_directory(self, path: Path) -> List[Path]:
        """List directory contents (sync operation for executor)."""
        try:
            return list(path.iterdir())
        except (PermissionError, OSError):
            return []

    def _create_scan_result(self, path: Path) -> ScanResult:
        """Create scan result (sync operation for executor)."""
        try:
            stat = path.stat()
            return ScanResult(
                path=path,
                file_type=path.suffix.lower(),
                size_bytes=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime),
            )
        except OSError as e:
            return ScanResult(
                path=path,
                file_type="error",
                size_bytes=0,
                modified_time=datetime.now(),
                error=str(e),
            )

    def cancel(self):
        """Cancel the async scan."""
        self._cancel_event.set()


class QFileScanWorker(QThread):
    """Qt worker thread for file scanning with progress updates."""

    # Signals
    progress_updated = Signal(ScanProgress)
    batch_ready = Signal(list)  # List[ScanResult]
    scan_completed = Signal()
    scan_error = Signal(str)

    def __init__(
        self,
        root_path: Path,
        file_patterns: List[str],
        batch_size: int = 50,
        update_interval_ms: int = 100,
    ):
        super().__init__()
        self.root_path = root_path
        self.file_patterns = file_patterns
        self.batch_size = batch_size
        self.update_interval_ms = update_interval_ms

        self._scanner: Optional[FileScanner] = None
        self._progress = ScanProgress()
        self._should_stop = False
        self._last_update_time = 0

    def run(self):
        """Run the scan in this thread."""
        try:
            self._scanner = FileScanner(
                root_path=self.root_path,
                file_patterns=self.file_patterns,
            )

            start_time = time.time()
            batch = []

            # First pass: count directories for progress
            self._count_directories()

            # Second pass: actual scanning
            for result in self._scanner.scan():
                if self._should_stop:
                    break

                batch.append(result)
                self._progress.scanned_files += 1

                # Update current path
                if result.path.is_dir():
                    self._progress.scanned_dirs += 1
                    self._progress.current_path = result.path

                # Emit batch when ready
                if len(batch) >= self.batch_size:
                    self.batch_ready.emit(batch)
                    batch = []

                # Update progress periodically
                current_time = time.time()
                if (
                    current_time - self._last_update_time
                ) * 1000 >= self.update_interval_ms:
                    self._progress.elapsed_seconds = current_time - start_time
                    self._update_estimated_time()
                    self.progress_updated.emit(self._progress)
                    self._last_update_time = current_time

            # Emit remaining batch
            if batch:
                self.batch_ready.emit(batch)

            # Final progress update
            self._progress.elapsed_seconds = time.time() - start_time
            self._progress.state = ScanState.COMPLETED
            self.progress_updated.emit(self._progress)
            self.scan_completed.emit()

        except Exception as e:
            logger.error(f"Scan error: {e}")
            self._progress.state = ScanState.ERROR
            self.scan_error.emit(str(e))

    def _count_directories(self):
        """Count total directories for progress calculation."""
        try:
            total = 0
            for root, dirs, _ in os.walk(self.root_path):
                total += len(dirs) + 1  # Include root itself
                if self._should_stop:
                    break
            self._progress.total_dirs = total
        except Exception as e:
            logger.warning(f"Error counting directories: {e}")
            self._progress.total_dirs = 1  # Fallback

    def _update_estimated_time(self):
        """Update estimated remaining time."""
        if self._progress.scan_rate > 0 and self._progress.total_dirs > 0:
            remaining_dirs = self._progress.total_dirs - self._progress.scanned_dirs
            self._progress.estimated_remaining = (
                remaining_dirs / self._progress.scan_rate
            )

    def stop(self):
        """Request the worker to stop."""
        self._should_stop = True
        if self._scanner:
            self._scanner.cancel()


class ParallelFileScanner(QObject):
    """Parallel file scanner using thread pool."""

    # Signals
    progress_updated = Signal(dict)  # Dict[str, ScanProgress]
    results_ready = Signal(list)  # List[ScanResult]
    scan_completed = Signal()

    def __init__(
        self,
        worker_count: int = 4,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.worker_count = worker_count

        self._thread_pool = QThreadPool.globalInstance()
        self._thread_pool.setMaxThreadCount(worker_count)

        self._active_workers: Dict[str, QRunnable] = {}
        self._results_queue: queue.Queue = queue.Queue()
        self._progress_map: Dict[str, ScanProgress] = {}
        self._lock = threading.RLock()

        # Results collection timer
        self._results_timer = QTimer(self)
        self._results_timer.timeout.connect(self._collect_results)
        self._results_timer.setInterval(100)

    def scan_paths(self, paths: List[Tuple[Path, List[str]]]):
        """Scan multiple paths in parallel.

        Args:
            paths: List of (root_path, file_patterns) tuples
        """
        self._results_timer.start()

        for i, (root_path, patterns) in enumerate(paths):
            worker_id = f"worker_{i}"
            runnable = ScanRunnable(
                worker_id=worker_id,
                root_path=root_path,
                file_patterns=patterns,
                results_queue=self._results_queue,
                progress_callback=self._update_progress,
            )

            with self._lock:
                self._active_workers[worker_id] = runnable
                self._progress_map[worker_id] = ScanProgress()

            self._thread_pool.start(runnable)

    def _update_progress(self, worker_id: str, progress: ScanProgress):
        """Update progress for a worker."""
        with self._lock:
            self._progress_map[worker_id] = progress

            # Check if all workers completed
            all_completed = all(
                p.state in (ScanState.COMPLETED, ScanState.ERROR)
                for p in self._progress_map.values()
            )

            if all_completed:
                self._results_timer.stop()
                self.scan_completed.emit()

        self.progress_updated.emit(dict(self._progress_map))

    def _collect_results(self):
        """Collect results from queue and emit them."""
        results = []

        try:
            while True:
                result = self._results_queue.get_nowait()
                results.append(result)

                if len(results) >= 100:  # Batch size
                    break
        except queue.Empty:
            pass

        if results:
            self.results_ready.emit(results)

    def stop_all(self):
        """Stop all scanning operations."""
        self._results_timer.stop()

        # Note: QRunnable doesn't have a direct stop method
        # Workers should check a shared stop flag
        with self._lock:
            self._active_workers.clear()


class ScanRunnable(QRunnable):
    """Runnable for parallel scanning."""

    def __init__(
        self,
        worker_id: str,
        root_path: Path,
        file_patterns: List[str],
        results_queue: queue.Queue,
        progress_callback: Callable[[str, ScanProgress], None],
    ):
        super().__init__()
        self.worker_id = worker_id
        self.root_path = root_path
        self.file_patterns = file_patterns
        self.results_queue = results_queue
        self.progress_callback = progress_callback

        self.setAutoDelete(True)

    def run(self):
        """Execute the scan."""
        scanner = FileScanner(
            root_path=self.root_path,
            file_patterns=self.file_patterns,
        )

        progress = ScanProgress(state=ScanState.SCANNING)
        start_time = time.time()

        try:
            for result in scanner.scan():
                self.results_queue.put(result)
                progress.scanned_files += 1

                if result.path.is_dir():
                    progress.scanned_dirs += 1

                # Update progress periodically
                if progress.scanned_files % 100 == 0:
                    progress.elapsed_seconds = time.time() - start_time
                    self.progress_callback(self.worker_id, progress)

            progress.state = ScanState.COMPLETED
        except Exception as e:
            logger.error(f"Worker {self.worker_id} error: {e}")
            progress.state = ScanState.ERROR

        progress.elapsed_seconds = time.time() - start_time
        self.progress_callback(self.worker_id, progress)


class OptimizedThreeDEScanner(QObject):
    """Optimized scanner specifically for 3DE files."""

    # Signals
    scene_found = Signal(dict)  # Scene info dict
    progress_updated = Signal(int, int)  # current, total
    scan_completed = Signal(list)  # All scenes

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._scanner: Optional[ParallelFileScanner] = None
        self._scenes: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def scan_user_directories(self, base_path: Path, excluded_users: Set[str]):
        """Scan user directories for 3DE files."""
        user_dir = base_path / "user"
        if not user_dir.exists():
            logger.warning(f"User directory does not exist: {user_dir}")
            return

        # Prepare scan paths
        scan_paths = []
        for user_path in user_dir.iterdir():
            if not user_path.is_dir():
                continue

            username = user_path.name
            if username in excluded_users:
                continue

            scan_paths.append((user_path, ["*.3de", "*.3DE"]))

        # Start parallel scan
        self._scanner = ParallelFileScanner(worker_count=4, parent=self)
        self._scanner.results_ready.connect(self._process_results)
        self._scanner.scan_completed.connect(self._on_scan_completed)
        self._scanner.progress_updated.connect(self._on_progress_updated)

        self._scanner.scan_paths(scan_paths)

    def _process_results(self, results: List[ScanResult]):
        """Process batch of scan results."""
        for result in results:
            if result.error:
                continue

            # Extract scene information
            scene_info = self._extract_scene_info(result)
            if scene_info:
                with self._lock:
                    self._scenes.append(scene_info)
                self.scene_found.emit(scene_info)

    def _extract_scene_info(self, result: ScanResult) -> Optional[Dict[str, Any]]:
        """Extract 3DE scene information from scan result."""
        try:
            path = result.path

            # Extract user from path
            parts = path.parts
            if "user" in parts:
                user_idx = parts.index("user")
                if user_idx + 1 < len(parts):
                    username = parts[user_idx + 1]
                else:
                    username = "unknown"
            else:
                username = "unknown"

            return {
                "path": str(path),
                "user": username,
                "size_bytes": result.size_bytes,
                "modified_time": result.modified_time.isoformat(),
                "file_name": path.name,
            }
        except Exception as e:
            logger.error(f"Error extracting scene info: {e}")
            return None

    def _on_progress_updated(self, progress_map: Dict[str, ScanProgress]):
        """Handle progress updates from parallel scanner."""
        total_scanned = sum(p.scanned_files for p in progress_map.values())
        total_estimated = len(progress_map) * 1000  # Rough estimate
        self.progress_updated.emit(total_scanned, total_estimated)

    def _on_scan_completed(self):
        """Handle scan completion."""
        with self._lock:
            scenes = list(self._scenes)
        self.scan_completed.emit(scenes)

    def stop(self):
        """Stop the scanning operation."""
        if self._scanner:
            self._scanner.stop_all()
