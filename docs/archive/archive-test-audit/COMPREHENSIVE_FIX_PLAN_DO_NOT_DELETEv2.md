# Comprehensive Fix Plan for ShotBot Application - DO NOT DELETE v2
**Date**: 2025-08-27  
**Timeline**: 10-12 Weeks  
**Approach**: Systematic, Phased, Test-Driven  
**Goal**: Transform from critical state to production-ready

---

## 📋 Executive Overview

This document provides a detailed, actionable plan to thoroughly fix all critical issues identified in the ShotBot application. The plan addresses stability, type safety, test coverage, code quality, and architectural problems through a systematic 6-phase approach over 10-12 weeks.

### Current State vs Target State

| Metric | Current State | Target State | 
|--------|--------------|--------------|
| Stability Issues | Race conditions, deadlock risks | Robust concurrent operation |
| Type Errors | 2,054 errors | 0 errors |
| Test Coverage | 9.8% | 70% overall, 90% critical paths |
| Largest File | 2,029 lines | <500 lines |
| Code Duplication | ~25% | <5% |
| Architecture Score | D+ | A- |

---

## 🚀 Phase 1: Critical Stability Improvements (Weeks 1-2)

### Objective
Stabilize the application and improve reliability for robust operation.

### Week 1: Stability and Reliability Improvements

#### Day 1-2: Core Stability Fixes
```python
# Task 1: Complete secure_command_executor integration in command_launcher.py
# Replace all instances of:
subprocess.Popen(["/bin/bash", "-i", "-c", full_command])

# With:
from secure_command_executor import get_secure_executor
executor = get_secure_executor()
result = executor.execute(command, allow_workspace_function=True)
```

**Specific Changes Required:**
1. `command_launcher.py`:
   - Lines 240-270: Replace workspace command execution
   - Lines 305-337: Replace 3DE launch logic
   - Lines 450-483: Replace general app launching

2. `launcher_manager.py`:
   - Lines 1014-1037: Remove terminal command construction
   - Line 183: Replace subprocess.Popen with secure executor
   - Lines 63-156: Integrate with secure validation

3. **Delete entirely**: `persistent_bash_session.py`
   ```bash
   # Remove the vulnerable component
   git rm persistent_bash_session.py
   
   # Update all imports
   grep -r "persistent_bash_session" . --include="*.py" | cut -d: -f1 | xargs -I {} sed -i 's/from persistent_bash_session/from secure_command_executor/g' {}
   ```

#### Day 3-4: Stability Validation Suite
```python
# Create test_stability_comprehensive.py
import pytest
import threading
from cache.storage_backend import StorageBackend

class TestStabilityComprehensive:
    """Comprehensive stability test suite."""
    
    def test_race_condition_prevention(self):
        """Test that file operations handle race conditions."""
        backend = StorageBackend()
        
        # Test concurrent file operations
        def concurrent_operation():
            backend.delete_file(Path("/tmp/test_file"))
        
        threads = []
        for _ in range(10):
            t = threading.Thread(target=concurrent_operation)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All operations should complete without errors
        assert True
    
    def test_no_deadlock_patterns(self):
        """Verify no deadlock-prone patterns exist."""
        # Test signal emission safety
        from thread_safe_worker import ThreadSafeWorker
        worker = ThreadSafeWorker()
        
        # Should complete without deadlock
        worker.set_state(WorkerState.STOPPED)
        assert worker.get_state() == WorkerState.STOPPED
```

#### Day 5: Performance Validation
```python
# Create performance_validation.py
import time
import tracemalloc

class PerformanceValidator:
    """Validate performance hasn't degraded."""
    
    def validate_startup_time(self):
        """Ensure startup remains under 1 second."""
        start = time.time()
        from shotbot import ShotBotApplication
        app = ShotBotApplication()
        app.initialize()
        elapsed = time.time() - start
        
        assert elapsed < 1.0, f"Startup took {elapsed}s"
        return elapsed
    
    def validate_memory_usage(self):
        """Ensure memory usage remains low."""
        tracemalloc.start()
        
        from shotbot import ShotBotApplication
        app = ShotBotApplication()
        app.load_shots()
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        peak_mb = peak / 1024 / 1024
        assert peak_mb < 200, f"Peak memory {peak_mb}MB"
        return peak_mb
```

### Week 2: Stability & Validation

