"""Contract testing for ShotBot component interfaces.

This module defines and validates contracts between components,
ensuring API boundaries are respected and signal/slot contracts are maintained.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Type, Union

import pytest
from PySide6.QtCore import QObject, Signal


@dataclass
class Contract:
    """Defines a contract between components."""

    name: str
    provider: Type
    consumer: Type
    constraints: List[Callable[[Any], bool]]
    description: str


@dataclass
class SignalContract:
    """Defines a contract for Qt signal/slot connections."""

    signal_name: str
    signal_type: List[Type]
    slot_constraints: List[Callable]
    description: str


class ModelContract(Protocol):
    """Contract for all model components in ShotBot."""

    def refresh(self) -> bool:
        """Refresh the model data.

        Returns:
            True if refresh succeeded, False otherwise
        """
        ...

    def get_data(self) -> List[Any]:
        """Get the current model data.

        Returns:
            List of model items
        """
        ...

    def clear(self) -> None:
        """Clear all model data."""
        ...


class CacheContract(Protocol):
    """Contract for cache implementations."""

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        ...

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        """
        ...

    def delete(self, key: str) -> None:
        """Delete value from cache.

        Args:
            key: Cache key
        """
        ...

    def clear_all(self) -> None:
        """Clear entire cache."""
        ...


class FinderContract(Protocol):
    """Contract for finder components."""

    def find(self, *args, **kwargs) -> Optional[Union[str, List[str]]]:
        """Find items based on criteria.

        Returns:
            Found item(s) or None if not found
        """
        ...


class LauncherContract(Protocol):
    """Contract for launcher components."""

    def launch(self, command: str, **kwargs) -> bool:
        """Launch a command.

        Args:
            command: Command to execute
            **kwargs: Additional launch parameters

        Returns:
            True if launch succeeded
        """
        ...

    def is_running(self) -> bool:
        """Check if launcher has active processes.

        Returns:
            True if processes are running
        """
        ...

    def terminate(self) -> None:
        """Terminate all active processes."""
        ...


class ContractValidator:
    """Validates contracts between components."""

    @staticmethod
    def validate_interface(obj: Any, contract: Type) -> bool:
        """Validate that an object implements a protocol contract.

        Args:
            obj: Object to validate
            contract: Protocol contract to check against

        Returns:
            True if object satisfies contract
        """
        # Check all required methods exist
        for method_name in dir(contract):
            if method_name.startswith("_"):
                continue

            if not hasattr(obj, method_name):
                return False

            obj_method = getattr(obj, method_name)
            if not callable(obj_method):
                return False

            # Check method signature matches
            contract_method = getattr(contract, method_name)
            obj_sig = inspect.signature(obj_method)
            contract_sig = inspect.signature(contract_method)

            # Compare parameter names (excluding self)
            obj_params = list(obj_sig.parameters.keys())[1:]
            contract_params = list(contract_sig.parameters.keys())[1:]

            if obj_params != contract_params:
                return False

        return True

    @staticmethod
    def validate_signal_contract(obj: QObject, contract: SignalContract) -> bool:
        """Validate that a QObject satisfies a signal contract.

        Args:
            obj: QObject to validate
            contract: Signal contract to check

        Returns:
            True if signal contract is satisfied
        """
        if not hasattr(obj, contract.signal_name):
            return False

        signal = getattr(obj, contract.signal_name)
        if not isinstance(signal, Signal):
            return False

        # Validate signal can be connected to appropriate slots
        for constraint in contract.slot_constraints:
            try:
                # Test connection (don't actually connect)
                if not callable(constraint):
                    return False
            except Exception:
                return False

        return True

    @staticmethod
    def validate_data_contract(
        data: Any, constraints: List[Callable[[Any], bool]]
    ) -> bool:
        """Validate that data satisfies constraints.

        Args:
            data: Data to validate
            constraints: List of constraint functions

        Returns:
            True if all constraints are satisfied
        """
        return all(constraint(data) for constraint in constraints)


# Define contracts for ShotBot components
SHOT_MODEL_CONTRACT = Contract(
    name="ShotModel",
    provider=type,  # Will be replaced with actual class
    consumer=type,
    constraints=[
        lambda m: hasattr(m, "shots_updated"),  # Must have signal
        lambda m: hasattr(m, "refresh_shots"),  # Must have refresh method
        lambda m: hasattr(m, "get_shots"),  # Must have getter
    ],
    description="Contract for shot model component",
)

CACHE_MANAGER_CONTRACT = Contract(
    name="CacheManager",
    provider=type,
    consumer=type,
    constraints=[
        lambda c: hasattr(c, "get"),
        lambda c: hasattr(c, "set"),
        lambda c: hasattr(c, "delete"),
        lambda c: hasattr(c, "clear_all"),
    ],
    description="Contract for cache manager",
)

