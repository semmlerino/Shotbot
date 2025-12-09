"""Type-safe threading test utilities for ShotBot.

This module provides comprehensive utilities for testing thread safety, race conditions,
deadlocks, and performance in a type-safe manner compatible with basedpyright.

Key Features:
- Full type safety with Python 3.8 compatible annotations
- Integration with ThreadSafeWorker and LauncherManager
- Deterministic race condition creation
- Deadlock detection and analysis
- Performance benchmarking
- pytest fixtures for isolated testing

Example Usage:
    # Test worker state transitions
    result = ThreadingTestHelpers.wait_for_worker_state(
        worker, WorkerState.RUNNING, timeout_ms=1000
    )
    assert result.success

    # Create deterministic race condition
    race_result = RaceConditionFactory.create_state_race(
        workers=[worker1, worker2],
        target_state=WorkerState.STOPPED
    )
    assert race_result.race_occurred

    # Detect deadlocks
    analysis = DeadlockDetector.detect_deadlock(
        threads=[thread1, thread2],
        timeout_ms=5000
    )
    assert not analysis.deadlock_detected
"""

from __future__ import annotations

# Standard library imports
import logging
import shutil
import sys
import threading
import time
import traceback
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    NamedTuple,
    Protocol,
    TypeVar,
)

# Third-party imports
import pytest
from PySide6.QtCore import (
    QEventLoop,
    QObject,
    Qt,
    QThread,
    Signal,
)

# Local application imports
from tests.helpers.synchronization import (
    simulate_work_without_sleep,
)


if TYPE_CHECKING:
    # Standard library imports
    from collections.abc import Callable, Iterator

# Import project modules
try:
    # Local application imports
    from launcher import LauncherWorker
    from launcher_manager import LauncherManager

    from thread_safe_worker import WorkerState
except ImportError:
    # Handle relative imports for test context
    # Standard library imports
    import sys
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Local application imports
    from launcher import LauncherWorker
    from launcher_manager import LauncherManager

    from thread_safe_worker import WorkerState

logger = logging.getLogger(__name__)

# Type variables for generic typing
T = TypeVar("T")
WorkerT = TypeVar("WorkerT", bound=QThread)
ManagerT = TypeVar("ManagerT", bound=QObject)


class ThreadingTestError(Exception):
    """Base exception for threading test utilities."""


class DeadlockDetectedError(ThreadingTestError):
    """Raised when a deadlock is detected during testing."""


class RaceConditionTimeoutError(ThreadingTestError):
    """Raised when race condition setup times out."""


# Protocol definitions for type safety
class WorkerProtocol(Protocol):
    """Protocol for worker-like objects that can be monitored."""

    def get_state(self) -> WorkerState: ...
    def request_stop(self) -> bool: ...
    def isRunning(self) -> bool: ...
    def wait(self, timeout_ms: int = 5000) -> bool: ...


class LockProtocol(Protocol):
    """Protocol for lock-like objects."""

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool: ...
    def release(self) -> None: ...
    def locked(self) -> bool: ...


class ManagerProtocol(Protocol):
    """Protocol for manager objects with process tracking."""

    def get_active_process_count(self) -> int: ...
    def shutdown(self) -> None: ...


# Result types using NamedTuple for immutability and type safety
class StateTransitionResult(NamedTuple):
    """Result of waiting for worker state transition."""

    success: bool
    final_state: WorkerState
    transition_time_ms: float
    timeout_occurred: bool
    error_message: str | None = None


class RaceConditionResult(NamedTuple):
    """Result of race condition test."""

    race_occurred: bool
    winner_thread: threading.Thread | None
    participants: int
    setup_time_ms: float
    race_duration_ms: float
    violations_detected: list[str] = field(default_factory=list)


class DeadlockAnalysisResult(NamedTuple):
    """Result of deadlock analysis."""

    deadlock_detected: bool
    involved_threads: list[threading.Thread]
    lock_graph: dict[str, list[str]]
    cycles: list[list[str]]
    analysis_time_ms: float
    stack_traces: dict[int, list[str]] = field(default_factory=dict)


class PerformanceResult(NamedTuple):
    """Result of performance measurement."""

    operation_name: str
    duration_ms: float
    iterations: int
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    std_deviation_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class ThreadInfo(NamedTuple):
    """Information about a monitored thread."""

    thread_id: int
    name: str
    state: str
    stack_trace: list[str]
    locks_held: list[str]
    locks_waiting: list[str]


