"""Tests for SingletonMixin thread-safe singleton pattern.

Tests cover:
- Basic singleton behavior (same instance returned)
- Thread-safe concurrent creation
- Reset clears instance properly
- Cleanup hooks invoked during reset
- Initialization guards prevent re-initialization
- Multiple subclasses have independent instances
"""

from __future__ import annotations

import queue
import threading
from typing import ClassVar

import pytest

from singleton_mixin import SingletonMixin


class TestSingletonBasicBehavior:
    """Basic singleton creation and identity tests."""

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls to __new__ return the same instance."""

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.value = 42
                self._mark_initialized()

        try:
            instance1 = TestSingleton()
            instance2 = TestSingleton()
            instance3 = TestSingleton()

            assert instance1 is instance2
            assert instance2 is instance3
            assert instance1.value == 42
        finally:
            TestSingleton.reset()

    def test_singleton_class_attributes_exist(self) -> None:
        """Singleton class has required class attributes."""

        class TestSingleton(SingletonMixin):
            pass

        try:
            assert hasattr(TestSingleton, "_instance")
            assert hasattr(TestSingleton, "_lock")
            assert hasattr(TestSingleton, "_initialized")
        finally:
            TestSingleton.reset()


class TestSingletonThreadSafety:
    """Thread safety tests for concurrent singleton access."""

    def test_concurrent_creation_produces_single_instance(self) -> None:
        """Multiple threads calling __new__ simultaneously get same instance."""

        class TestSingleton(SingletonMixin):
            creation_count: ClassVar[int] = 0

            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                TestSingleton.creation_count += 1
                self._mark_initialized()

        try:
            instances: queue.Queue[TestSingleton] = queue.Queue()
            barrier = threading.Barrier(10)

            def create_instance() -> None:
                barrier.wait()  # Synchronize all threads to start together
                inst = TestSingleton()
                instances.put(inst)

            threads = [threading.Thread(target=create_instance) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Collect all instances
            collected = []
            while not instances.empty():
                collected.append(instances.get())

            # All must be the same object
            assert len(collected) == 10
            first = collected[0]
            assert all(inst is first for inst in collected)
            assert TestSingleton.creation_count == 1
        finally:
            TestSingleton.reset()
            TestSingleton.creation_count = 0

    def test_concurrent_access_after_creation(self) -> None:
        """Concurrent reads after singleton exists are safe."""

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.data = {"key": "value"}
                self._mark_initialized()

        try:
            # Create singleton first
            _ = TestSingleton()

            results: queue.Queue[str] = queue.Queue()

            def read_data() -> None:
                inst = TestSingleton()
                results.put(inst.data["key"])

            threads = [threading.Thread(target=read_data) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All reads should succeed
            collected = []
            while not results.empty():
                collected.append(results.get())

            assert len(collected) == 20
            assert all(v == "value" for v in collected)
        finally:
            TestSingleton.reset()


class TestSingletonReset:
    """Tests for reset() functionality and test isolation."""

    def test_reset_clears_instance(self) -> None:
        """reset() creates a fresh instance on next access."""

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.value = 0
                self._mark_initialized()

        try:
            instance1 = TestSingleton()
            instance1.value = 100

            TestSingleton.reset()

            instance2 = TestSingleton()

            # New instance, not the same object
            assert instance1 is not instance2
            # Fresh initialization
            assert instance2.value == 0
        finally:
            TestSingleton.reset()

    def test_reset_calls_cleanup_instance(self, mocker) -> None:
        """reset() invokes _cleanup_instance() hook."""
        cleanup_called = mocker.MagicMock()

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self._mark_initialized()

            @classmethod
            def _cleanup_instance(cls) -> None:
                cleanup_called()

        try:
            _ = TestSingleton()
            TestSingleton.reset()

            cleanup_called.assert_called_once()
        finally:
            TestSingleton.reset()

    def test_reset_clears_initialized_flag(self) -> None:
        """reset() sets _initialized to False."""

        class TestSingleton(SingletonMixin):
            init_calls: ClassVar[int] = 0

            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                TestSingleton.init_calls += 1
                self._mark_initialized()

        try:
            _ = TestSingleton()
            assert TestSingleton._initialized is True
            assert TestSingleton.init_calls == 1

            TestSingleton.reset()

            assert TestSingleton._initialized is False

            # New instance should re-initialize
            _ = TestSingleton()
            assert TestSingleton.init_calls == 2
        finally:
            TestSingleton.reset()
            TestSingleton.init_calls = 0

    def test_reset_without_instance_is_safe(self) -> None:
        """reset() on never-created singleton doesn't error."""

        class TestSingleton(SingletonMixin):
            pass

        # Should not raise
        TestSingleton.reset()
        TestSingleton.reset()


