"""Example test file demonstrating UNIFIED_TESTING_GUIDE best practices."""

from __future__ import annotations

import subprocess
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy


try:
    from PIL import Image
except ImportError:
    Image = None

from typing import TYPE_CHECKING

from cache_manager import CacheManager

# Test doubles for behavior testing (UNIFIED_TESTING_GUIDE)
from tests.fixtures.doubles_library import TestShot, TestShotModel, TestSubprocess


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,
    pytest.mark.slow,  # CRITICAL for parallel safety
    pytest.mark.tutorial,
]

if TYPE_CHECKING:
    from pathlib import Path

# This file shows how to properly write tests using test doubles instead of mocks,
# following all principles from the guide:
# - Test behavior, not implementation
# - Use real components where possible
# - Mock only at system boundaries
# - Use test doubles for non-system components


class TestBehaviorNotImplementation:
    """Demonstrates testing behavior instead of implementation."""

    def test_shot_model_behavior(self) -> None:
        """Test actual behavior of shot model, not mock calls.

        ❌ BAD: Testing implementation
        with patch.object(model, '_parse_output') as mock_parse:
            model.refresh()
            # TODO: Test behavior instead of mock call
        # assert result.success is True  # Who cares?

        ✅ GOOD: Testing behavior (this example)
        """
        # Use test double instead of mock
        model = TestShotModel()

        # Add test data
        shot1 = TestShot("show1", "seq01", "0010")
        shot2 = TestShot("show1", "seq01", "0020")
        model.add_shot(shot1)
        model.add_shot(shot2)

        # Test behavior: model has shots
        assert len(model.get_shots()) == 2
        assert model.get_shots()[0].shot == "0010"
        assert model.get_shots()[1].shot == "0020"

        # Test signal emission (behavior)
        # TestShotModel from fixtures/doubles_library tracks emissions in signal_emissions dict
        assert model.signal_emissions["shots_updated"] == 2  # Emitted for each add


class TestRealComponentsOverMocks:
    """Demonstrates using real components instead of mocks."""

    def test_with_real_cache_manager(self, tmp_path: Path) -> None:
        """Use real CacheManager with temp directory instead of mocking.

        ❌ BAD: Mocking everything
        cache = TestCacheManager()
        cache.cache_thumbnail.return_value = "fake_path"

        ✅ GOOD: Real component with temp storage (this example)
        """
        # Use real cache manager with temp directory
        cache_dir = tmp_path / "cache"
        cache = CacheManager(cache_dir=cache_dir)

        # Test real caching behavior
        test_image = tmp_path / "test.jpg"

        # Create valid JPEG image
        try:
            img = Image.new("RGB", (100, 100), color="red")
            img.save(test_image, "JPEG")
        except ImportError:
            img = QImage(100, 100, QImage.Format.Format_RGB32)
            img.fill(QColor(255, 0, 0))
            img.save(str(test_image), "JPEG")

        # This actually caches the file - API expects Path not str
        cache.cache_thumbnail(
            source_path=test_image,  # Pass Path object directly
            show="test",
            sequence="seq01",
            shot="0010",
        )

        # Verify real behavior occurred
        cached_files = list(cache_dir.glob("**/*.jpg"))
        assert len(cached_files) > 0  # File was actually cached


class TestMockOnlyAtBoundaries:
    """Demonstrates mocking only at system boundaries."""

    def test_subprocess_at_boundary(self) -> None:
        """Mock subprocess (system boundary) but use real components elsewhere.

        System boundaries to mock:
        - subprocess.run (external process)
        - Network calls
        - File system (only when testing logic, not I/O)

        ✅ GOOD: This example mocks only subprocess
        """
        # Create test double for subprocess (system boundary)
        test_subprocess = TestSubprocess()
        # TestSubprocess uses direct properties, not set_success method
        test_subprocess.return_code = 0
        test_subprocess.stdout = "nuke\nmaya\n3de"
        test_subprocess.stderr = ""

        # Use real component with test double injected
        # In real code, we'd inject the subprocess dependency
        # For this example, we patch only at the boundary

        original_run = subprocess.run
        subprocess.run = test_subprocess.run

        try:
            # Test that subprocess was replaced - run a command
            result = subprocess.run(["echo", "test"], check=False, capture_output=True)

            # Verify the test double was used
            assert result.returncode == 0
            assert result.stdout == "nuke\nmaya\n3de"

        finally:
            # Restore original
            subprocess.run = original_run