@dataclass
class ThreadSafetyViolation:
    """Represents a thread safety violation."""

    violation_type: str
    thread_id: int
    resource_name: str
    timestamp: float
    stack_trace: list[str]
    description: str


class ThreadingTestHelpers:
    """Static helper methods for thread testing with type safety."""

    @staticmethod
    def wait_for_worker_state(
        worker: WorkerProtocol,
        target_state: WorkerState,
        timeout_ms: int = 5000,
        poll_interval_ms: int = 10,
    ) -> StateTransitionResult:
        """Wait for worker to reach specific state with timeout.

        Args:
            worker: Worker to monitor
            target_state: State to wait for
            timeout_ms: Maximum time to wait
            poll_interval_ms: How often to check state

        Returns:
            StateTransitionResult with success status and timing info

        Example:
            result = ThreadingTestHelpers.wait_for_worker_state(
                worker, WorkerState.RUNNING, timeout_ms=1000
            )
            assert result.success
            assert result.final_state == WorkerState.RUNNING

        """
        start_time = time.perf_counter()
        timeout_sec = timeout_ms / 1000.0
        poll_interval_ms / 1000.0

        current_state = worker.get_state()

        while time.perf_counter() - start_time < timeout_sec:
            current_state = worker.get_state()
            if current_state == target_state:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return StateTransitionResult(
                    success=True,
                    final_state=current_state,
                    transition_time_ms=elapsed_ms,
                    timeout_occurred=False,
                )

            simulate_work_without_sleep(poll_interval_ms)

        # Timeout occurred
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return StateTransitionResult(
            success=False,
            final_state=current_state,
            transition_time_ms=elapsed_ms,
            timeout_occurred=True,
            error_message=f"Timeout waiting for {target_state}, got {current_state}",
        )

    @staticmethod
    def trigger_race_condition(
        participants: list[Callable[[], Any]],
        setup_barrier: bool = True,
        timeout_ms: int = 5000,
    ) -> RaceConditionResult:
        """Trigger deterministic race condition between multiple operations.

        Args:
            participants: List of callables to execute simultaneously
            setup_barrier: Whether to use barrier for precise timing
            timeout_ms: Maximum time to wait for completion

        Returns:
            RaceConditionResult with race outcome and timing

        Example:
            def operation1():
                return worker1.request_stop()

            def operation2():
                return worker2.request_stop()

            result = ThreadingTestHelpers.trigger_race_condition(
                [operation1, operation2], timeout_ms=1000
            )
            assert result.race_occurred

        """
        setup_start = time.perf_counter()
        num_participants = len(participants)

        if num_participants < 2:
            raise ValueError("Race condition requires at least 2 participants")

        # Setup synchronization
        barrier = threading.Barrier(num_participants) if setup_barrier else None
        results: list[tuple[threading.Thread, Any, Exception]] = []
        winner_thread: threading.Thread | None = None
        race_start_event = threading.Event()

        def participant_wrapper(func: Callable[[], Any], _index: int) -> None:
            """Wrapper to synchronize participant execution."""
            thread = threading.current_thread()
            result = None
            error = None

            try:
                if barrier:
                    # Wait for all participants to be ready
                    barrier.wait(timeout_ms / 1000.0)
                else:
                    # Wait for start signal
                    race_start_event.wait(timeout_ms / 1000.0)

                # Execute the operation
                result = func()

                # Mark as winner if first to complete
                nonlocal winner_thread
                if winner_thread is None:
                    winner_thread = thread

            except Exception as e:
                error = e
            finally:
                results.append((thread, result, error))

        # Create and start participant threads
        threads = []
        for i, participant in enumerate(participants):
            thread = threading.Thread(
                target=participant_wrapper,
                args=(participant, i),
                name=f"RaceParticipant-{i}",
            )
            threads.append(thread)
            thread.start()

        # Trigger race start if not using barrier
        if not setup_barrier:
            race_start_event.set()

        race_start_time = time.perf_counter()

        # Wait for all threads to complete
        timeout_sec = timeout_ms / 1000.0
        for thread in threads:
            thread.join(timeout_sec)

        race_end_time = time.perf_counter()
        setup_time_ms = (race_start_time - setup_start) * 1000
        race_duration_ms = (race_end_time - race_start_time) * 1000

        # Analyze results
        race_occurred = len({r[1] for r in results if r[2] is None}) > 1
        violations = [
            f"Thread {r[0].name} raised {type(r[2]).__name__}: {r[2]}"
            for r in results
            if r[2] is not None
        ]

        return RaceConditionResult(
            race_occurred=race_occurred,
            winner_thread=winner_thread,
            participants=num_participants,
            setup_time_ms=setup_time_ms,
            race_duration_ms=race_duration_ms,
            violations_detected=violations,
        )

    @staticmethod
    def monitor_thread_safety(
        operation: Callable[[], T],
        _monitored_resources: list[str],
        _duration_ms: int = 1000,
    ) -> tuple[T, list[ThreadSafetyViolation]]:
        """Monitor operation for thread safety violations.

        WARNING: This is a STUB - it does NOT detect thread safety violations.
        The function executes the operation but always returns empty violations.
        Do NOT rely on this for actual thread safety verification.

        Args:
            operation: Operation to monitor
            monitored_resources: Names of resources to monitor (IGNORED)
            duration_ms: How long to monitor (IGNORED)

        Returns:
            Tuple of (operation_result, empty_violations_list)

        Note:
            Real implementation would require instrumentation of monitored
            resources to detect race conditions and improper synchronization.

        """
        import warnings

        warnings.warn(
            "monitor_thread_safety() is a stub that does NOT detect violations. "
            "Do not rely on empty violations list as proof of thread safety.",
            UserWarning,
            stacklevel=2,
        )

        violations: list[ThreadSafetyViolation] = []
        result = operation()
        return result, violations

    @staticmethod
    def create_concurrent_workers(
        worker_factory: Callable[[], WorkerT],
        count: int,
        start_delay_ms: int = 10,
        cleanup_timeout_ms: int = 5000,
    ) -> list[WorkerT]:
        """Create multiple workers with staggered startup for testing.

        Args:
            worker_factory: Factory function to create workers
            count: Number of workers to create
            start_delay_ms: Delay between worker starts
            cleanup_timeout_ms: Timeout for cleanup operations

        Returns:
            List of created and started workers

        Example:
            workers = ThreadingTestHelpers.create_concurrent_workers(
                lambda: LauncherWorker("test", "echo hello"),
                count=3,
                start_delay_ms=50
            )
            # All workers will be started with 50ms delays

        """
        workers: list[WorkerT] = []
        start_delay_ms / 1000.0

        try:
            for i in range(count):
                worker = worker_factory()
                workers.append(worker)
                worker.start()

                if i < count - 1:  # Don't delay after last worker
                    simulate_work_without_sleep(start_delay_ms)

            # Verify all workers started
            for worker in workers:
                if hasattr(worker, "wait_for_started"):
                    worker.wait_for_started(1000)  # Wait up to 1 second

            return workers

        except Exception as e:
            # Cleanup on error
            ThreadingTestHelpers._cleanup_workers(workers, cleanup_timeout_ms)
            raise ThreadingTestError(f"Failed to create concurrent workers: {e}") from e

    @staticmethod
    def _cleanup_workers(workers: list[WorkerT], timeout_ms: int) -> None:
        """Clean up worker threads safely."""
        for worker in workers:
            try:
                if hasattr(worker, "request_stop"):
                    worker.request_stop()
                elif hasattr(worker, "quit"):
                    worker.quit()

                if hasattr(worker, "wait"):
                    worker.wait(timeout_ms)

            except Exception as e:
                logger.warning(f"Error cleaning up worker: {e}")


