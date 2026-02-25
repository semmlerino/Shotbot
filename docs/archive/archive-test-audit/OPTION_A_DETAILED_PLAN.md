# Option A: Emergency Architecture Surgery - Detailed Implementation Plan

**Duration**: 4 weeks  
**Goal**: Decompose god objects and fix type system conflicts while preserving 100% functionality  
**Approach**: Incremental, testable refactoring with verification at each step

## Pre-Flight Checklist

### Week 0 - Preparation (2-3 days before starting)

1. **Create Safety Net**
   ```bash
   # Create branch for refactoring
   git checkout -b architecture-surgery
   
   # Tag current working state
   git tag pre-refactoring-baseline
   
   # Create backup of critical files
   cp launcher_manager.py launcher_manager.py.backup
   cp main_window.py main_window.py.backup
   ```

2. **Establish Baseline Metrics**
   ```bash
   # Document current functionality
   python3 -c "from launcher_manager import LauncherManager; lm = LauncherManager(); print(len(lm.list_launchers()))"
   
   # Run existing tests (even if coverage is low)
   pytest tests/unit/test_launcher_manager.py -v > baseline_launcher_tests.txt
   pytest tests/unit/test_main_window.py -v > baseline_mainwindow_tests.txt
   
   # Type check baseline
   basedpyright launcher_manager.py main_window.py > baseline_type_errors.txt
   
   # Line counts
   wc -l launcher_manager.py main_window.py > baseline_line_counts.txt
   ```

3. **Create Integration Test Suite**
   ```python
   # tests/integration/test_refactoring_safety.py
   """Tests to ensure functionality is preserved during refactoring."""
   
   def test_launcher_crud_operations():
       """Verify all CRUD operations work."""
       # Test create, read, update, delete
   
   def test_launcher_execution():
       """Verify launchers can still execute."""
       # Test execution with mock subprocess
   
   def test_ui_initialization():
       """Verify UI still initializes correctly."""
       # Test main window creation
   
   def test_signal_connections():
       """Verify all signals still connect."""
       # Test critical signal-slot connections
   ```

## Week 1: Decompose launcher_manager.py

### Day 1-2: Extract Data Models and Value Objects

**Goal**: Separate data structures from business logic

1. **Create launcher/models.py (≈300 lines)**
   ```python
   # Move from launcher_manager.py:
   - LauncherValidation (lines 265-283)
   - LauncherTerminal (lines 284-292)  
   - LauncherEnvironment (lines 293-302)
   - CustomLauncher (lines 303-335)
   - ProcessInfo (lines 403-421)
   ```

2. **Verification Steps**
   ```bash
   # After each extraction:
   python3 -c "from launcher.models import CustomLauncher; print('Import successful')"
   
   # Ensure launcher_manager.py still works with imports
   python3 -c "from launcher_manager import LauncherManager; print('Still works')"
   
   # Run integration tests
   pytest tests/integration/test_refactoring_safety.py::test_launcher_crud_operations
   ```

3. **Update imports in launcher_manager.py**
   ```python
   # Replace internal classes with:
   from launcher.models import (
       CustomLauncher, LauncherValidation, 
       LauncherTerminal, LauncherEnvironment, ProcessInfo
   )
   ```

### Day 3: Extract Configuration Management

**Goal**: Isolate persistence logic

1. **Create launcher/config_manager.py (≈200 lines)**
   ```python
   # Extract from launcher_manager.py:
   - LauncherConfig class (lines 336-402)
   - load_launchers() method
   - save_launchers() method
   - _ensure_config_dir() method
   ```

2. **Create adapter in LauncherManager**
   ```python
   class LauncherManager(QObject):
       def __init__(self, config_dir=None):
           super().__init__()
           self._config_manager = LauncherConfigManager(config_dir)
           self._launchers = self._config_manager.load_launchers()
       
       def save_launchers(self):
           """Delegate to config manager."""
           return self._config_manager.save_launchers(self._launchers)
   ```

