"""Test doubles - re-export shim for backward compatibility.

All test doubles have been split into domain-specific modules:
- signal_doubles: SignalDouble
- process_doubles: TestProcessPool, TestCompletedProcess, TestSubprocess, PopenDouble,
                   simulate_work_without_sleep
- model_doubles: TestShot, TestShotModel, TestCacheManager, TestFileSystem,
                 FakeShotModel, FakePreviousShotsFinder, FakeCacheManager,
                 FakePreviousShotsWorker, shot_model_factory,
                 create_test_shot, create_test_shots
- cache_doubles: TestProgressOperation, TestProgressManager, test_process_pool

Import directly from domain modules for new code.
"""

from __future__ import annotations

from tests.fixtures.cache_doubles import (
    TestProgressManager,
    TestProgressOperation,
    test_process_pool,
)
from tests.fixtures.model_doubles import (
    FakeCacheManager,
    FakePreviousShotsFinder,
    FakePreviousShotsWorker,
    FakeShotModel,
    TestCacheManager,
    TestFileSystem,
    TestShot,
    TestShotModel,
    create_test_shot,
    create_test_shots,
    shot_model_factory,
)
from tests.fixtures.process_doubles import (
    PopenDouble,
    TestCompletedProcess,
    TestProcessPool,
    TestSubprocess,
    simulate_work_without_sleep,
)
from tests.fixtures.signal_doubles import (
    SignalDouble,
)


__all__ = [
    "FakeCacheManager",
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
    "shot_model_factory",
    "simulate_work_without_sleep",
    "test_process_pool",
]