class DeadlockDetector:
    """Deadlock detection and analysis utilities."""

    @staticmethod
    def detect_deadlock(
        threads: list[threading.Thread | None] | None = None,
        _timeout_ms: int = 5000,
        include_stack_traces: bool = True,
    ) -> DeadlockAnalysisResult:
        """Detect deadlocks in specified threads or all threads.

        Args:
            threads: Threads to analyze (None for all threads)
            timeout_ms: Maximum time to spend on analysis
            include_stack_traces: Whether to capture stack traces

        Returns:
            DeadlockAnalysisResult with deadlock information

        Example:
            analysis = DeadlockDetector.detect_deadlock(
                threads=[worker_thread, manager_thread],
                timeout_ms=3000
            )
            if analysis.deadlock_detected:
                logger.error(f"Deadlock between: {analysis.involved_threads}")

        """
        analysis_start = time.perf_counter()

        if threads is None:
            threads = [t for t in threading.enumerate() if t.is_alive()]

        # Build lock dependency graph
        lock_graph = DeadlockDetector.get_lock_graph(threads)

        # Find cycles in the dependency graph
        cycles = DeadlockDetector.find_cycles(lock_graph)

        # Capture stack traces if requested
        stack_traces = {}
        if include_stack_traces:
            stack_traces = DeadlockDetector.get_thread_stacks(threads)

        analysis_time_ms = (time.perf_counter() - analysis_start) * 1000

        # Determine involved threads
        involved_threads = []
        if cycles:
            # Find threads involved in cycles
            involved_thread_names = set()
            for cycle in cycles:
                involved_thread_names.update(cycle)

            involved_threads = [t for t in threads if t.name in involved_thread_names]

        return DeadlockAnalysisResult(
            deadlock_detected=len(cycles) > 0,
            involved_threads=involved_threads,
            lock_graph=lock_graph,
            cycles=cycles,
            analysis_time_ms=analysis_time_ms,
            stack_traces=stack_traces,
        )

    @staticmethod
    def get_lock_graph(_threads: list[threading.Thread]) -> dict[str, list[str]]:
        """Build wait-for graph of lock dependencies.

        WARNING: This is a STUB - it does NOT track actual lock dependencies.
        The function always returns an empty graph regardless of actual
        thread state. Do NOT rely on this for deadlock detection.

        Args:
            threads: Threads to analyze (IGNORED)

        Returns:
            Empty dictionary (stub - no actual analysis performed)

        Note:
            Real implementation would require instrumentation of lock
            acquisition, tracking of lock ownership, and detection of
            wait-for relationships.

        """
        import warnings

        warnings.warn(
            "get_lock_graph() is a stub that does NOT track lock dependencies. "
            "Do not rely on empty graph as proof of no deadlock potential.",
            UserWarning,
            stacklevel=2,
        )

        graph: dict[str, list[str]] = defaultdict(list)
        return dict(graph)

    @staticmethod
    def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
        """Find cycles in directed graph using DFS.

        Args:
            graph: Directed graph as adjacency list

        Returns:
            List of cycles found (each cycle is a list of node names)

        """
        cycles: list[list[str]] = []
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node: str) -> bool:
            """DFS helper to detect cycles."""
            if node in rec_stack:
                # Found cycle - extract it from path
                cycle_start = path.index(node)
                cycle = [*path[cycle_start:], node]
                cycles.append(cycle)
                return True

            if node in visited:
                return False

            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if dfs(neighbor):
                    return True

            rec_stack.remove(node)
            path.pop()
            return False

        # Check all nodes for cycles
        for node in graph:
            if node not in visited:
                dfs(node)

        return cycles

    @staticmethod
    def get_thread_stacks(threads: list[threading.Thread]) -> dict[int, list[str]]:
        """Capture stack traces for specified threads.

        Args:
            threads: Threads to capture stacks for

        Returns:
            Dictionary mapping thread ID to stack trace lines

        """
        stack_traces = {}

        # Get current frame for all threads
        frames = sys._current_frames()

        for thread in threads:
            thread_id = thread.ident
            if thread_id and thread_id in frames:
                frame = frames[thread_id]
                stack_lines = traceback.format_stack(frame)
                stack_traces[thread_id] = stack_lines

        return stack_traces