#### Day 6-7: Fix Race Conditions
```python
# Fix file operation race conditions in cache/storage_backend.py
# Replace check-then-use pattern with EAFP

# OLD (RACE CONDITION):
if file_path.exists():
    with open(file_path) as f:
        data = f.read()

# NEW (SAFE):
try:
    with open(file_path) as f:
        data = f.read()
except FileNotFoundError:
    return None
```

#### Day 8-9: Stability Validation
```bash
# Run stability tests
python -m pytest tests/unit/ -x --tb=short

# Check for race conditions
python -m pytest tests/threading/ -x

# Validate core components
python validate_stability.py
```

#### Day 10: Validation Gate
```yaml
# Phase 1 Success Criteria Checklist:
stability:
  - [ ] Race conditions fixed
  - [ ] Thread safety improved
  - [ ] Signal emission safety
  - [ ] Application starts successfully
  - [ ] Core workflows functional
  - [ ] No regression in performance
  - [ ] Test suite functional
  - [ ] Backward compatibility maintained
```

---

## 🎯 Phase 2: Type Safety Campaign (Weeks 3-4)

### Objective
Fix all 2,054 type errors and establish comprehensive type safety.

### Week 3: Type Error Elimination

#### Day 1-2: Setup & Triage
```bash
# Enable strict type checking gradually
echo '{
  "typeCheckingMode": "strict",
  "reportUnknownMemberType": "warning",
  "reportUnknownArgumentType": "warning",
  "reportUnknownVariableType": "warning",
  "reportMissingTypeStubs": "none"
}' > pyrightconfig.strict.json

# Generate type error report
basedpyright --configuration pyrightconfig.strict.json > type_errors_full.txt

# Categorize by severity
grep "error:" type_errors_full.txt > critical_type_errors.txt
grep "warning:" type_errors_full.txt > type_warnings.txt
```

#### Day 3-5: Core Module Type Fixes
```python
# Priority 1: main_window.py
from typing import Optional, Dict, List, Tuple, Any, cast
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QMainWindow, QWidget

class MainWindow(QMainWindow):
    """Main application window with proper typing."""
    
    # Properly typed signals
    shots_refreshed: Signal = Signal()
    error_occurred: Signal = Signal(str)
    
    def __init__(self) -> None:
        super().__init__()
        self.shot_model: Optional[ShotModel] = None
        self.cache_manager: CacheManager = CacheManager()
        self.workers: Dict[str, ThreadSafeWorker] = {}
        self._refresh_timer: Optional[QTimer] = None
        
    def refresh_shots(self) -> Tuple[bool, bool]:
        """Refresh shots with proper return type."""
        if self.shot_model is None:
            return False, False
        return self.shot_model.refresh_shots()
```

```python
# Priority 2: launcher_manager.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class LauncherProtocol(Protocol):
    """Protocol for launcher implementations."""
    
    def launch(self, command: str, shot: Optional[Shot] = None) -> ProcessInfo:
        ...
    
    def terminate(self, process_id: int) -> bool:
        ...

class LauncherManager:
    """Launcher management with type safety."""
    
    def __init__(self) -> None:
        self._launchers: Dict[str, LauncherProtocol] = {}
        self._active_processes: Dict[str, ProcessInfo] = {}
        self._lock: threading.RLock = threading.RLock()
```

#### Day 6-7: Fix Optional Handling
```python
# Common pattern fixes throughout codebase

# BAD - Type error prone:
def process_shot(shot):
    return shot.name  # shot might be None

# GOOD - Type safe:
def process_shot(shot: Optional[Shot]) -> Optional[str]:
    if shot is None:
        return None
    return shot.name

# Or with assertion for guaranteed non-None:
def process_shot_required(shot: Optional[Shot]) -> str:
    assert shot is not None, "Shot is required"
    return shot.name
```

### Week 4: Type Annotation Completion

#### Day 8-10: Public API Annotations
```python
# Add comprehensive type hints to all public methods

# Example: cache_manager.py
from typing import TypeVar, Generic, Optional, Dict, Any
from typing_extensions import TypedDict

T = TypeVar('T')

class CacheEntry(TypedDict):
    """Typed cache entry."""
    data: Any
    timestamp: float
    ttl: float

class CacheManager(Generic[T]):
    """Fully typed cache manager."""
    
    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """Get cached value with type safety."""
        ...
    
    def set(self, key: str, value: T, ttl: float = 3600) -> None:
        """Set cached value with TTL."""
        ...
    
    def invalidate(self, pattern: str) -> int:
        """Invalidate cache entries matching pattern."""
        ...
```