class SignalDoubleTestingPatterns:
    """Demonstrates proper signal testing patterns."""

    def test_with_test_signal(self) -> None:
        """Use SignalDouble for test doubles.

        From UNIFIED_TESTING_GUIDE:
        - QSignalSpy only works with real Qt signals
        - SignalDouble for test doubles
        """
        # Create component with test signal
        # NOTE: Could use LauncherWorkerDouble from test doubles
        # from tests.test_doubles import LauncherWorkerDouble
        # worker = LauncherWorkerDouble(launcher_id="test_123", command="echo test")
        from tests.fixtures.doubles_library import (
            SignalDouble,
        )

        class TestLauncherWorker:
            def __init__(self, launcher_id, command) -> None:
                self.launcher_id = launcher_id
                self.command = command
                self.output = SignalDouble()
                self.started = SignalDouble()
                self.finished = SignalDouble()

            def start(self) -> None:
                self.started.emit()
                self.output.emit(self.launcher_id, "Test output")
                self.finished.emit()

        worker = TestLauncherWorker(launcher_id="test_123", command="echo test")

        # Connect to test signal
        outputs = []
        worker.output.connect(lambda lid, msg: outputs.append((lid, msg)))

        # Trigger behavior
        worker.start()

        # Verify signal was emitted
        assert worker.started.was_emitted
        assert worker.finished.was_emitted
        assert len(outputs) == 1
        assert outputs[0] == ("test_123", "Test output")

    def test_with_real_qt_signal(self, qtbot) -> None:
        """Use QSignalSpy with real Qt components.

        ✅ CORRECT: QSignalSpy with real Qt object
        """

        class RealQtComponent(QObject):
            data_changed = Signal(str)

            def update_data(self, value: str) -> None:
                self.data_changed.emit(value)

        # Create real Qt component
        component = RealQtComponent()
        # Note: RealQtComponent is QObject, not QWidget - no qtbot.addWidget() needed

        # Use QSignalSpy for real Qt signals
        spy = QSignalSpy(component.data_changed)

        # Trigger behavior
        component.update_data("test_value")

        # Verify with QSignalSpy
        assert spy.count() == 1
        assert spy.at(0)[0] == "test_value"


class TestNoSleepPattern:
    """Demonstrates alternatives to time.sleep()."""

    def test_qt_event_processing(self) -> None:
        """Use Qt event processing instead of sleep.

        ❌ BAD: time.sleep(0.1)
        ✅ GOOD: QCoreApplication.processEvents()
        """
        # Process Qt events instead of sleeping
        app = QCoreApplication.instance()
        if app:
            # Process events multiple times for thorough processing
            for _ in range(10):
                app.processEvents()

    def test_with_synchronization(self) -> None:
        """Use proper synchronization instead of sleep.

        ❌ BAD: time.sleep(0.5)  # Wait for thread
        ✅ GOOD: Use Events, Barriers, or Conditions
        """
        # Use Event for synchronization
        ready = threading.Event()

        def worker() -> None:
            # Do work
            ready.set()  # Signal ready

        thread = threading.Thread(target=worker)
        thread.start()

        # Wait for signal instead of sleep
        ready.wait(timeout=1.0)
        thread.join()


class TestIntegrationExample:
    """Demonstrates integration testing with minimal mocking."""

    def test_complete_workflow(self, tmp_path: Path) -> None:
        """Test complete workflow with real components.

        Only mock at system boundaries (subprocess).
        Everything else uses real components or test doubles.
        """
        # Setup real components
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cache = CacheManager(cache_dir=cache_dir)

        # Use test doubles for models
        shot_model = TestShotModel()
        shot_model.add_shot(TestShot("show1", "seq01", "0010"))

        # Test double for subprocess (system boundary)
        test_subprocess = TestSubprocess()
        # TestSubprocess uses direct properties
        test_subprocess.return_code = 0
        test_subprocess.stdout = ""
        test_subprocess.stderr = ""

        # Integration: components work together
        shots = shot_model.get_shots()
        assert len(shots) == 1

        # Cache would work with real files
        test_file = tmp_path / "test.jpg"

        # Create valid JPEG image
        try:
            img = Image.new("RGB", (100, 100), color="blue")
            img.save(test_file, "JPEG")
        except ImportError:
            img = QImage(100, 100, QImage.Format.Format_RGB32)
            img.fill(QColor(0, 0, 255))
            img.save(str(test_file), "JPEG")

        cached = cache.cache_thumbnail(
            test_file,  # Pass Path object directly, not str
            shots[0].show,
            shots[0].sequence,
            shots[0].shot,
        )

        # Verify integration
        assert cached is not None  # Real caching occurred


# Fixture examples following best practices
@pytest.fixture
def real_cache_manager(tmp_path: Path):
    """Provide real CacheManager with temp storage.

    Best practice: Use real components with temp directories.
    """
    cache_dir = tmp_path / "test_cache"
    cache_dir.mkdir()
    return CacheManager(cache_dir=cache_dir)


@pytest.fixture
def test_shot_factory():
    """Factory for creating test shots.

    Best practice: Factory fixtures for test data.
    """

    def make_shot(show="test", seq="seq01", shot="0010"):
        return TestShot(show, seq, shot)

    return make_shot


@pytest.fixture
def test_subprocess():
    """Provide test subprocess double.

    Best practice: Test doubles for system boundaries.
    """
    return TestSubprocess()
