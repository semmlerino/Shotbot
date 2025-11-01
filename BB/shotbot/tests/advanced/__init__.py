"""Advanced testing suite for ShotBot application.

This package contains advanced testing approaches including:
- Property-based testing with Hypothesis
- Mutation testing strategies
- Contract validation
- Snapshot testing
- Performance regression testing
- Test quality improvement patterns
"""

# Only import modules that have their dependencies installed
import importlib.util

# Check if property-based testing module is available
spec = importlib.util.find_spec("tests.advanced.test_property_based")
PROPERTY_BASED_AVAILABLE = spec is not None

# The following modules require additional dependencies (psutil, etc.)
# and are not imported by default to avoid import errors.
# Uncomment and install dependencies if you want to use them:

# from .test_mutation_strategies import (
#     MutationStrategy,
#     MutationTestRunner,
#     TestQualityAnalyzer,
#     SHOTBOT_MUTATION_CONFIGS,
# )

# from .test_contract_validation import (
#     Contract,
#     SignalContract,
#     ContractValidator,
#     ContractMonitor,
#     ModelContract,
#     CacheContract,
#     FinderContract,
#     LauncherContract,
# )

# from .test_snapshot import (
#     Snapshot,
#     SnapshotStore,
#     UISnapshotCapture,
#     CacheSnapshot,
#     ConfigSnapshot,
#     SnapshotAssertion,
# )

# from .test_performance_regression import (
#     PerformanceBenchmark,
#     MemoryLeakDetector,
#     PerformanceBaseline,
#     PerformanceReporter,
#     CIPerformanceMonitor,
# )

# from .test_quality_patterns import (
#     ShotFactory,
#     ThreeDESceneFactory,
#     LauncherFactory,
#     PathFactory,
#     ShotModelBuilder,
#     CacheBuilder,
#     IsolatedTest,
#     MockBuilder,
# )

# Only export what's available
__all__ = ["PROPERTY_BASED_AVAILABLE"]