#### Day 11-12: Type Validation Gate
```bash
# Run final type check
basedpyright --configuration pyrightconfig.strict.json

# Success criteria:
# - 0 type errors
# - <50 type warnings  
# - All public APIs have type hints
# - Generic types used appropriately
```

---

## 🧪 Phase 3: Test Coverage Blitz (Weeks 5-6)

### Objective
Achieve 70% overall test coverage with 90% coverage on critical paths.

### Week 5: Test Infrastructure & Critical Path Testing

#### Day 1: Fix Broken Tests
```python
# Fix the 4 broken test files identified
# 1. test_performance_benchmarks.py - add missing imports
# 2. test_threading_fixes.py - update TestSubprocess import
# 3. test_async_shot_loader.py - fix QSignalSpy import
# 4. test_process_pool_manager.py - remove PersistentBashSession dependency
```

#### Day 2-4: Critical Component Tests
```python
# test_main_window_comprehensive.py
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

class TestMainWindow:
    """Comprehensive MainWindow testing."""
    
    @pytest.fixture
    def main_window(self, qtbot: QtBot, mocker):
        """Create MainWindow with mocked dependencies."""
        mocker.patch('main_window.ProcessPoolManager')
        mocker.patch('main_window.CacheManager')
        window = MainWindow()
        qtbot.addWidget(window)
        return window
    
    def test_initialization(self, main_window, qtbot):
        """Test window initializes correctly."""
        assert main_window.shot_model is not None
        assert main_window.cache_manager is not None
        assert main_window.isVisible()
    
    def test_shot_refresh_workflow(self, main_window, qtbot, mocker):
        """Test complete shot refresh workflow."""
        # Mock workspace command
        mocker.patch.object(
            main_window.shot_model, 
            'refresh_shots',
            return_value=(True, True)
        )
        
        # Trigger refresh
        with qtbot.waitSignal(main_window.shots_refreshed, timeout=5000):
            main_window.refresh_shots()
        
        # Verify UI updated
        assert main_window.shot_grid.model().rowCount() > 0
    
    def test_launcher_execution(self, main_window, qtbot, mocker):
        """Test launcher execution workflow."""
        # Create mock launcher
        mock_launcher = mocker.MagicMock()
        mock_launcher.launch.return_value = ProcessInfo(pid=12345)
        
        # Execute launcher
        main_window.launch_application("nuke", Shot("show", "seq", "shot"))
        
        # Verify process tracked
        assert 12345 in main_window.active_processes
```

#### Day 5: Integration Tests
```python
# test_integration_end_to_end.py
class TestEndToEndWorkflows:
    """Test complete user workflows."""
    
    def test_user_journey_shot_to_nuke(self, qtbot, tmp_path):
        """Test: User opens shot in Nuke."""
        # 1. Start application
        app = ShotBotApplication()
        
        # 2. Load shots
        app.refresh_shots()
        
        # 3. Select shot
        shot = app.get_shot("seq_010")
        app.select_shot(shot)
        
        # 4. Launch Nuke
        process = app.launch_nuke()
        
        # 5. Verify process started
        assert process.is_running()
        
        # 6. Cleanup
        process.terminate()
```

### Week 6: Comprehensive Test Coverage

#### Day 6-8: UI Component Testing
```python
# test_ui_components.py
class TestUIComponents:
    """Test all UI components."""
    
    def test_shot_grid_view(self, qtbot):
        """Test shot grid view functionality."""
        grid = ShotGridView()
        qtbot.addWidget(grid)
        
        # Test thumbnail loading
        grid.load_thumbnails()
        assert grid.thumbnail_count() > 0
        
        # Test selection
        grid.select_shot(0)
        assert grid.current_shot() is not None
        
        # Test double-click
        with qtbot.waitSignal(grid.shot_double_clicked):
            qtbot.mouseDClick(grid, Qt.LeftButton)
    
    def test_launcher_dialog(self, qtbot):
        """Test custom launcher dialog."""
        dialog = LauncherDialog()
        qtbot.addWidget(dialog)
        
        # Fill form
        dialog.name_input.setText("Test Launcher")
        dialog.command_input.setText("echo test")
        
        # Submit
        qtbot.mouseClick(dialog.ok_button, Qt.LeftButton)
        
        # Verify launcher created
        assert dialog.launcher is not None
        assert dialog.launcher.name == "Test Launcher"
```