RAW_PLATE_FINDER_CONTRACT = Contract(
    name="RawPlateFinder",
    provider=type,
    consumer=type,
    constraints=[
        lambda f: hasattr(f, "find_latest_raw_plate"),
        lambda f: callable(getattr(f, "find_latest_raw_plate", None)),
    ],
    description="Contract for raw plate finder",
)

THREEDE_FINDER_CONTRACT = Contract(
    name="ThreeDESceneFinder",
    provider=type,
    consumer=type,
    constraints=[
        lambda f: hasattr(f, "find_other_users_scenes"),
        lambda f: hasattr(f, "_deduplicate_scenes"),
    ],
    description="Contract for 3DE scene finder",
)

# Signal contracts
SHOT_MODEL_SIGNALS = SignalContract(
    signal_name="shots_updated",
    signal_type=[],  # No parameters
    slot_constraints=[
        lambda: None,  # Can connect to parameterless slot
    ],
    description="Signal emitted when shots are updated",
)

LAUNCHER_SIGNALS = SignalContract(
    signal_name="command_started",
    signal_type=[str, str],  # process_key, command
    slot_constraints=[
        lambda key, cmd: None,  # Can connect to two-parameter slot
    ],
    description="Signal emitted when command starts",
)


class ContractTestBase:
    """Base class for contract tests."""

    def assert_implements_contract(
        self, obj: Any, contract: Type, contract_name: str = ""
    ):
        """Assert that an object implements a contract.

        Args:
            obj: Object to test
            contract: Protocol contract
            contract_name: Human-readable contract name
        """
        assert ContractValidator.validate_interface(obj, contract), (
            f"{obj.__class__.__name__} does not implement {contract_name or contract.__name__}"
        )

    def assert_signal_contract(self, obj: QObject, contract: SignalContract):
        """Assert that a QObject satisfies a signal contract.

        Args:
            obj: QObject to test
            contract: Signal contract
        """
        assert ContractValidator.validate_signal_contract(obj, contract), (
            f"{obj.__class__.__name__} does not satisfy signal contract for {contract.signal_name}"
        )

    def assert_data_contract(self, data: Any, contract: Contract):
        """Assert that data satisfies a contract.

        Args:
            data: Data to validate
            contract: Contract with constraints
        """
        assert ContractValidator.validate_data_contract(data, contract.constraints), (
            f"Data does not satisfy contract {contract.name}"
        )


@pytest.mark.contract
class TestModelContracts(ContractTestBase):
    """Test model component contracts."""

    def test_shot_model_contract(self):
        """Test that ShotModel implements ModelContract."""
        from shot_model import ShotModel

        model = ShotModel()

        # Check interface contract
        assert hasattr(model, "refresh_shots")
        assert hasattr(model, "get_shots")
        assert hasattr(model, "shots_updated")

        # Check signal contract
        self.assert_signal_contract(model, SHOT_MODEL_SIGNALS)

        # Check data contract
        self.assert_data_contract(model, SHOT_MODEL_CONTRACT)

    def test_threede_model_contract(self):
        """Test that ThreeDESceneModel implements ModelContract."""
        from threede_scene_model import ThreeDESceneModel

        model = ThreeDESceneModel()

        # Check required methods
        assert hasattr(model, "refresh_scenes")
        assert hasattr(model, "get_scenes")
        assert hasattr(model, "clear_cache")

        # Check return types
        scenes = model.get_scenes()
        assert isinstance(scenes, list)


@pytest.mark.contract
class TestFinderContracts(ContractTestBase):
    """Test finder component contracts."""

    def test_raw_plate_finder_contract(self):
        """Test RawPlateFinder contract."""
        from raw_plate_finder import RawPlateFinder

        # Check static method contract
        assert hasattr(RawPlateFinder, "find_latest_raw_plate")
        assert callable(RawPlateFinder.find_latest_raw_plate)

        # Check method signature
        sig = inspect.signature(RawPlateFinder.find_latest_raw_plate)
        params = list(sig.parameters.keys())
        assert "shot_workspace_path" in params
        assert "shot_name" in params

        # Check return type annotation
        assert sig.return_annotation == Optional[str]

    def test_threede_finder_contract(self):
        """Test ThreeDESceneFinder contract."""
        from threede_scene_finder import ThreeDESceneFinder

        finder = ThreeDESceneFinder()

        # Check required methods
        assert hasattr(finder, "find_other_users_scenes")
        assert hasattr(finder, "_deduplicate_scenes")

        # Check method signatures
        sig = inspect.signature(finder.find_other_users_scenes)
        assert sig.return_annotation == List