3. **Verification**
   ```bash
   # Test persistence still works
   python3 -c "
   from launcher_manager import LauncherManager
   lm = LauncherManager()
   launchers = lm.list_launchers()
   print(f'Loaded {len(launchers)} launchers')
   "
   ```

### Day 4: Extract Validation Logic

**Goal**: Centralize all validation rules

1. **Create launcher/validator.py (≈400 lines)**
   ```python
   class LauncherValidator:
       """Validates launcher configurations and commands."""
       
       def validate_command_syntax(self, command: str) -> tuple[bool, Optional[str]]:
           # Move from launcher_manager.py lines 850-911
       
       def validate_launcher_paths(self, launcher: CustomLauncher) -> tuple[bool, List[str]]:
           # Move from launcher_manager.py lines 1270-1456
       
       def validate_environment(self, env: LauncherEnvironment) -> tuple[bool, str]:
           # New method extracted from scattered validation
       
       def validate_launcher_config(self, launcher: CustomLauncher) -> tuple[bool, List[str]]:
           # Combine all validation logic
   ```

2. **Update LauncherManager**
   ```python
   class LauncherManager(QObject):
       def __init__(self):
           self._validator = LauncherValidator()
       
       def create_launcher(self, launcher: CustomLauncher) -> bool:
           # Use validator
           valid, errors = self._validator.validate_launcher_config(launcher)
           if not valid:
               self.launcher_error.emit(launcher.id, f"Validation failed: {errors}")
               return False
           # Continue with creation...
   ```

3. **Verification**
   ```python
   # Test validation still works
   from launcher.validator import LauncherValidator
   validator = LauncherValidator()
   valid, error = validator.validate_command_syntax("nuke {shot_path}")
   assert valid, f"Valid command rejected: {error}"
   ```

### Day 5: Extract Process Management

**Goal**: Isolate subprocess and thread management

1. **Create launcher/process_manager.py (≈500 lines)**
   ```python
   class LauncherProcessManager:
       """Manages launcher process lifecycle."""
       
       def __init__(self):
           self._active_processes: Dict[str, ProcessInfo] = {}
           self._workers: Dict[str, LauncherWorker] = {}
           self._lock = threading.RLock()
       
       # Move from launcher_manager.py:
       - execute_launcher() core logic
       - _create_worker()
       - _start_worker()
       - _on_worker_finished()
       - _cleanup_finished_workers()
       - get_active_process_count()
       - get_active_process_info()
       - terminate_process()
   ```

2. **Move LauncherWorker to launcher/worker.py (≈250 lines)**
   ```python
   # Extract LauncherWorker class (lines 32-264)
   ```

3. **Update LauncherManager to delegate**
   ```python
   class LauncherManager(QObject):
       def __init__(self):
           self._process_manager = LauncherProcessManager()
           self._process_manager.process_started.connect(self.command_started)
           self._process_manager.process_finished.connect(self.command_finished)
       
       def execute_launcher(self, launcher_id: str, shot: Optional[Shot] = None):
           launcher = self.get_launcher(launcher_id)
           if not launcher:
               return None
           return self._process_manager.execute(launcher, shot)
   ```

### Day 6-7: Final LauncherManager Refactoring

**Goal**: LauncherManager becomes a thin orchestrator

1. **Create launcher/repository.py (≈200 lines)**
   ```python
   class LauncherRepository:
       """CRUD operations for launchers."""
       
       def __init__(self, config_manager: LauncherConfigManager):
           self._config = config_manager
           self._launchers: Dict[str, CustomLauncher] = {}
           self.reload()
       
       def create(self, launcher: CustomLauncher) -> bool:
           # Create logic
       
       def update(self, launcher_id: str, updates: dict) -> bool:
           # Update logic
       
       def delete(self, launcher_id: str) -> bool:
           # Delete logic
       
       def get(self, launcher_id: str) -> Optional[CustomLauncher]:
           # Get by ID
       
       def list_all(self, category: Optional[str] = None) -> List[CustomLauncher]:
           # List with optional filtering
   ```