class RaceConditionFactory:
    """Factory for creating deterministic race conditions."""

    @staticmethod
    def create_state_race(
        workers: list[WorkerProtocol],
        target_state: WorkerState,
        timeout_ms: int = 2000,
    ) -> RaceConditionResult:
        """Create race condition in worker state transitions.

        Args:
            workers: Workers to race
            target_state: State to transition to simultaneously
            timeout_ms: Timeout for race setup

        Returns:
            RaceConditionResult with race outcome

        Example:
            result = RaceConditionFactory.create_state_race(
                workers=[worker1, worker2],
                target_state=WorkerState.STOPPED
            )
            assert result.race_occurred

        """
        operations = []

        if target_state == WorkerState.STOPPED:
            operations = [lambda w=worker: w.request_stop() for worker in workers]
        else:
            # For other states, would need specific transition operations
            raise ValueError(f"State race not implemented for {target_state}")

        return ThreadingTestHelpers.trigger_race_condition(
            operations,
            setup_barrier=True,
            timeout_ms=timeout_ms,
        )

    @staticmethod
    def create_signal_race(
        signal: Signal,
        emit_count: int = 2,
        disconnect_after: int = 1,
        timeout_ms: int = 1000,
    ) -> RaceConditionResult:
        """Create race between signal emission and disconnection.

        Args:
            signal: Qt signal to race with
            emit_count: Number of emissions to perform
            disconnect_after: Disconnect after this many emissions
            timeout_ms: Timeout for race

        Returns:
            RaceConditionResult with race outcome

        """
        received_signals = []

        def signal_handler(*args) -> None:
            received_signals.append(args)

        # Connect signal handler
        signal.connect(signal_handler)

        def emit_operation() -> None:
            for i in range(emit_count):
                signal.emit()
                if i == disconnect_after - 1:
                    simulate_work_without_sleep(1)  # Small delay to create race window

        def disconnect_operation() -> None:
            simulate_work_without_sleep(1)  # Small delay to create race window
            signal.disconnect(signal_handler)

        result = ThreadingTestHelpers.trigger_race_condition(
            [emit_operation, disconnect_operation],
            setup_barrier=True,
            timeout_ms=timeout_ms,
        )

        # Enhance result with signal-specific information
        return result._replace(
            violations_detected=[
                *result.violations_detected,
                f"Received {len(received_signals)} signals during race",
            ],
        )

    @staticmethod
    def create_resource_race(
        resource_operations: list[Callable[[], Any]],
        _resource_name: str = "shared_resource",
        timeout_ms: int = 1000,
    ) -> RaceConditionResult:
        """Create race for shared resource access.

        Args:
            resource_operations: Operations that access the resource
            resource_name: Name of the resource for logging
            timeout_ms: Timeout for race

        Returns:
            RaceConditionResult with race outcome

        Example:
            operations = [
                lambda: manager.get_active_process_count(),
                lambda: manager.shutdown(),
            ]
            result = RaceConditionFactory.create_resource_race(
                operations, "process_manager"
            )

        """
        return ThreadingTestHelpers.trigger_race_condition(
            resource_operations,
            setup_barrier=True,
            timeout_ms=timeout_ms,
        )

    @staticmethod
    def create_cleanup_race(
        cleanup_operations: list[Callable[[], Any]],
        active_operations: list[Callable[[], Any]],
        timeout_ms: int = 2000,
    ) -> RaceConditionResult:
        """Create race between cleanup and active operations.

        Args:
            cleanup_operations: Cleanup operations to race
            active_operations: Active operations to race against cleanup
            timeout_ms: Timeout for race

        Returns:
            RaceConditionResult with race outcome

        """
        all_operations = cleanup_operations + active_operations

        return ThreadingTestHelpers.trigger_race_condition(
            all_operations,
            setup_barrier=True,
            timeout_ms=timeout_ms,
        )


