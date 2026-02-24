# threading_test_utils.py

Low-level threading primitives for testing thread safety: `ThreadingTestHelpers`,
`RaceConditionFactory`, `DeadlockDetector`, `PerformanceMetrics`.

**Note**: The `isolated_launcher_manager` and `monitored_worker` fixtures require
`launcher.py` and `launcher_manager.py` which are not present in the codebase.
Those fixtures will fail with `ImportError` at collection time.

The remaining utilities (`ThreadingTestHelpers.wait_for_worker_state`,
`DeadlockDetector.detect_deadlock`, `PerformanceMetrics.measure_thread_creation`,
`RaceConditionFactory.create_state_race`) work against any `QThread` subclass and
`threading.Lock`.

For current thread testing patterns, see `tests/helpers/qt_thread_cleanup.py`
and `UNIFIED_TESTING_V2.md`.