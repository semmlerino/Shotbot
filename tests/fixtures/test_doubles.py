"""Test doubles - re-export shim for backward compatibility.

All test doubles have been consolidated into domain-specific modules:
- model_fixtures:   SignalDouble, TestShot, TestShotModel, TestCacheManager,
                    FakeShotModel, FakePreviousShotsFinder,
                    FakePreviousShotsWorker, create_test_shot, create_test_shots
- process_fixtures: TestProcessPool, TestCompletedProcess, PopenDouble,
                    SubprocessMock, simulate_work_without_sleep, test_process_pool

Import directly from domain modules for new code.
Removed in cleanup:
- TestFileSystem → use make_test_filesystem fixture in environment_fixtures
- TestProgressContext → use MagicMock()
- MainWindowTestProgressManager → use MagicMock()
- TestNotificationManager → use MagicMock()
- TestMessageBox → use DialogRecorder or MagicMock()
- ProgressOperationDouble → use MagicMock()
"""

from __future__ import annotations

from tests.fixtures.model_fixtures import (
    FakePreviousShotsFinder,
    FakePreviousShotsWorker,
    FakeShotModel,
    SignalDouble,
    TestCacheManager,
    TestShot,
    TestShotModel,
    create_test_shot,
    create_test_shots,
)
from tests.fixtures.process_fixtures import (
    PopenDouble,
    TestCompletedProcess,
    TestProcessPool,
    simulate_work_without_sleep,
    test_process_pool,
)


__all__ = [
    "FakePreviousShotsFinder",
    "FakePreviousShotsWorker",
    "FakeShotModel",
    "PopenDouble",
    "SignalDouble",
    "TestCacheManager",
    "TestCompletedProcess",
    "TestProcessPool",
    "TestShot",
    "TestShotModel",
    "create_test_shot",
    "create_test_shots",
    "simulate_work_without_sleep",
    "test_process_pool",
]