#### Day 9-10: Performance & Load Testing
```python
# test_performance_load.py
class TestPerformanceUnderLoad:
    """Test performance with realistic load."""
    
    def test_large_shot_list(self, benchmark):
        """Test with 1000+ shots."""
        model = ShotModel()
        
        # Generate test data
        shots = [Shot(f"show", f"seq_{i:03d}", f"shot_{j:03d}") 
                 for i in range(10) for j in range(100)]
        
        # Benchmark refresh
        result = benchmark(model.load_shots, shots)
        assert result[0] == True  # Success
        assert len(model.shots) == 1000
    
    def test_concurrent_operations(self):
        """Test concurrent launcher execution."""
        manager = LauncherManager()
        
        # Launch 10 concurrent processes
        processes = []
        for i in range(10):
            p = manager.launch_command(f"echo test_{i}")
            processes.append(p)
        
        # Verify all started
        assert len(manager.active_processes) == 10
        
        # Wait for completion
        for p in processes:
            p.wait()
```

#### Day 11-12: Coverage Validation
```bash
# Run coverage analysis
pytest --cov=. --cov-report=html --cov-report=term

# Generate detailed report
coverage html
open htmlcov/index.html

# Success criteria:
# - Overall coverage: >70%
# - Critical paths: >90%
# - UI components: >60%
# - Security code: 100%
```

---

## 🏗️ Phase 4: Architecture Refactoring (Weeks 7-8)

### Objective
Break down god objects and implement proper architectural patterns.

### Week 7: God Object Decomposition

#### Day 1-3: Refactor launcher_manager.py
```python
# Split launcher_manager.py (2,029 lines) into:

# 1. launcher_service.py - Business logic
class LauncherService:
    """Core launcher business logic."""
    
    def __init__(self, executor: CommandExecutor):
        self.executor = executor
        self.registry = LauncherRegistry()
    
    def create_launcher(self, config: LauncherConfig) -> Launcher:
        """Create and register a launcher."""
        launcher = Launcher(config)
        self.registry.register(launcher)
        return launcher

# 2. command_validator.py - Validation
class CommandValidator:
    """Command validation and verification.""
    
    def sanitize(self, command: str) -> str:
        """Sanitize command for safe execution."""
        # Validation logic moved here
        return sanitized_command

# 3. process_monitor.py - Process management
class ProcessMonitor:
    """Monitor and manage running processes."""
    
    def __init__(self):
        self.processes: Dict[int, ProcessInfo] = {}
        self.monitor_thread = MonitorThread()
    
    def track_process(self, process: ProcessInfo) -> None:
        """Track a running process."""
        self.processes[process.pid] = process

# 4. launcher_ui.py - UI components
class LauncherUI:
    """UI components for launcher management."""
    
    def __init__(self, service: LauncherService):
        self.service = service
        self.setup_ui()
```

#### Day 4-5: Refactor main_window.py
```python
# Split main_window.py (1,795 lines) into coordinators:

# 1. shot_coordinator.py
class ShotCoordinator:
    """Coordinates shot-related operations."""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager
        self.shot_model = OptimizedShotModel()
        
    def refresh_shots(self) -> RefreshResult:
        """Coordinate shot refresh."""
        return self.shot_model.refresh_shots()

# 2. worker_coordinator.py  
class WorkerCoordinator:
    """Manages background workers."""
    
    def __init__(self):
        self.workers: Dict[str, QThread] = {}
        
    def start_worker(self, name: str, worker: QThread) -> None:
        """Start and track a worker."""
        self.workers[name] = worker
        worker.start()

# 3. ui_coordinator.py
class UICoordinator:
    """Manages UI component setup."""
    
    def __init__(self, parent: QMainWindow):
        self.parent = parent
        self.setup_layout()
        
    def setup_layout(self) -> None:
        """Setup main window layout."""
        # UI setup code

# 4. main_window_refactored.py
class MainWindow(QMainWindow):
    """Refactored main window using coordinators."""
    
    def __init__(self):
        super().__init__()
        self.shot_coordinator = ShotCoordinator(CacheManager())
        self.worker_coordinator = WorkerCoordinator()
        self.ui_coordinator = UICoordinator(self)
```