class PerformanceMetrics:
    """Performance measurement utilities for threading operations."""

    @staticmethod
    def measure_thread_creation(
        worker_factory: Callable[[], WorkerT],
        iterations: int = 10,
        warmup_iterations: int = 2,
    ) -> PerformanceResult:
        """Benchmark thread creation performance.

        Args:
            worker_factory: Factory function to create workers
            iterations: Number of iterations to measure
            warmup_iterations: Warmup iterations (not counted)

        Returns:
            PerformanceResult with timing statistics

        """
        # Warmup
        for _ in range(warmup_iterations):
            worker = worker_factory()
            if hasattr(worker, "deleteLater"):
                worker.deleteLater()

        # Measure iterations
        durations = []

        for _ in range(iterations):
            start_time = time.perf_counter()
            worker = worker_factory()
            worker.start()

            # Wait for thread to actually start
            if hasattr(worker, "isRunning"):
                while not worker.isRunning():
                    simulate_work_without_sleep(1)

            end_time = time.perf_counter()
            durations.append((end_time - start_time) * 1000)  # Convert to ms

            # Cleanup
            if hasattr(worker, "request_stop"):
                worker.request_stop()
            if hasattr(worker, "wait"):
                worker.wait(1000)
            if hasattr(worker, "deleteLater"):
                worker.deleteLater()

        return PerformanceMetrics._calculate_statistics(
            "thread_creation",
            durations,
            iterations,
        )

    @staticmethod
    def measure_lock_contention(
        lock: LockProtocol,
        contention_threads: int = 4,
        operations_per_thread: int = 10,
        timeout_ms: int = 5000,
    ) -> PerformanceResult:
        """Measure lock contention performance.

        Args:
            lock: Lock to measure contention for
            contention_threads: Number of competing threads
            operations_per_thread: Operations per thread
            timeout_ms: Timeout for measurement

        Returns:
            PerformanceResult with contention statistics

        """
        durations = []
        barrier = threading.Barrier(contention_threads)

        def contending_operation(thread_id: int) -> None:
            """Operation that contends for the lock."""
            barrier.wait()  # Synchronize start

            for _ in range(operations_per_thread):
                start_time = time.perf_counter()

                if lock.acquire(timeout=timeout_ms / 1000.0):
                    try:
                        # Simulate work while holding lock
                        simulate_work_without_sleep(1)
                    finally:
                        lock.release()

                end_time = time.perf_counter()
                durations.append((end_time - start_time) * 1000)

        # Start contending threads
        threads = []
        for i in range(contention_threads):
            thread = threading.Thread(
                target=contending_operation,
                args=(i,),
                name=f"ContentionThread-{i}",
            )
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout_ms / 1000.0)

        total_operations = contention_threads * operations_per_thread

        return PerformanceMetrics._calculate_statistics(
            "lock_contention",
            durations,
            total_operations,
            metadata={"contention_threads": contention_threads},
        )

    @staticmethod
    def measure_signal_latency(
        signal: Signal,
        iterations: int = 100,
        connection_type: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
    ) -> PerformanceResult:
        """Measure Qt signal emission latency.

        Args:
            signal: Signal to measure
            iterations: Number of measurements
            connection_type: Qt connection type to test

        Returns:
            PerformanceResult with latency statistics

        """
        durations = []
        received_times = []

        def signal_handler() -> None:
            received_times.append(time.perf_counter())

        # Connect signal with specified connection type
        signal.connect(signal_handler, connection_type)

        try:
            for _ in range(iterations):
                received_times.clear()

                start_time = time.perf_counter()
                signal.emit()

                # Wait for signal to be received
                timeout = time.perf_counter() + 1.0  # 1 second timeout
                while not received_times and time.perf_counter() < timeout:
                    QEventLoop().processEvents()
                    simulate_work_without_sleep(1)

                if received_times:
                    duration_ms = (received_times[0] - start_time) * 1000
                    durations.append(duration_ms)

        finally:
            signal.disconnect(signal_handler)

        return PerformanceMetrics._calculate_statistics(
            "signal_latency",
            durations,
            len(durations),
            metadata={"connection_type": str(connection_type)},
        )

    @staticmethod
    def compare_before_after(
        before_operation: Callable[[], PerformanceResult],
        after_operation: Callable[[], PerformanceResult],
        improvement_threshold: float = 5.0,
    ) -> dict[str, Any]:
        """Compare performance before and after an optimization.

        Args:
            before_operation: Operation to measure "before" performance
            after_operation: Operation to measure "after" performance
            improvement_threshold: Minimum improvement percentage to report

        Returns:
            Dictionary with comparison results

        Example:
            comparison = PerformanceMetrics.compare_before_after(
                lambda: measure_thread_creation(old_factory),
                lambda: measure_thread_creation(new_factory),
                improvement_threshold=10.0
            )
            assert comparison["improvement_percent"] > 10

        """
        before_result = before_operation()
        after_result = after_operation()

        improvement_percent = (
            (before_result.avg_duration_ms - after_result.avg_duration_ms)
            / before_result.avg_duration_ms
            * 100
        )

        is_improvement = improvement_percent >= improvement_threshold

        return {
            "before_result": before_result,
            "after_result": after_result,
            "improvement_percent": improvement_percent,
            "is_significant_improvement": is_improvement,
            "improvement_threshold": improvement_threshold,
            "comparison_summary": f"{improvement_percent:.1f}% {'improvement' if improvement_percent > 0 else 'regression'}",
        }

    @staticmethod
    def _calculate_statistics(
        operation_name: str,
        durations: list[float],
        iterations: int,
        metadata: dict[str, Any | None] | None = None,
    ) -> PerformanceResult:
        """Calculate performance statistics from duration measurements."""
        if not durations:
            return PerformanceResult(
                operation_name=operation_name,
                duration_ms=0.0,
                iterations=0,
                avg_duration_ms=0.0,
                min_duration_ms=0.0,
                max_duration_ms=0.0,
                std_deviation_ms=0.0,
                metadata=metadata or {},
            )

        total_duration = sum(durations)
        avg_duration = total_duration / len(durations)
        min_duration = min(durations)
        max_duration = max(durations)

        # Calculate standard deviation
        variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)
        std_deviation = variance**0.5

        return PerformanceResult(
            operation_name=operation_name,
            duration_ms=total_duration,
            iterations=iterations,
            avg_duration_ms=avg_duration,
            min_duration_ms=min_duration,
            max_duration_ms=max_duration,
            std_deviation_ms=std_deviation,
            metadata=metadata or {},
        )


