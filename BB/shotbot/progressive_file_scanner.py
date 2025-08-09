"""Progressive file scanning architecture with generator-based batching and cancellation.

This module provides a production-ready progressive scanning system that yields
results in batches for responsive UI updates and efficient memory usage.
"""

import enum
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Protocol,
    TypeVar,
)

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, Signal

# Set up logger for this module
logger = logging.getLogger(__name__)

T = TypeVar("T")


class ScanState(enum.Enum):
    """Scanner state enumeration."""

    IDLE = "idle"
    SCANNING = "scanning"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ScanProgress:
    """Progress information for scanning operation."""

    total_scanned: int = 0
    total_found: int = 0
    current_directory: str = ""
    directories_processed: int = 0
    directories_total: int = 0  # Estimated
    items_per_second: float = 0.0
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = 0.0
    memory_usage_mb: float = 0.0


@dataclass
class ScanResult:
    """Result from a scanning operation."""

    path: Path
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class BatchResult:
    """A batch of scan results."""

    results: List[ScanResult]
    batch_number: int
    is_final: bool
    progress: ScanProgress


class ScanFilter(Protocol):
    """Protocol for scan filters."""

    def should_include(self, path: Path) -> bool:
        """Check if path should be included in results.

        Args:
            path: Path to check

        Returns:
            True if path should be included
        """
        ...

    def should_traverse(self, directory: Path) -> bool:
        """Check if directory should be traversed.

        Args:
            directory: Directory to check

        Returns:
            True if directory should be traversed
        """
        ...


class ExtensionFilter:
    """Filter for file extensions."""

    def __init__(self, extensions: List[str], case_sensitive: bool = False):
        """Initialize extension filter.

        Args:
            extensions: List of extensions (with or without dots)
            case_sensitive: Whether to match case-sensitively
        """
        self.extensions = set()
        for ext in extensions:
            if not ext.startswith("."):
                ext = f".{ext}"
            if case_sensitive:
                self.extensions.add(ext)
            else:
                self.extensions.add(ext.lower())
        self.case_sensitive = case_sensitive

    def should_include(self, path: Path) -> bool:
        """Check if file has matching extension."""
        if not path.is_file():
            return False

        suffix = path.suffix
        if not self.case_sensitive:
            suffix = suffix.lower()

        return suffix in self.extensions

    def should_traverse(self, directory: Path) -> bool:
        """Always traverse directories."""
        return True


class PatternFilter:
    """Filter using glob patterns."""

    def __init__(
        self, patterns: List[str], exclude_patterns: Optional[List[str]] = None
    ):
        """Initialize pattern filter.

        Args:
            patterns: Include patterns
            exclude_patterns: Exclude patterns
        """
        self.patterns = patterns
        self.exclude_patterns = exclude_patterns or []

    def should_include(self, path: Path) -> bool:
        """Check if path matches patterns."""
        # Check exclude patterns first
        for pattern in self.exclude_patterns:
            if path.match(pattern):
                return False

        # Check include patterns
        for pattern in self.patterns:
            if path.match(pattern):
                return True

        return False

    def should_traverse(self, directory: Path) -> bool:
        """Check if directory should be traversed."""
        # Don't traverse excluded directories
        for pattern in self.exclude_patterns:
            if directory.match(pattern):
                return False
        return True