2. **Final LauncherManager structure (≈400 lines)**
   ```python
   class LauncherManager(QObject):
       """Orchestrates launcher operations."""
       
       def __init__(self, config_dir=None):
           super().__init__()
           # Initialize components
           self._config_manager = LauncherConfigManager(config_dir)
           self._repository = LauncherRepository(self._config_manager)
           self._validator = LauncherValidator()
           self._process_manager = LauncherProcessManager()
           
           # Connect signals
           self._setup_signal_forwarding()
       
       # Thin delegation methods
       def create_launcher(self, launcher: CustomLauncher) -> bool:
           if not self._validator.validate_launcher_config(launcher)[0]:
               return False
           return self._repository.create(launcher)
       
       # ... other delegating methods
   ```

3. **Verification Suite**
   ```bash
   # Full functionality test
   python3 tests/integration/test_launcher_decomposition.py
   
   # Line count verification
   wc -l launcher_manager.py launcher/*.py
   # Should show: launcher_manager.py < 400 lines
   #              Total of launcher/*.py ≈ 2000 lines (same as original)
   ```

## Week 2: Decompose main_window.py

### Day 8-9: Extract Tab Management

**Goal**: Separate tab logic from main window

1. **Create ui/tabs/ directory structure**
   ```
   ui/tabs/
   ├── __init__.py
   ├── base_tab.py (≈100 lines) - Common tab functionality
   ├── shot_tab.py (≈250 lines) - "My Shots" tab
   ├── threede_tab.py (≈250 lines) - "Other 3DE scenes" tab  
   ├── previous_tab.py (≈200 lines) - "Previous/approved shots" tab
   └── launcher_tab.py (≈200 lines) - "Custom Launchers" tab
   ```

2. **Extract tab initialization from main_window.py**
   ```python
   # ui/tabs/shot_tab.py
   class ShotTab(BaseTab):
       def __init__(self, shot_model, cache_manager, parent=None):
           super().__init__(parent)
           self._setup_ui()
           self._connect_signals()
       
       def _setup_ui(self):
           # Move shot grid setup from main_window._setup_ui()
           self.shot_grid = ShotGrid(self.shot_model, self.cache_manager)
           # ... rest of UI setup
   ```

3. **Update MainWindow to use tabs**
   ```python
   class MainWindow(QMainWindow):
       def _setup_tabs(self):
           # Replace inline tab creation with:
           self.shot_tab = ShotTab(self.shot_model, self.cache_manager)
           self.tab_widget.addTab(self.shot_tab, "My Shots")
           
           self.threede_tab = ThreeDETab(self.shot_model, self.cache_manager)
           self.tab_widget.addTab(self.threede_tab, "Other 3DE scenes")
   ```

### Day 10: Extract Menu System

**Goal**: Modularize menu construction

1. **Create ui/menu_builder.py (≈200 lines)**
   ```python
   class MenuBuilder:
       """Builds application menus."""
       
       def build_file_menu(self, parent: QMainWindow) -> QMenu:
           menu = QMenu("&File", parent)
           # Add actions
           return menu
       
       def build_edit_menu(self, parent: QMainWindow) -> QMenu:
           # Edit menu construction
       
       def build_view_menu(self, parent: QMainWindow) -> QMenu:
           # View menu construction
       
       def build_help_menu(self, parent: QMainWindow) -> QMenu:
           # Help menu construction
   ```

2. **Create ui/action_manager.py (≈150 lines)**
   ```python
   class ActionManager:
       """Manages application actions and shortcuts."""
       
       def create_refresh_action(self, parent) -> QAction:
           action = QAction("&Refresh", parent)
           action.setShortcut(QKeySequence.Refresh)
           return action
       
       # Other action creation methods
   ```

### Day 11: Extract Settings Management

**Goal**: Centralize settings handling

1. **Create ui/settings_manager.py (≈200 lines)**
   ```python
   class SettingsManager:
       """Manages application settings persistence."""
       
       def __init__(self):
           self.settings = QSettings("YourCompany", "ShotBot")
       
       def save_window_state(self, window: QMainWindow):
           # Extract from main_window.closeEvent()
       
       def restore_window_state(self, window: QMainWindow):
           # Extract from main_window.__init__()
       
       def save_tab_state(self, tab_widget: QTabWidget):
           # Save active tab, etc.
   ```