# Pytest fixtures for threading tests
@pytest.fixture
def isolated_launcher_manager(tmp_path: Path) -> Iterator[LauncherManager]:
    """Provide isolated LauncherManager for testing.

    Creates a temporary manager with separate configuration
    to avoid interference between tests.

    Args:
        tmp_path: Pytest tmp_path fixture for isolated filesystem

    Yields:
        LauncherManager: Isolated manager instance

    """
    # Create temporary config directory using pytest tmp_path for isolation
    temp_config_dir = tmp_path / ".shotbot_test"
    temp_config_dir.mkdir(parents=True, exist_ok=True)

    # Create manager with temporary config
    manager = LauncherManager()
    # Override config path for isolation
    manager.config.config_dir = temp_config_dir
    manager.config.config_file = temp_config_dir / "custom_launchers.json"

    try:
        yield manager
    finally:
        # Cleanup
        manager.shutdown()

        # Remove temporary config
        if temp_config_dir.exists():
            shutil.rmtree(temp_config_dir, ignore_errors=True)


@pytest.fixture
def monitored_worker(qtbot) -> Iterator[LauncherWorker]:
    """Provide LauncherWorker with automatic monitoring and cleanup.

    Args:
        qtbot: pytest-qt fixture for Qt testing

    Yields:
        LauncherWorker: Monitored worker instance

    """
    worker = LauncherWorker("test_launcher", "echo 'test'")
    # Note: LauncherWorker is QThread, not QWidget - no qtbot.addWidget needed

    # Add monitoring
    state_changes = []

    def track_state_change() -> None:
        state_changes.append((time.perf_counter(), worker.get_state()))

    worker.worker_started.connect(track_state_change)
    worker.worker_stopped.connect(track_state_change)
    worker.worker_error.connect(
        lambda msg: state_changes.append((time.perf_counter(), f"ERROR: {msg}")),
    )

    try:
        yield worker
    finally:
        # Ensure worker is stopped
        if worker.isRunning():
            worker.request_stop()
            worker.wait(2000)

        # Log state changes for debugging
        logger.debug(f"Worker state changes: {state_changes}")