class ProgressiveFileScanner:
    """Generator-based progressive file scanner with batching and cancellation.

    This scanner provides:
    - Generator-based iteration for memory efficiency
    - Configurable batch sizes for UI responsiveness
    - Cancellation support with proper cleanup
    - Progress tracking and estimation
    - Filter chaining for flexible matching
    - Memory-aware operation

    Example:
        >>> scanner = ProgressiveFileScanner()
        >>> filter = ExtensionFilter([".3de"])
        >>> for batch in scanner.scan_directory("/shows", filter, batch_size=50):
        ...     print(f"Found {len(batch.results)} items")
        ...     update_ui(batch.results)
        ...     if should_cancel():
        ...         scanner.cancel()
        ...         break
    """

    def __init__(self, follow_symlinks: bool = False, max_depth: Optional[int] = None):
        """Initialize scanner.

        Args:
            follow_symlinks: Whether to follow symbolic links
            max_depth: Maximum directory depth (None for unlimited)
        """
        self.follow_symlinks = follow_symlinks
        self.max_depth = max_depth
        self._state = ScanState.IDLE
        self._cancel_requested = False
        self._pause_requested = False

    def scan_directory(
        self,
        root_path: Path,
        filter: Optional[ScanFilter] = None,
        batch_size: int = 100,
        metadata_extractor: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> Generator[BatchResult, None, None]:
        """Scan directory progressively, yielding results in batches.

        Args:
            root_path: Root directory to scan
            filter: Optional filter for results
            batch_size: Number of results per batch
            metadata_extractor: Optional function to extract metadata

        Yields:
            BatchResult containing batch of results and progress
        """
        if not isinstance(root_path, Path):
            root_path = Path(root_path)

        if not root_path.exists():
            logger.error(f"Path does not exist: {root_path}")
            self._state = ScanState.ERROR
            return

        if not root_path.is_dir():
            logger.error(f"Path is not a directory: {root_path}")
            self._state = ScanState.ERROR
            return

        self._state = ScanState.SCANNING
        self._cancel_requested = False
        self._pause_requested = False

        # Initialize progress tracking
        start_time = time.time()
        progress = ScanProgress()
        batch_number = 0
        current_batch: List[ScanResult] = []

        # Use generator for memory efficiency
        for result in self._scan_recursive(
            root_path, filter, metadata_extractor, progress, start_time, depth=0
        ):
            if self._cancel_requested:
                self._state = ScanState.CANCELLED
                logger.info("Scan cancelled by user")
                break

            while self._pause_requested:
                time.sleep(0.1)
                if self._cancel_requested:
                    break

            current_batch.append(result)

            # Yield batch when full
            if len(current_batch) >= batch_size:
                batch_number += 1
                progress.elapsed_seconds = time.time() - start_time

                yield BatchResult(
                    results=current_batch.copy(),
                    batch_number=batch_number,
                    is_final=False,
                    progress=self._calculate_progress(progress),
                )
                current_batch.clear()

        # Yield final batch
        if current_batch:
            batch_number += 1
            progress.elapsed_seconds = time.time() - start_time

            yield BatchResult(
                results=current_batch,
                batch_number=batch_number,
                is_final=True,
                progress=self._calculate_progress(progress),
            )

        # Update final state
        if self._state == ScanState.SCANNING:
            self._state = ScanState.COMPLETED
            logger.info(f"Scan completed: {progress.total_found} items found")

    def _scan_recursive(
        self,
        directory: Path,
        filter: Optional[ScanFilter],
        metadata_extractor: Optional[Callable[[Path], Dict[str, Any]]],
        progress: ScanProgress,
        start_time: float,
        depth: int,
    ) -> Generator[ScanResult, None, None]:
        """Recursively scan directory.

        Args:
            directory: Directory to scan
            filter: Optional filter
            metadata_extractor: Optional metadata extractor
            progress: Progress tracker
            start_time: Scan start time
            depth: Current depth

        Yields:
            ScanResult for each matching item
        """
        if self.max_depth is not None and depth > self.max_depth:
            return

        progress.current_directory = str(directory)
        progress.directories_processed += 1

        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot access directory {directory}: {e}")
            return

        # Process entries
        subdirectories = []

        for entry in entries:
            if self._cancel_requested:
                return

            progress.total_scanned += 1

            try:
                # Check if it's a symlink
                if entry.is_symlink() and not self.follow_symlinks:
                    continue

                # Process files
                if entry.is_file():
                    if filter is None or filter.should_include(entry):
                        # Extract metadata if extractor provided
                        metadata = {}
                        if metadata_extractor:
                            try:
                                metadata = metadata_extractor(entry)
                            except Exception as e:
                                logger.debug(
                                    f"Metadata extraction failed for {entry}: {e}"
                                )

                        progress.total_found += 1
                        yield ScanResult(path=entry, metadata=metadata)

                # Collect subdirectories for traversal
                elif entry.is_dir():
                    if filter is None or filter.should_traverse(entry):
                        subdirectories.append(entry)

            except (PermissionError, OSError) as e:
                logger.debug(f"Cannot access {entry}: {e}")
                yield ScanResult(path=entry, error=str(e))

        # Update progress stats
        elapsed = time.time() - start_time
        if elapsed > 0:
            progress.items_per_second = progress.total_scanned / elapsed

        # Recursively scan subdirectories
        for subdir in subdirectories:
            if self._cancel_requested:
                return

            yield from self._scan_recursive(
                subdir, filter, metadata_extractor, progress, start_time, depth + 1
            )

    def _calculate_progress(self, progress: ScanProgress) -> ScanProgress:
        """Calculate progress statistics.

        Args:
            progress: Current progress

        Returns:
            Updated progress with calculated fields
        """
        # Estimate remaining time based on current rate
        if progress.items_per_second > 0 and progress.directories_total > 0:
            remaining_dirs = progress.directories_total - progress.directories_processed
            progress.estimated_remaining_seconds = (
                remaining_dirs / progress.items_per_second
            )

        # Estimate memory usage (rough approximation)
        import sys

        progress.memory_usage_mb = sys.getsizeof(progress) / (1024 * 1024)

        return progress

    def cancel(self) -> None:
        """Request cancellation of current scan."""
        self._cancel_requested = True
        logger.info("Scan cancellation requested")

    def pause(self) -> None:
        """Pause current scan."""
        self._pause_requested = True
        self._state = ScanState.PAUSED
        logger.info("Scan paused")

    def resume(self) -> None:
        """Resume paused scan."""
        self._pause_requested = False
        self._state = ScanState.SCANNING
        logger.info("Scan resumed")

    def get_state(self) -> ScanState:
        """Get current scanner state.

        Returns:
            Current ScanState
        """
        return self._state


class AsyncProgressiveScanner(QThread):
    """Asynchronous progressive scanner running in a QThread.

    This scanner provides:
    - Background scanning with Qt signals
    - Batch emission for UI updates
    - Proper thread cleanup
    - Cancellation from main thread

    Example:
        >>> scanner = AsyncProgressiveScanner("/shows", batch_size=50)
        >>> scanner.batch_ready.connect(handle_batch)
        >>> scanner.scan_completed.connect(handle_completion)
        >>> scanner.start()
    """

    # Signals
    batch_ready = Signal(BatchResult)
    scan_started = Signal(str)  # root_path
    scan_completed = Signal(int)  # total_found
    scan_cancelled = Signal()
    scan_error = Signal(str)  # error_message
    progress_updated = Signal(ScanProgress)

    def __init__(
        self,
        root_path: str,
        filter: Optional[ScanFilter] = None,
        batch_size: int = 100,
        metadata_extractor: Optional[Callable[[Path], Dict[str, Any]]] = None,
        parent: Optional[QObject] = None,
    ):
        """Initialize async scanner.

        Args:
            root_path: Root directory to scan
            filter: Optional filter
            batch_size: Results per batch
            metadata_extractor: Optional metadata extractor
            parent: Parent QObject
        """
        super().__init__(parent)

        self.root_path = Path(root_path)
        self.filter = filter
        self.batch_size = batch_size
        self.metadata_extractor = metadata_extractor
        self._scanner = ProgressiveFileScanner()
        self._mutex = QMutex()
        self._should_stop = False

    def run(self) -> None:
        """Run scanning in thread."""
        try:
            self.scan_started.emit(str(self.root_path))
            total_found = 0

            for batch in self._scanner.scan_directory(
                self.root_path,
                self.filter,
                self.batch_size,
                self.metadata_extractor,
            ):
                with QMutexLocker(self._mutex):
                    if self._should_stop:
                        self.scan_cancelled.emit()
                        return

                total_found += len(batch.results)
                self.batch_ready.emit(batch)
                self.progress_updated.emit(batch.progress)

            self.scan_completed.emit(total_found)

        except Exception as e:
            logger.error(f"Scan error: {e}", exc_info=True)
            self.scan_error.emit(str(e))

    def stop(self) -> None:
        """Stop scanning."""
        with QMutexLocker(self._mutex):
            self._should_stop = True
            self._scanner.cancel()

    def pause(self) -> None:
        """Pause scanning."""
        self._scanner.pause()

    def resume(self) -> None:
        """Resume scanning."""
        self._scanner.resume()


class OptimizedSceneScanner(ProgressiveFileScanner):
    """Optimized scanner specifically for 3DE scene files.

    This scanner includes:
    - Pre-compiled patterns for performance
    - Smart directory pruning
    - Metadata extraction for scenes
    - User-based filtering
    """

    def __init__(
        self,
        current_user: Optional[str] = None,
        plate_patterns: Optional[List[str]] = None,
    ):
        """Initialize scene scanner.

        Args:
            current_user: Current username to exclude
            plate_patterns: Plate name patterns to extract
        """
        super().__init__(follow_symlinks=False, max_depth=10)

        self.current_user = current_user
        self.plate_patterns = plate_patterns or ["BG01", "FG01", "bg01", "fg01"]

        # Pre-compile for performance
        import re

        self.plate_regex = re.compile(
            r"(?:" + "|".join(re.escape(p) for p in self.plate_patterns) + r")",
            re.IGNORECASE,
        )

    def scan_for_scenes(
        self, root_path: Path, batch_size: int = 50
    ) -> Generator[BatchResult, None, None]:
        """Scan for 3DE scene files.

        Args:
            root_path: Root directory
            batch_size: Results per batch

        Yields:
            BatchResult with scene files
        """
        # Create filter for .3de files
        filter = ExtensionFilter([".3de"])

        # Create metadata extractor
        def extract_metadata(path: Path) -> Dict[str, Any]:
            metadata = {
                "size": path.stat().st_size,
                "modified": path.stat().st_mtime,
            }

            # Extract plate name if present
            if match := self.plate_regex.search(str(path)):
                metadata["plate"] = match.group()

            # Extract user from path
            parts = path.parts
            if "user" in parts:
                user_idx = parts.index("user")
                if user_idx + 1 < len(parts):
                    metadata["user"] = parts[user_idx + 1]

            return metadata

        # Use base scanner with our configuration
        for batch in self.scan_directory(
            root_path, filter, batch_size, extract_metadata
        ):
            # Filter out current user if specified
            if self.current_user:
                filtered_results = [
                    r
                    for r in batch.results
                    if r.metadata.get("user") != self.current_user
                ]
                batch.results = filtered_results

            yield batch