### Day 12-13: Extract State Coordination

**Goal**: Separate UI state management from MainWindow

1. **Create ui/state_coordinator.py (≈300 lines)**
   ```python
   class StateCoordinator:
       """Coordinates UI state across components."""
       
       def __init__(self):
           self._current_shot: Optional[Shot] = None
           self._ui_components: Dict[str, QWidget] = {}
       
       def register_component(self, name: str, component: QWidget):
           self._ui_components[name] = component
       
       def on_shot_selected(self, shot: Optional[Shot]):
           self._current_shot = shot
           self._update_ui_for_shot(shot)
       
       def _update_ui_for_shot(self, shot: Optional[Shot]):
           # Update all registered components
   ```

2. **Final MainWindow structure (≈400 lines)**
   ```python
   class MainWindow(QMainWindow):
       """Main application window - thin orchestrator."""
       
       def __init__(self):
           super().__init__()
           # Initialize components
           self._init_models()
           self._init_ui_components()
           self._connect_signals()
           self._restore_state()
       
       def _init_models(self):
           """Initialize data models."""
           self.cache_manager = CacheManager()
           self.shot_model = ShotModel(self.cache_manager)
           self.launcher_manager = LauncherManager()
       
       def _init_ui_components(self):
           """Initialize UI components."""
           self.menu_builder = MenuBuilder()
           self.state_coordinator = StateCoordinator()
           self.settings_manager = SettingsManager()
           self._setup_ui()
       
       def _setup_ui(self):
           """Setup UI using components."""
           # Now just 50-100 lines of coordination
   ```

## Week 3: Fix Type System Conflicts

### Day 14-15: Resolve Shot Class Duplication

**Goal**: Create unified Shot type hierarchy

1. **Create shot_types.py - Unified type definitions**
   ```python
   from typing import Protocol, runtime_checkable
   from dataclasses import dataclass, field
   
   @runtime_checkable
   class ShotProtocol(Protocol):
       """Protocol defining Shot interface."""
       show: str
       sequence: str
       shot: str
       workspace_path: str
       
       @property
       def full_name(self) -> str: ...
   
   @dataclass
   class BaseShot:
       """Base Shot implementation."""
       show: str
       sequence: str
       shot: str
       workspace_path: str = ""
       
       @property
       def full_name(self) -> str:
           return f"{self.sequence}_{self.shot}"
   
   @dataclass
   class ShotWithThumbnail(BaseShot):
       """Shot with thumbnail caching."""
       _cached_thumbnail_path: Any = field(
           default=_NOT_SEARCHED, init=False, repr=False, compare=False
       )
       
       @property
       def thumbnail_dir(self) -> Path:
           return PathUtils.build_thumbnail_path(
               Config.SHOWS_ROOT, self.show, self.sequence, self.shot
           )
   ```

2. **Update all imports systematically**
   ```python
   # Step 1: Find all Shot imports
   grep -r "from.*import.*Shot" --include="*.py" > shot_imports.txt
   
   # Step 2: Update each file
   # shot_model.py
   from shot_types import ShotWithThumbnail as Shot  # Use enhanced version
   
   # cache_manager.py and others
   from shot_types import ShotProtocol  # Use protocol for flexibility
   
   def cache_shots(self, shots: Sequence[ShotProtocol]) -> None:
       # Now accepts any Shot implementation
   ```

3. **Verification**
   ```python
   # Test compatibility
   from shot_types import BaseShot, ShotWithThumbnail, ShotProtocol
   from cache_manager import CacheManager
   
   # Both should work
   basic_shot = BaseShot("show", "seq", "shot", "/path")
   full_shot = ShotWithThumbnail("show", "seq", "shot", "/path")
   
   cache = CacheManager()
   cache.cache_shots([basic_shot, full_shot])  # Should accept both
   ```

### Day 16: Fix Critical Type Errors

**Goal**: Address the 17 critical errors in core modules

