"""Test doubles - re-export shim for backward compatibility.

All test doubles have been consolidated into domain-specific modules:
- model_fixtures:   SignalDouble, TestShot, TestShotModel, TestCacheManager,
                    TestFileSystem, FakeShotModel, FakePreviousShotsFinder,
                    FakePreviousShotsWorker, create_test_shot, create_test_shots
- process_fixtures: TestProcessPool, TestCompletedProcess, TestSubprocess,
                    PopenDouble, simulate_work_without_sleep,
                    TestProgressManager, TestProgressOperation, test_process_pool

Import directly from domain modules for new code.
"""

from __future__ import annotations

from tests.fixtures.model_fixtures import (
    FakePreviousShotsFinder,
    FakePreviousShotsWorker,
    FakeShotModel,
    SignalDouble,
    TestCacheManager,
    TestFileSystem,
    TestShot,
    TestShotModel,
    create_test_shot,
    create_test_shots,
)
from tests.fixtures.process_fixtures import (
    PopenDouble,
    TestCompletedProcess,
    TestProcessPool,
    TestProgressManager,
    TestProgressOperation,
    TestSubprocess,
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
    "TestFileSystem",
    "TestProcessPool",
    "TestProgressManager",
    "TestProgressOperation",
    "TestShot",
    "TestShotModel",
    "TestSubprocess",
    "create_test_shot",
    "create_test_shots",
    "simulate_work_without_sleep",
    "test_process_pool",
]