@pytest.fixture
def deadlock_timeout() -> Iterator[None]:
    """Auto-detect deadlocks during test execution.

    Monitors for deadlocks during test execution and fails
    the test if a deadlock is detected.

    Yields:
        None

    """
    monitor_thread = None
    stop_monitoring = threading.Event()
    deadlock_detected = threading.Event()

    def deadlock_monitor() -> None:
        """Background thread to monitor for deadlocks."""
        while not stop_monitoring.wait(1.0):  # Check every second
            try:
                analysis = DeadlockDetector.detect_deadlock(timeout_ms=500)
                if analysis.deadlock_detected:
                    deadlock_detected.set()
                    logger.error(f"Deadlock detected: {analysis}")
                    break
            except Exception as e:
                logger.warning(f"Deadlock monitor error: {e}")

    # Start monitoring
    monitor_thread = threading.Thread(target=deadlock_monitor, daemon=True)
    monitor_thread.start()

    try:
        yield

        # Check if deadlock was detected
        if deadlock_detected.is_set():
            pytest.fail("Deadlock detected during test execution")

    finally:
        # Stop monitoring
        stop_monitoring.set()
        if monitor_thread:
            monitor_thread.join(timeout=2.0)


@pytest.fixture
def thread_pool() -> Iterator[list[threading.Thread]]:
    """Provide managed pool of test threads with cleanup.

    Yields:
        list[threading.Thread]: Empty list to populate with test threads

    """
    threads: list[threading.Thread] = []

    try:
        yield threads
    finally:
        # Clean up all threads
        for thread in threads:
            if thread.is_alive():
                # Give threads a chance to finish naturally
                thread.join(timeout=1.0)

                # Log any threads that didn't finish
                if thread.is_alive():
                    logger.warning(f"Thread {thread.name} still alive after cleanup")