### Week 8: Qt Threading Pattern Migration

#### Day 6-8: Implement moveToThread Pattern
```python
# Migrate from QThread subclassing to moveToThread pattern

# OLD (Anti-pattern):
class OldWorker(QThread):
    def run(self):
        # Work done in thread
        self.do_work()

# NEW (Best practice):
class Worker(QObject):
    """Worker using moveToThread pattern."""
    
    started = Signal()
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)
    
    @Slot()
    def process(self):
        """Main processing slot."""
        self.started.emit()
        try:
            self._do_work()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
    
    def _do_work(self):
        """Actual work implementation."""
        for i in range(100):
            if QThread.currentThread().isInterruptionRequested():
                break
            self.progress.emit(i)
            time.sleep(0.1)

# Usage:
def start_worker():
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    
    # Connect signals
    thread.started.connect(worker.process)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    
    # Start
    thread.start()
```

#### Day 9-10: Dependency Injection Implementation
```python
# container.py - Dependency injection container
class ServiceContainer:
    """Application service container."""
    
    def __init__(self):
        # Core services
        self._services: Dict[type, Any] = {}
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize all services."""
        # Execution
        self._services[CommandExecutor] = CommandExecutor()
        
        # Cache
        self._services[CacheManager] = CacheManager()
        
        # Data
        self._services[ShotModel] = OptimizedShotModel(
            cache=self._services[CacheManager]
        )
        
        # Launchers
        self._services[LauncherService] = LauncherService(
            executor=self._services[CommandExecutor]
        )
    
    def get(self, service_type: type) -> Any:
        """Get a service instance."""
        return self._services.get(service_type)

# Application initialization
container = ServiceContainer()
main_window = MainWindow(container)
```

---

## 🎨 Phase 5: Code Quality & Consolidation (Weeks 9-10)

### Objective
Eliminate duplication, fix linting issues, and establish consistent code quality.

### Week 9: Code Cleanup

#### Day 1-2: Eliminate Duplication
```python
# Consolidate shot models into single implementation

# shot_model.py - Unified implementation
class ShotModel(BaseShotModel):
    """Unified shot model with optional optimizations."""
    
    def __init__(self, use_async: bool = True):
        super().__init__()
        self.use_async = use_async
        if use_async:
            self._async_loader = AsyncShotLoader()
    
    def refresh_shots(self) -> RefreshResult:
        """Refresh with optional async loading."""
        if self.use_async:
            return self._refresh_async()
        return self._refresh_sync()

# Delete duplicate files:
# - shot_model_optimized.py
# - base_shot_model.py (merge into shot_model.py)
```

#### Day 3-4: Fix Linting Issues
```bash
# Auto-fix all fixable issues
ruff check --fix .
ruff format .

# Fix remaining issues manually
ruff check . > linting_report.txt

# Common fixes:
# - Remove unused imports (F401)
# - Remove unused variables (F841)
# - Fix line length (E501)
# - Sort imports (I001)
```

#### Day 5: Replace Print Statements
```python
# Setup proper logging throughout

# logging_config.py
import logging
import logging.handlers

def setup_logging():
    """Configure application logging."""
    logger = logging.getLogger('shotbot')
    logger.setLevel(logging.DEBUG if os.getenv('SHOTBOT_DEBUG') else logging.INFO)
    
    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(console)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        'shotbot.log', maxBytes=10485760, backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    ))
    logger.addHandler(file_handler)
    
    return logger

# Replace all print statements
# OLD:
print(f"Loading shot: {shot_name}")

# NEW:
logger.info(f"Loading shot: {shot_name}")
```

### Week 10: Final Quality Improvements

#### Day 6-7: Documentation
```python
# Add comprehensive docstrings

class ShotModel:
    """Model for managing VFX shots.
    
    This class provides the data model for shots retrieved from
    the workspace command. It handles caching, refresh operations,
    and change detection.
    
    Attributes:
        shots: List of available shots
        cache_manager: Cache management instance
        use_async: Whether to use async loading
        
    Example:
        model = ShotModel(use_async=True)
        success, changed = model.refresh_shots()
        if changed:
            print(f"Loaded {len(model.shots)} shots")
    """
    
    def refresh_shots(self) -> RefreshResult:
        """Refresh the shot list from workspace.
        
        Attempts to load shots from the workspace command,
        falling back to cache if the command fails.
        
        Returns:
            RefreshResult: Named tuple with (success, has_changes)
            
        Raises:
            WorkspaceError: If workspace command fails and no cache exists
        """
```