1. **Fix Signal Type Safety**
   ```python
   # Before: Generic object signals
   shot_selected = Signal(object)
   
   # After: Typed signals with compatibility
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from shot_types import ShotProtocol
   
   shot_selected = Signal(object)  # Keep for runtime
   
   def emit_shot_selected(self, shot: 'ShotProtocol'):
       """Type-safe emission."""
       self.shot_selected.emit(shot)
   ```

2. **Fix Lambda Type Issues**
   ```python
   # Before: Lambda with unknown types
   self.button.clicked.connect(
       lambda checked, lid=launcher.id: self._execute_launcher(lid)
   )
   
   # After: Named method with types
   def _create_launcher_callback(self, launcher_id: str):
       def callback(checked: bool = False):
           self._execute_launcher(launcher_id)
       return callback
   
   self.button.clicked.connect(self._create_launcher_callback(launcher.id))
   ```

3. **Add Missing Type Annotations**
   ```python
   # Run targeted type checking
   basedpyright cache_manager.py shot_model.py launcher_manager.py
   
   # Fix each error systematically
   # Example: Add return types
   def find_scenes_for_shot(
       self,
       shot_workspace_path: str,
       show: str,
       sequence: str,
       shot: str
   ) -> List[Dict[str, Any]]:  # Add explicit return type
       # Implementation
   ```

### Day 17: Type System Verification

**Goal**: Ensure type safety improvements

1. **Run Progressive Type Checking**
   ```bash
   # Check core modules first
   basedpyright shot_types.py --typeCheckingMode strict
   basedpyright launcher/*.py --typeCheckingMode basic
   basedpyright ui/*.py --typeCheckingMode basic
   
   # Document improvements
   basedpyright . 2>&1 | tee post_refactoring_type_errors.txt
   
   # Compare with baseline
   diff baseline_type_errors.txt post_refactoring_type_errors.txt
   ```

2. **Create Type Stubs if Needed**
   ```python
   # shotbot-stubs/__init__.pyi
   from shot_types import ShotProtocol as ShotProtocol
   from shot_types import BaseShot as BaseShot
   from shot_types import ShotWithThumbnail as ShotWithThumbnail
   ```

## Week 4: Integration and Verification

### Day 18-19: Integration Testing

**Goal**: Ensure all components work together

1. **Create Comprehensive Integration Tests**
   ```python
   # tests/integration/test_refactored_architecture.py
   
   def test_launcher_full_workflow():
       """Test complete launcher workflow."""
       manager = LauncherManager()
       
       # Create
       launcher = CustomLauncher(
           id="test", name="Test", command="echo test"
       )
       assert manager.create_launcher(launcher)
       
       # Execute
       process_id = manager.execute_launcher("test")
       assert process_id is not None
       
       # Verify process tracking
       assert manager.get_active_process_count() > 0
       
       # Delete
       assert manager.delete_launcher("test")
   
   def test_main_window_initialization():
       """Test MainWindow with refactored components."""
       app = QApplication([])
       window = MainWindow()
       
       # Verify all tabs exist
       assert window.tab_widget.count() == 4
       
       # Verify menu exists
       assert window.menuBar().actions()
       
       # Verify signals connected
       # ... test signal connections
   ```

2. **Test Each Decomposed Module**
   ```bash
   # Test each new module independently
   pytest tests/unit/test_launcher_validator.py
   pytest tests/unit/test_launcher_repository.py
   pytest tests/unit/test_launcher_process_manager.py
   pytest tests/unit/test_ui_tabs.py
   pytest tests/unit/test_menu_builder.py
   ```

### Day 20: Performance Verification

**Goal**: Ensure no performance regression

1. **Benchmark Key Operations**
   ```python
   # benchmark_refactoring.py
   import time
   from launcher_manager import LauncherManager
   from main_window import MainWindow
   
   def benchmark_launcher_operations():
       manager = LauncherManager()
       
       start = time.perf_counter()
       launchers = manager.list_launchers()
       list_time = time.perf_counter() - start
       
       print(f"List launchers: {list_time:.3f}s")
       assert list_time < 0.1, "Performance regression"
   
   def benchmark_window_creation():
       app = QApplication([])
       
       start = time.perf_counter()
       window = MainWindow()
       window.show()
       create_time = time.perf_counter() - start
       
       print(f"Window creation: {create_time:.3f}s")
       assert create_time < 1.0, "Startup regression"
   ```