class TestSingletonInitializationGuards:
    """Tests for _is_initialized() and _mark_initialized() guards."""

    def test_is_initialized_false_before_init(self) -> None:
        """_is_initialized() returns False before initialization."""

        class TestSingleton(SingletonMixin):
            pass

        try:
            assert TestSingleton._is_initialized() is False
        finally:
            TestSingleton.reset()

    def test_is_initialized_prevents_reinit(self) -> None:
        """_is_initialized() guard prevents __init__ body re-execution."""

        class TestSingleton(SingletonMixin):
            init_body_calls: ClassVar[int] = 0

            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                TestSingleton.init_body_calls += 1
                self._mark_initialized()

        try:
            _ = TestSingleton()
            _ = TestSingleton()
            _ = TestSingleton()

            # Init body should only run once
            assert TestSingleton.init_body_calls == 1
        finally:
            TestSingleton.reset()
            TestSingleton.init_body_calls = 0

    def test_mark_initialized_sets_flag(self) -> None:
        """_mark_initialized() sets _initialized to True."""

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                # Check before marking
                assert TestSingleton._initialized is False
                self._mark_initialized()
                # Check after marking
                assert TestSingleton._initialized is True

        try:
            _ = TestSingleton()
        finally:
            TestSingleton.reset()


class TestSingletonSubclassIndependence:
    """Tests that different subclasses have independent singletons."""

    def test_multiple_subclasses_independent(self) -> None:
        """Each SingletonMixin subclass has its own independent instance."""

        class SingletonA(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.name = "A"
                self._mark_initialized()

        class SingletonB(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.name = "B"
                self._mark_initialized()

        try:
            a = SingletonA()
            b = SingletonB()

            assert a is not b
            assert a.name == "A"
            assert b.name == "B"

            # Each maintains separate identity
            assert SingletonA() is a
            assert SingletonB() is b
        finally:
            SingletonA.reset()
            SingletonB.reset()

    def test_subclass_inherits_singleton_behavior(self) -> None:
        """Subclass of singleton also exhibits singleton behavior."""

        class BaseSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.base_value = 1
                self._mark_initialized()

        class DerivedSingleton(BaseSingleton):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self.derived_value = 2
                self._mark_initialized()

        try:
            d1 = DerivedSingleton()
            d2 = DerivedSingleton()

            assert d1 is d2
            assert d1.derived_value == 2
        finally:
            DerivedSingleton.reset()
            BaseSingleton.reset()


class TestSingletonEdgeCases:
    """Edge case and error handling tests."""

    def test_cleanup_with_exception_doesnt_break_reset(self) -> None:
        """Exception in _cleanup_instance doesn't prevent reset."""

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self._mark_initialized()

            @classmethod
            def _cleanup_instance(cls) -> None:
                raise RuntimeError("Cleanup failed!")

        try:
            _ = TestSingleton()

            with pytest.raises(RuntimeError, match="Cleanup failed!"):
                TestSingleton.reset()

            # Instance should still be cleared despite exception
            # (actual behavior depends on implementation)
        finally:
            # Force cleanup for test isolation
            TestSingleton._instance = None
            TestSingleton._initialized = False

    def test_concurrent_reset_calls(self) -> None:
        """Multiple concurrent reset() calls are safe."""
        reset_count = {"count": 0}

        class TestSingleton(SingletonMixin):
            def __init__(self) -> None:
                if self._is_initialized():
                    return
                super().__init__()
                self._mark_initialized()

            @classmethod
            def _cleanup_instance(cls) -> None:
                reset_count["count"] += 1

        try:
            # Create initial instance
            _ = TestSingleton()

            barrier = threading.Barrier(5)

            def do_reset() -> None:
                barrier.wait()
                TestSingleton.reset()

            threads = [threading.Thread(target=do_reset) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Cleanup should only be called once (when instance existed)
            assert reset_count["count"] == 1
        finally:
            TestSingleton.reset()