#### Day 8-9: Performance Optimization
```python
# Optimize identified bottlenecks

# 1. Lazy imports for faster startup
def load_heavy_module():
    """Load heavy module only when needed."""
    global heavy_module
    if 'heavy_module' not in globals():
        import heavy_module
    return heavy_module

# 2. Cache computed properties
from functools import cached_property

class Shot:
    @cached_property
    def thumbnail_path(self) -> Path:
        """Compute thumbnail path once and cache."""
        return self._compute_thumbnail_path()

# 3. Use slots for memory efficiency
class ProcessInfo:
    __slots__ = ['pid', 'command', 'start_time', 'status']
    
    def __init__(self, pid: int, command: str):
        self.pid = pid
        self.command = command
        self.start_time = time.time()
        self.status = 'running'
```

#### Day 10: Final Cleanup
```bash
# Remove deprecated code
find . -name "*.backup*" -delete
find . -name "*.deprecated*" -delete

# Clean up TODO/FIXME comments
grep -r "TODO\|FIXME" . --include="*.py" > todo_list.txt

# Update requirements
pip freeze > requirements.txt

# Generate documentation
pdoc --html --output-dir docs shotbot
```

---

## ✅ Phase 6: Validation & Deployment Readiness (Weeks 11-12)

### Objective
Ensure all fixes are integrated and application is production-ready.

### Week 11: Integration Testing

#### Day 1-3: Comprehensive Integration Tests
```python
# test_integration_complete.py
class TestCompleteIntegration:
    """Test all components work together."""
    
    def test_full_application_lifecycle(self):
        """Test application from start to shutdown."""
        # 1. Start application
        app = QApplication([])
        window = MainWindow()
        
        # 2. Load shots
        assert window.shot_coordinator.refresh_shots().success
        
        # 3. Launch multiple applications
        processes = []
        for app_name in ['nuke', 'maya', '3de']:
            p = window.launch_application(app_name)
            processes.append(p)
        
        # 4. Verify all running
        assert len(window.active_processes) == 3
        
        # 5. Clean shutdown
        window.close()
        for p in processes:
            assert p.terminate()
    
    def test_error_recovery(self):
        """Test error handling and recovery."""
        # Test workspace command failure
        # Test cache corruption
        # Test network issues
        # Test permission errors
```

#### Day 4-5: Performance Validation
```python
# Ensure performance hasn't degraded

def test_startup_performance():
    """Verify startup time remains under 1 second."""
    start = time.time()
    app = ShotBotApplication()
    app.initialize()
    elapsed = time.time() - start
    assert elapsed < 1.0, f"Startup took {elapsed}s"

def test_memory_usage():
    """Verify memory usage remains low."""
    import tracemalloc
    tracemalloc.start()
    
    app = ShotBotApplication()
    app.load_shots()
    app.load_thumbnails()
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    assert peak / 1024 / 1024 < 200, f"Peak memory {peak/1024/1024}MB"
```

### Week 12: Deployment Preparation

#### Day 6-7: Final Validation
```bash
# Run comprehensive test suite
python -m pytest tests/ --cov=. --cov-report=term

# Check for race conditions
python test_stability_comprehensive.py

# Performance validation
python performance_validation.py

# Manual review checklist
# [ ] No race conditions
# [ ] Thread safety verified
# [ ] Performance maintained
# [ ] All tests passing
# [ ] Backward compatibility preserved
```

#### Day 8-9: Documentation Update
```markdown
# Update all documentation

1. README.md - Installation, usage, features
2. ARCHITECTURE.md - System design, patterns
3. STABILITY.md - Stability measures, reliability patterns
4. DEPLOYMENT.md - Deployment procedures
5. TROUBLESHOOTING.md - Common issues, solutions
6. API.md - Public API documentation
```