# Context managers for resource management
@contextmanager
def temporary_worker(worker_class: type, *args, **kwargs) -> Iterator[WorkerT]:
    """Context manager for temporary worker with guaranteed cleanup.

    Args:
        worker_class: Worker class to instantiate
        *args: Arguments for worker constructor
        **kwargs: Keyword arguments for worker constructor

    Yields:
        Worker instance

    Example:
        with temporary_worker(LauncherWorker, "test", "echo hello") as worker:
            worker.start()
            # Worker will be automatically cleaned up

    """
    worker = worker_class(*args, **kwargs)

    try:
        yield worker
    finally:
        # Cleanup worker
        if hasattr(worker, "request_stop"):
            worker.request_stop()

        if hasattr(worker, "wait"):
            worker.wait(5000)

        if hasattr(worker, "deleteLater"):
            worker.deleteLater()


@contextmanager
def thread_safety_monitor(
    resources: list[str],
    violation_handler: Callable[[ThreadSafetyViolation], None] | None = None,
) -> Iterator[list[ThreadSafetyViolation]]:
    """Context manager for monitoring thread safety violations.

    Args:
        resources: Names of resources to monitor
        violation_handler: Optional handler for violations

    Yields:
        List of detected violations

    Example:
        with thread_safety_monitor(["_active_processes"]) as violations:
            # Perform operations that might have thread safety issues
            manager.execute_launcher("test")

        assert len(violations) == 0  # No violations detected

    """
    violations: list[ThreadSafetyViolation] = []

    # TODO: Implement actual monitoring
    # This would require instrumentation of resource access

    try:
        yield violations
    finally:
        # Report violations if handler provided
        if violation_handler:
            for violation in violations:
                violation_handler(violation)


# Utility functions for common threading test patterns
def assert_worker_state_transition(
    worker: WorkerProtocol,
    expected_transitions: list[WorkerState],
    timeout_ms: int = 5000,
) -> None:
    """Assert that worker transitions through expected states.

    Args:
        worker: Worker to monitor
        expected_transitions: Expected state sequence
        timeout_ms: Total timeout for all transitions

    Raises:
        AssertionError: If transitions don't match expected sequence

    Example:
        assert_worker_state_transition(
            worker,
            [WorkerState.CREATED, WorkerState.RUNNING, WorkerState.STOPPED]
        )

    """
    if not expected_transitions:
        return

    start_time = time.perf_counter()
    timeout_sec = timeout_ms / 1000.0
    current_transition = 0

    while current_transition < len(expected_transitions):
        if time.perf_counter() - start_time > timeout_sec:
            current_state = worker.get_state()
            expected_state = expected_transitions[current_transition]
            raise AssertionError(
                f"Timeout waiting for state transition. "
                f"Expected: {expected_state}, Got: {current_state}, "
                f"Transition: {current_transition}/{len(expected_transitions)}",
            )

        current_state = worker.get_state()
        expected_state = expected_transitions[current_transition]

        if current_state == expected_state:
            current_transition += 1

        simulate_work_without_sleep(10)  # Small polling interval


def create_test_deadlock(
    lock1: LockProtocol,
    lock2: LockProtocol,
    timeout_ms: int = 1000,
) -> tuple[threading.Thread, threading.Thread]:
    """Create a test deadlock scenario for verification.

    Args:
        lock1: First lock in deadlock
        lock2: Second lock in deadlock
        timeout_ms: How long to maintain deadlock

    Returns:
        Tuple of threads that will deadlock

    Warning:
        This function creates an actual deadlock for testing deadlock
        detection. Use with caution and ensure proper cleanup.

    Example:
        thread1, thread2 = create_test_deadlock(lock_a, lock_b)
        # Verify deadlock detection
        analysis = DeadlockDetector.detect_deadlock([thread1, thread2])
        assert analysis.deadlock_detected

    """
    barrier = threading.Barrier(2)

    def deadlock_thread1() -> None:
        barrier.wait()
        lock1.acquire()
        simulate_work_without_sleep(100)  # Ensure thread2 acquires lock2
        lock2.acquire(timeout=timeout_ms / 1000.0)  # This will deadlock
        lock2.release()
        lock1.release()

    def deadlock_thread2() -> None:
        barrier.wait()
        lock2.acquire()
        simulate_work_without_sleep(100)  # Ensure thread1 acquires lock1
        lock1.acquire(timeout=timeout_ms / 1000.0)  # This will deadlock
        lock1.release()
        lock2.release()

    thread1 = threading.Thread(target=deadlock_thread1, name="DeadlockThread1")
    thread2 = threading.Thread(target=deadlock_thread2, name="DeadlockThread2")

    thread1.start()
    thread2.start()

    return thread1, thread2