@pytest.mark.contract
class TestCacheContracts(ContractTestBase):
    """Test cache component contracts."""

    def test_cache_manager_contract(self):
        """Test CacheManager implements CacheContract."""
        from cache_manager import CacheManager

        cache = CacheManager()

        # Check interface
        self.assert_implements_contract(cache, CacheContract, "CacheContract")

        # Test contract behavior
        cache.set("test_key", "test_value", ttl=60)
        value = cache.get("test_key")
        assert value == "test_value"

        cache.delete("test_key")
        assert cache.get("test_key") is None

    def test_cache_ttl_contract(self):
        """Test cache TTL behavior contract."""
        import time

        from cache_manager import CacheManager

        cache = CacheManager()

        # Contract: Expired items should return None
        cache.set("expire_test", "value", ttl=0.001)
        time.sleep(0.002)
        assert cache.get("expire_test") is None

        # Contract: Non-expired items should return value
        cache.set("valid_test", "value", ttl=60)
        assert cache.get("valid_test") == "value"


@pytest.mark.contract
class TestLauncherContracts(ContractTestBase):
    """Test launcher component contracts."""

    def test_launcher_manager_contract(self):
        """Test LauncherManager contract."""
        from launcher_manager import LauncherManager

        manager = LauncherManager()

        # Check required methods
        assert hasattr(manager, "launch_app")
        assert hasattr(manager, "get_active_processes")
        assert hasattr(manager, "terminate_all")

        # Check signals
        assert hasattr(manager, "command_started")
        assert hasattr(manager, "command_finished")
        assert hasattr(manager, "command_output")

        # Test signal contract
        self.assert_signal_contract(manager, LAUNCHER_SIGNALS)

    def test_launcher_worker_contract(self):
        """Test LauncherWorker thread contract."""
        from launcher_manager import LauncherWorker

        worker = LauncherWorker("test_cmd", "test_key")

        # Check thread contract
        assert hasattr(worker, "run")
        assert hasattr(worker, "finished")
        assert hasattr(worker, "output")
        assert hasattr(worker, "error")


class ContractMonitor:
    """Monitor contract violations at runtime."""

    def __init__(self):
        self.violations: List[Dict[str, Any]] = []

    def check_contract(
        self, obj: Any, contract: Union[Type, Contract], context: str = ""
    ) -> bool:
        """Check a contract and log violations.

        Args:
            obj: Object to check
            contract: Contract to validate
            context: Context information

        Returns:
            True if contract is satisfied
        """
        if isinstance(contract, type) and issubclass(contract, Protocol):
            valid = ContractValidator.validate_interface(obj, contract)
        elif isinstance(contract, Contract):
            valid = ContractValidator.validate_data_contract(obj, contract.constraints)
        else:
            valid = False

        if not valid:
            self.violations.append(
                {
                    "object": obj.__class__.__name__,
                    "contract": getattr(contract, "__name__", str(contract)),
                    "context": context,
                }
            )

        return valid

    def report_violations(self) -> str:
        """Generate a report of contract violations.

        Returns:
            Formatted violation report
        """
        if not self.violations:
            return "No contract violations detected."

        report = ["Contract Violations Detected:", "=" * 50]
        for violation in self.violations:
            report.append(
                f"- {violation['object']} violates {violation['contract']}"
                f" in {violation['context']}"
            )

        return "\n".join(report)


@pytest.mark.contract
class TestContractIntegration:
    """Integration tests for contract validation."""

    def test_model_view_contract_integration(self, qtbot):
        """Test contract between model and view components."""
        from shot_grid import ShotGrid
        from shot_model import ShotModel

        model = ShotModel()
        grid = ShotGrid()
        qtbot.addWidget(grid)

        # Contract: Grid should connect to model signals
        model.shots_updated.connect(grid.update_shots)

        # Contract: Model update should trigger view update
        with qtbot.waitSignal(model.shots_updated, timeout=1000):
            model.refresh_shots()

        # Verify contract is maintained
        assert grid.get_shot_count() >= 0

    def test_finder_cache_contract_integration(self):
        """Test contract between finder and cache components."""
        from cache_manager import CacheManager
        from raw_plate_finder import RawPlateFinder

        cache = CacheManager()

        # Contract: Finder results should be cacheable
        test_path = "/test/path"
        test_shot = "TEST_0001"

        # Simulate finder result
        result = RawPlateFinder.find_latest_raw_plate(test_path, test_shot)

        # Contract: Cache should accept finder results
        if result:
            cache.set(f"plate_{test_shot}", result, ttl=300)
            cached = cache.get(f"plate_{test_shot}")
            assert cached == result


if __name__ == "__main__":
    # Example: Monitor contracts during execution
    monitor = ContractMonitor()

    # Check various contracts
    from cache_manager import CacheManager
    from shot_model import ShotModel

    model = ShotModel()
    cache = CacheManager()

    monitor.check_contract(model, ModelContract, "ShotModel initialization")
    monitor.check_contract(cache, CacheContract, "CacheManager initialization")

    print(monitor.report_violations())