### Day 21: Documentation and Cleanup

**Goal**: Document the new architecture

1. **Create Architecture Documentation**
   ```markdown
   # ARCHITECTURE.md
   
   ## Module Organization
   
   ### launcher/ Package
   - models.py - Data structures
   - validator.py - Validation logic
   - repository.py - CRUD operations
   - process_manager.py - Process lifecycle
   - config_manager.py - Persistence
   
   ### ui/ Package  
   - tabs/ - Tab implementations
   - menu_builder.py - Menu construction
   - settings_manager.py - Settings persistence
   - state_coordinator.py - UI state management
   
   ## Design Patterns
   - Repository Pattern: LauncherRepository
   - Strategy Pattern: Tab implementations
   - Observer Pattern: StateCoordinator
   - Facade Pattern: LauncherManager
   ```

2. **Update Imports Across Codebase**
   ```python
   # create update_imports.py script
   import os
   import re
   
   def update_imports():
       # Update imports systematically
       replacements = [
           (r"from launcher_manager import CustomLauncher",
            "from launcher.models import CustomLauncher"),
           (r"from type_definitions import Shot",
            "from shot_types import ShotProtocol"),
       ]
       
       for root, dirs, files in os.walk("."):
           for file in files:
               if file.endswith(".py"):
                   # Apply replacements
   ```

3. **Clean Up**
   ```bash
   # Remove backup files after verification
   rm launcher_manager.py.backup
   rm main_window.py.backup
   
   # Update requirements if needed
   pip freeze > requirements.txt
   
   # Final metrics
   echo "=== Refactoring Complete ===="
   echo "launcher_manager.py: $(wc -l launcher_manager.py)"
   echo "launcher/ total: $(wc -l launcher/*.py | tail -1)"
   echo "main_window.py: $(wc -l main_window.py)"
   echo "ui/ total: $(wc -l ui/*.py ui/**/*.py | tail -1)"
   echo "Type errors: $(basedpyright 2>&1 | grep 'error' | wc -l)"
   ```

## Verification Checkpoints

### After Each Day
1. **Run integration tests** - Must pass
2. **Check type errors** - Should decrease
3. **Test UI manually** - All features work
4. **Commit working state** - Can rollback if needed

### After Each Week
1. **Full regression test suite**
2. **Performance benchmarks**  
3. **Code review checkpoint**
4. **Update documentation**

## Rollback Strategy

If any step fails:
1. **Immediate**: `git stash` and test previous commit
2. **Day-level**: `git reset --hard HEAD~[commits]`
3. **Week-level**: `git checkout pre-week-N-tag`
4. **Emergency**: `git checkout pre-refactoring-baseline`

## Success Criteria

### Week 1 Complete
- [ ] launcher_manager.py < 400 lines
- [ ] All launcher functionality preserved
- [ ] launcher/ package properly organized
- [ ] All tests pass

### Week 2 Complete  
- [ ] main_window.py < 400 lines
- [ ] All UI functionality preserved
- [ ] ui/ package properly organized
- [ ] No visual changes to user

### Week 3 Complete
- [ ] Shot type conflicts resolved
- [ ] Type errors reduced by 80%+
- [ ] All cache operations work
- [ ] No runtime type failures

### Week 4 Complete
- [ ] All integration tests pass
- [ ] No performance regression
- [ ] Documentation complete
- [ ] Ready for next phase

## Post-Surgery Next Steps

1. **Immediate**: Run the application for a full day in production
2. **Week 5**: Begin Phase 2 - Test Coverage improvements on new architecture
3. **Week 6**: Begin Phase 3 - Performance optimizations
4. **Week 7+**: Continue with comprehensive plan

---

This plan ensures **zero functionality loss** through incremental refactoring, comprehensive testing at each step, and multiple rollback points. Each change is independently verifiable and the application remains functional throughout the process.