#### Day 10: Deployment Checklist
```yaml
# deployment_checklist.yaml
pre_deployment:
  code_quality:
    - [ ] 0 type errors
    - [ ] 0 race conditions
    - [ ] 70%+ test coverage
    - [ ] All tests passing
    - [ ] No linting errors
    
  performance:
    - [ ] Startup < 1 second
    - [ ] Memory < 200MB
    - [ ] No UI blocking operations
    
  documentation:
    - [ ] README updated
    - [ ] CHANGELOG updated
    - [ ] API docs generated
    
deployment:
  - [ ] Tag release version
  - [ ] Create release branch
  - [ ] Build deployment package
  - [ ] Run smoke tests
  
post_deployment:
  - [ ] Monitor error logs
  - [ ] Track performance metrics
  - [ ] Gather user feedback
```

---

## 📊 Success Metrics & Validation

### Phase Completion Criteria

| Phase | Success Criteria | Validation Method |
|-------|-----------------|-------------------|
| Phase 1 | Stable concurrent operation | Stability test suite, race condition tests |
| Phase 2 | 0 type errors | basedpyright --strict |
| Phase 3 | 70% test coverage | pytest --cov |
| Phase 4 | No files >500 lines | wc -l analysis |
| Phase 5 | 0 linting errors | ruff check |
| Phase 6 | All integration tests pass | Full test suite |

### Risk Mitigation

1. **Feature Flags**: Gradual rollout of changes
```python
FEATURE_FLAGS = {
    'use_secure_executor': True,
    'use_async_loading': True,
    'use_new_threading': False,  # Enable after testing
}
```

2. **Rollback Plan**: Git tags at each phase completion
```bash
git tag -a phase1-complete -m "Phase 1: Stability improvements complete"
git tag -a phase2-complete -m "Phase 2: Type safety complete"
# etc...
```

3. **Monitoring**: Error tracking and metrics
```python
# monitoring.py
class MetricsCollector:
    def track_error(self, error: Exception):
        """Track errors for monitoring."""
        # Send to error tracking service
        
    def track_performance(self, metric: str, value: float):
        """Track performance metrics."""
        # Send to metrics service
```

---

## 🚀 Implementation Commands

### Daily Workflow
```bash
# Start of day
git pull origin main
source venv/bin/activate
pytest tests/

# During development
ruff check --watch .
basedpyright --watch

# Before commit
ruff check --fix .
ruff format .
pytest --cov
basedpyright

# End of day
git add -A
git commit -m "Phase X, Day Y: [Description]"
git push origin feature/phase-x
```

### Weekly Review
```bash
# Generate progress report
echo "Week $(date +%U) Progress Report" > weekly_report.md
echo "=========================" >> weekly_report.md
echo "" >> weekly_report.md
echo "## Completed Tasks" >> weekly_report.md
git log --oneline --since="1 week ago" >> weekly_report.md
echo "" >> weekly_report.md
echo "## Test Coverage" >> weekly_report.md
pytest --cov --cov-report=term | tail -n 20 >> weekly_report.md
echo "" >> weekly_report.md
echo "## Type Errors" >> weekly_report.md
basedpyright --stats | grep "error" >> weekly_report.md
```

---

## 📅 Timeline Summary

| Week | Phase | Focus | Deliverables |
|------|-------|-------|--------------|
| 1-2 | Phase 1 | Stability Improvements | Race conditions fixed, stability tests |
| 3-4 | Phase 2 | Type Safety | Zero type errors, full annotations |
| 5-6 | Phase 3 | Test Coverage | 70% coverage, all tests passing |
| 7-8 | Phase 4 | Architecture | Refactored god objects, proper patterns |
| 9-10 | Phase 5 | Code Quality | Zero duplication, clean code |
| 11-12 | Phase 6 | Validation | Production ready, deployed |

---

## 🎯 Final Outcome

After 12 weeks of systematic improvement:

1. **Stability**: Robust concurrent operation
2. **Type Safety**: Fully typed, zero errors
3. **Test Coverage**: 70%+ with critical paths at 90%
4. **Architecture**: Clean, maintainable, SOLID principles
5. **Code Quality**: Professional grade, minimal duplication
6. **Performance**: Sub-second startup maintained
7. **Documentation**: Comprehensive and current
8. **Deployment**: Production-ready with monitoring

The ShotBot application will be transformed from a critical-risk state to a production-ready, maintainable, secure application suitable for VFX pipeline deployment.

---

*This plan provides a thorough, systematic approach to fixing all identified issues. Each phase builds on the previous, with clear validation gates ensuring quality at every step.*