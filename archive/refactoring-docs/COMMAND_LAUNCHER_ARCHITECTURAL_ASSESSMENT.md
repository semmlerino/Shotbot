# CommandLauncher Refactoring: Architectural Assessment

**Date**: 2025-01-11
**Scope**: CommandLauncher and extracted launch components (EnvironmentManager, CommandBuilder, ProcessExecutor)
**Status**: Phase 1 Complete - Extraction Successful, Phase 2 Needed - Consolidation

---

## Executive Summary

The CommandLauncher refactoring successfully extracted three focused components (EnvironmentManager, CommandBuilder, ProcessExecutor) from a monolithic launcher class. This represents **significant architectural progress** with clear separation of concerns and improved testability.

**Key Achievement**: Reduced component complexity from single 1500+ line class to multiple focused modules.

**Critical Issue**: CommandLauncher remains at **961 lines** with **~700 lines of code duplication** across three launch methods. This represents the **highest-priority architectural debt** that must be addressed.

**Overall Grade**: **B** (Good foundations, critical duplication issue remains)

---

## 1. Design Patterns Analysis

### ✅ Delegation Pattern - WELL EXECUTED

**Strengths**:
- Clear delegation boundaries between components
- CommandLauncher → EnvironmentManager for environment detection
- CommandLauncher → ProcessExecutor for process management
- CommandLauncher → NukeLaunchRouter for Nuke-specific logic
- Minimal coupling at delegation points

**Evidence**:
```python
# Clean delegation examples
self.env_manager = EnvironmentManager()
self.process_executor = ProcessExecutor(persistent_terminal, Config)
terminal = self.env_manager.detect_terminal()
```

### ⚠️ Strategy Pattern - PARTIALLY IMPLEMENTED

**Observation**: NukeLaunchRouter uses routing logic (simple vs complex launcher) but lacks formal Strategy interface.

**Current State**:
```python
# Implicit routing based on options
if has_workspace_options and not has_media_options:
    return self._route_to_simple(...)
if has_media_options or has_workspace_options:
    return self._route_to_complex(...)
```

**Improvement Opportunity**: Extract explicit `LaunchStrategy` protocol:
```python
class LaunchStrategy(Protocol):
    def prepare_command(
        self, shot: Shot, options: LaunchOptions
    ) -> tuple[str, list[str]]: ...

class SimpleLaunchStrategy: ...
class ComplexLaunchStrategy: ...
```

### ✅ Observer Pattern - EXCELLENT

**Strengths**:
- ProcessExecutor uses Qt signals for execution lifecycle events
- Clean decoupling between execution and notification
- Type-annotated signals for clarity

**Implementation**:
```python
class ProcessExecutor(QObject):
    execution_started: Signal = Signal(str, str)
    execution_progress: Signal = Signal(str, str)
    execution_completed: Signal = Signal(bool, str)
    execution_error: Signal = Signal(str, str)
```

**Benefits**:
- Asynchronous communication without tight coupling
- Multiple observers can subscribe to events
- Qt's signal/slot mechanism ensures thread safety

### ⚠️ Dependency Injection - MIXED QUALITY

**Good Examples**:
```python
# ProcessExecutor constructor injection
def __init__(
    self,
    persistent_terminal: PersistentTerminalManager | None,
    config: type[Config],
    parent: QObject | None = None,
): ...
```

**Issues**:

1. **EnvironmentManager**: No dependency injection
   ```python
   def detect_terminal(self) -> str | None:
       for term in self.TERMINAL_PREFERENCE:
           if shutil.which(term) is not None:  # Direct dependency
   ```
   - `shutil.which()` called directly - makes testing harder
   - Should inject `WhichChecker` protocol

2. **CommandLauncher**: Outdated legacy injection pattern
   ```python
   def __init__(
       self,
       raw_plate_finder: type[RawPlateFinderType] | None = None,  # Legacy
       # ... deprecated parameters marked for removal
   ```
   - Comments acknowledge deprecation
   - Creates confusion about proper usage

3. **Config Injection**: Unusual `type[Config]` pattern (discussed in detail below)

---

## 2. SOLID Principles Analysis

### Single Responsibility Principle (SRP)

| Component | SRP Grade | Assessment |
|-----------|-----------|------------|
| EnvironmentManager | ✅ A | Handles ONLY environment detection (terminal, rez) |
| CommandBuilder | ✅ A | Handles ONLY command construction and validation |
| ProcessExecutor | ✅ A- | Handles ONLY process execution and lifecycle |
| CommandLauncher | ❌ D | Still doing TOO MUCH (details below) |

**CommandLauncher Responsibilities** (TOO MANY):
1. Shot context management (`set_current_shot`, `current_shot`)
2. Signal routing (4 forwarding methods: `_on_execution_*`)
3. Three launch methods with 80% duplication
4. Workspace validation (`_validate_workspace_before_launch`)
5. Error emission with timestamps (`_emit_error`)
6. Legacy dependency management (4 deprecated finder injections)
7. Direct integration with 3 composed components
8. Nuke-specific logic (environment fixes, plate handling)
9. 3DE and Maya scene file handling
10. Terminal fallback decision logic

**Recommended Extractions**:
- `LaunchContextManager`: Shot context + workspace validation
- `SceneFileResolver`: 3DE/Maya latest scene finding
- `LaunchCoordinator`: Orchestrate launch flow (eliminate duplication)
- `ErrorHandler`: Centralize error emission and formatting

### Open/Closed Principle (OCP)

**✅ Strengths**:
- **CommandBuilder**: Composable static methods allow extension via composition
  ```python
  # Easy to add new transformations
  @staticmethod
  def new_transformation(command: str) -> str: ...
  ```

**❌ Violations**:
- **ProcessExecutor.GUI_APPS**: Hardcoded set, not extensible
  ```python
  GUI_APPS: Final[set[str]] = {"3de", "nuke", "maya", ...}  # Must modify class
  ```
  Should be: `gui_apps: set[str]` parameter or from Config

- **CommandLauncher Launch Methods**: Three methods with duplicated error handling
  - Not closed for modification - adding new launch scenario requires copy-paste
  - No template method pattern to abstract common flow

### Liskov Substitution Principle (LSP)

**Status**: N/A - No inheritance hierarchies in extracted components

All components use composition over inheritance, which avoids LSP concerns.

### Interface Segregation Principle (ISP)

**✅ Components Expose Focused APIs**:
- EnvironmentManager: 5 methods (rez check, package mapping, terminal detection, cache)
- CommandBuilder: 8 static methods (validate, build, wrap, transform)
- ProcessExecutor: 6 public methods (execution variants, verification, checks)

**⚠️ CommandLauncher Has Large API Surface**:
```python
# Public API
set_current_shot(shot)
launch_app(app_name, include_raw_plate, open_latest_threede, ...)  # 7 params
launch_app_with_scene(app_name, scene)
launch_app_with_scene_context(app_name, scene, include_raw_plate)
```

**Issues**:
- Three launch methods with overlapping concerns
- Unclear when to use `launch_app` vs `launch_app_with_scene_context`
- 7 parameters on `launch_app()` - violates clean code guidelines

### Dependency Inversion Principle (DIP)

**✅ Good Abstraction Usage**:
- ProcessExecutor depends on `PersistentTerminalManager` protocol (duck-typed)
- Signal-based communication creates loose coupling

**❌ Concrete Dependencies**:
- CommandBuilder depends on concrete `Config` class
- EnvironmentManager depends on concrete `shutil.which` / `os.environ`
- All components tightly coupled to `Config` structure

**Recommended**: Use protocols for all external dependencies:
```python
class ConfigProtocol(Protocol):
    USE_REZ_ENVIRONMENT: bool
    APPS: dict[str, str]
    # ... only needed fields

class WhichChecker(Protocol):
    def which(self, command: str) -> str | None: ...
```

---

## 3. Component Design Analysis

### EnvironmentManager (115 lines)

**Single Responsibility**: ✅ EXCELLENT
Focused solely on environment detection: rez availability, terminal detection, package mapping.

**Cohesion**: ✅ HIGH
All methods relate to environment configuration.

**Design Issues**:

#### 1. Stateful Caching (Code Smell)

```python
def __init__(self) -> None:
    self._rez_available_cache: bool | None = None
    self._available_terminal_cache: str | None = None

def reset_cache(self) -> None:  # Needed for testing - smell
    self._rez_available_cache = None
    self._available_terminal_cache = None
```

**Problem**: Requires instantiation just for caching. `reset_cache()` exists only for testing.

**Better Alternative**:
```python
from functools import lru_cache

class EnvironmentManager:
    @staticmethod
    @lru_cache(maxsize=1)
    def detect_terminal() -> str | None: ...

    @staticmethod
    @lru_cache(maxsize=1)
    def is_rez_available(use_rez: bool, auto_detect: bool) -> bool: ...
```

**Benefits**:
- No instance state required
- Thread-safe caching via `@lru_cache`
- No `reset_cache()` needed (use `detect_terminal.cache_clear()` in tests)

#### 2. Config Dependency Creates Tight Coupling

```python
def is_rez_available(self, config: type[Config]) -> bool:
    if not config.USE_REZ_ENVIRONMENT:
        return False
```

**Problem**: Tightly couples to `Config` class structure. Changes to Config ripple through all uses.

**Better Alternative**:
```python
def is_rez_available(self, use_rez: bool, auto_detect: bool) -> bool:
    if not use_rez:
        return False
```

#### 3. External Dependencies Not Injected

```python
def detect_terminal(self) -> str | None:
    for term in self.TERMINAL_PREFERENCE:
        if shutil.which(term) is not None:  # Direct call
```

**Problem**: Makes testing harder - requires mocking `shutil.which` globally.

**Better Alternative**:
```python
class WhichChecker(Protocol):
    def which(self, command: str) -> str | None: ...

class EnvironmentManager:
    def __init__(self, which_checker: WhichChecker = shutil): ...
```

#### 4. No Error Handling

```python
self._rez_available_cache = shutil.which("rez") is not None
```

**Problem**: What if `shutil.which()` throws? No exception handling or logging of failures.

**Verdict**: ✅ Good separation of concerns, ⚠️ needs better injection and error handling

---

### CommandBuilder (259 lines)

**Single Responsibility**: ✅ EXCELLENT
Pure command construction and validation logic with no side effects (except logging).

**Pure Functions vs Stateful**: ✅ EXCELLENT CHOICE
All methods are `@staticmethod` - functional approach is perfect for command building.

**Design Strengths**:

1. **Composability**:
   ```python
   @staticmethod
   def build_full_command(
       app_command: str,
       workspace: str | None,
       config: Config,
       rez_packages: list[str] | None = None,
       apply_nuke_fixes: bool = False,
       add_logging_redirect: bool = True,
   ) -> str:
       command = app_command
       if apply_nuke_fixes:
           command = CommandBuilder.apply_nuke_environment_fixes(command, config)
       if workspace:
           command = CommandBuilder.build_workspace_command(workspace, command)
       if rez_packages:
           command = CommandBuilder.wrap_with_rez(command, rez_packages)
       if add_logging_redirect:
           command = CommandBuilder.add_logging(command)
       return command
   ```
   Composes smaller functions into larger transformations.

2. **Security-Focused Validation**:
   ```python
   DANGEROUS_CHARS: Final[tuple[str, ...]] = (
       ";", "&&", "||", "|",  # Command separators
       ">", "<", ">>", ">&",  # Redirections
       "`", "$(",  # Command substitution
       # ...
   )

   @staticmethod
   def validate_path(path: str) -> str:
       for char in CommandBuilder.DANGEROUS_CHARS:
           if char in path:
               raise ValueError(f"Path contains dangerous character '{char}'")
       return shlex.quote(path)
   ```

3. **Clear Method Purposes**: Each method has single, clear responsibility

**Design Issues**:

#### 1. Config Dependency (Same Issue)

```python
@staticmethod
def apply_nuke_environment_fixes(command: str, config: Config) -> str:
    if config.NUKE_SKIP_PROBLEMATIC_PLUGINS:
        env_fixes.append(...)
```

**Better**:
```python
@staticmethod
def apply_nuke_environment_fixes(
    command: str,
    skip_problematic_plugins: bool,
    ocio_fallback_config: str | None,
) -> str:
```

#### 2. Mixed Concerns in `build_full_command()`

Single function orchestrates 4 transformations - it's both **composer** AND **orchestrator**.

**Alternative**: Extract `CommandPipeline` class:
```python
class CommandPipeline:
    def __init__(self):
        self.transformations: list[Callable[[str], str]] = []

    def add_transformation(self, transform: Callable[[str], str]) -> Self:
        self.transformations.append(transform)
        return self

    def execute(self, command: str) -> str:
        for transform in self.transformations:
            command = transform(command)
        return command
```

#### 3. Inconsistent Error Handling

- `validate_path()`: Raises `ValueError` ✅
- `add_logging()`: Returns original command on error (graceful degradation) ⚠️
- No documented error strategy

**Recommendation**: Use Result types for consistency:
```python
@staticmethod
def add_logging(command: str) -> Result[str, LoggingError]:
    try:
        # ... setup logging
        return Ok(command_with_logging)
    except OSError as e:
        return Err(LoggingError(f"Failed to setup logging: {e}"))
```

#### 4. Side Effects (Logging)

```python
@staticmethod
def wrap_with_rez(command: str, packages: list[str]) -> str:
    logger.debug(f"Wrapping command with rez packages: {packages_str}")
    return f'rez env {packages_str} -- bash -ilc "{command}"'
```

**Issue**: "Pure" functions have logging side effects. Less pure, harder to test.

**Better**: Return `Result` with metadata:
```python
@dataclass
class CommandResult:
    command: str
    metadata: dict[str, Any]  # Contains logging info
```

**Verdict**: ✅ Excellent functional design, ⚠️ minor improvements possible (Config coupling, error handling)

---

### ProcessExecutor (256 lines)

**Single Responsibility**: ✅ GOOD
Handles process execution and lifecycle management with signal-based status reporting.

**Signal-Based Communication**: ✅ EXCELLENT

```python
# Type-annotated signals
execution_started: Signal = Signal(str, str)  # timestamp, message
execution_progress: Signal = Signal(str, str)
execution_completed: Signal = Signal(bool, str)  # success, error_message
execution_error: Signal = Signal(str, str)
```

**Benefits**:
- Clean async communication pattern
- Decouples execution from notification
- Multiple observers can subscribe
- Thread-safe (Qt signal/slot mechanism)

**Design Strengths**:

1. **Proper Qt Integration**:
   ```python
   def __init__(
       self,
       persistent_terminal: PersistentTerminalManager | None,
       config: type[Config],
       parent: QObject | None = None,  # ✅ Correct!
   ):
       super().__init__(parent)
   ```

2. **Async Process Verification**:
   ```python
   # Use QTimer for non-blocking verification
   QTimer.singleShot(100, partial(self.verify_spawn, process, app_name))
   ```
   Uses `functools.partial` instead of lambda (avoids capture issues).

3. **Clean Delegation**: Delegates to persistent terminal when available:
   ```python
   def execute_in_persistent_terminal(self, command: str, app_name: str) -> bool:
       if not self.can_use_persistent_terminal():
           return False
       self.persistent_terminal.send_command_async(command)
       return True
   ```

**Design Issues**:

#### 1. GUI_APPS Hardcoded Set (Violates OCP)

```python
GUI_APPS: Final[set[str]] = {
    "3de", "nuke", "maya", "rv", "houdini", "mari", "katana", "clarisse",
}
```

**Problem**: Not extensible - must modify class to add new GUI app.

**Better**: Inject or read from Config:
```python
def __init__(
    self,
    persistent_terminal: PersistentTerminalManager | None,
    config: type[Config],
    gui_apps: set[str] | None = None,  # ✅ Injected
    parent: QObject | None = None,
):
    self.gui_apps = gui_apps or set(config.GUI_APPS)
```

#### 2. Private Member Access (Encapsulation Violation)

```python
if self.persistent_terminal._fallback_mode:  # pyright: ignore[reportPrivateUsage]
```

**Problem**: Breaking encapsulation, requires type checker suppression.

**Better**: Use public method:
```python
if self.persistent_terminal.is_in_fallback_mode():
```

#### 3. Config as `type[Config]` (Discussed in Section 4)

#### 4. Mixed Responsibilities

```python
def is_gui_app(self, app_name: str) -> bool:  # Configuration lookup
def can_use_persistent_terminal(self) -> bool:  # Availability checking
def execute_in_*() -> bool:  # Actual execution
def _on_terminal_*() -> None:  # Signal handling
```

**Analysis**: These are related but could be further separated:
- Configuration logic → `AppConfig` class
- Availability checking → Could be static utility
- Execution → Core responsibility ✅
- Signal handling → Bridge to persistent terminal ✅

**Verdict**: ✅ Good signal-based design, ⚠️ some encapsulation violations and hardcoding

---

### CommandLauncher (961 lines) - **STILL TOO LARGE**

**Critical Issue**: CommandLauncher has ~700 lines of **code duplication** across three launch methods.

#### Code Duplication Analysis

**Three Launch Methods**:
1. `launch_app()` - 293 lines
2. `launch_app_with_scene()` - 199 lines
3. `launch_app_with_scene_context()` - 226 lines

**Duplicated Code Blocks** (appears in all 3 methods):

```python
# 1. Workspace validation (8 lines each)
if not self._validate_workspace_before_launch(workspace_path, app_name):
    return False

# 2. Rez environment wrapping (15 lines each)
if self.env_manager.is_rez_available(Config):
    rez_packages = self.env_manager.get_rez_packages(app_name, Config)
    if rez_packages:
        packages_str = " ".join(rez_packages)
        full_command = f'rez env {packages_str} -- bash -ilc "{ws_command}"'
        # ...

# 3. Nuke environment fixes (10 lines each)
env_fixes = ""
if app_name == "nuke":
    env_fixes = self.nuke_handler.get_environment_fixes()
    if env_fixes:
        timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
        # ...

# 4. Logging redirection (2 lines each)
full_command = CommandBuilder.add_logging(full_command)

# 5. Command logging (4 lines each)
timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
self.command_executed.emit(timestamp, full_command)

# 6. Persistent terminal check (22 lines each)
if (
    self.persistent_terminal
    and Config.PERSISTENT_TERMINAL_ENABLED
    and Config.USE_PERSISTENT_TERMINAL
):
    if self.persistent_terminal._fallback_mode:
        # Fallback to new terminal
    else:
        self.persistent_terminal.send_command_async(full_command)
        return True

# 7. Terminal detection (8 lines each)
terminal = self.env_manager.detect_terminal()
if terminal is None:
    self._emit_error("No terminal emulator found...")
    return False

# 8. Terminal command building (15 lines each)
if terminal == "gnome-terminal":
    term_cmd = ["gnome-terminal", "--", "bash", "-ilc", full_command]
elif terminal == "konsole":
    term_cmd = ["konsole", "-e", "bash", "-ilc", full_command]
# ... 4 more branches

# 9. Process spawning (3 lines each)
process = subprocess.Popen(term_cmd)
QTimer.singleShot(100, partial(self.process_executor.verify_spawn, process, app_name))
return True

# 10. Error handling (60 lines each - IDENTICAL)
except FileNotFoundError as e:
    filename_not_found = _safe_filename_str(...)
    self._emit_error(f"Cannot launch {app_name}: ...")
    NotificationManager.error(...)
    self.env_manager.reset_cache()
    return False

except PermissionError as e:
    # ... identical pattern

except OSError as e:
    # ... identical pattern with errno checking

except Exception as e:
    # ... identical pattern
```

**Total Duplication**: ~700 lines of nearly identical code (10 duplicated blocks × ~70 lines × 3 methods = 210 lines per method × 3 = ~630 lines, plus variations)

**Impact**:
- ❌ **Bug fixes must be applied in 3 places** - high defect risk
- ❌ **New features require 3 updates** - maintenance nightmare
- ❌ **Testing requires 3× test cases** - inefficient
- ❌ **Violates DRY principle** - core software engineering principle

#### Recommended Solution: Template Method Pattern

**Extract Common Launch Flow**:

```python
class CommandLauncher:
    def _execute_launch(
        self,
        command: str,
        workspace_path: str,
        app_name: str,
        apply_nuke_fixes: bool = False,
    ) -> bool:
        """Template method for common launch flow.

        Consolidates duplicated logic across launch_app, launch_app_with_scene,
        and launch_app_with_scene_context.
        """
        # 1. Validate workspace
        if not self._validate_workspace_before_launch(workspace_path, app_name):
            return False

        # 2. Build full command with transformations
        full_command = self._build_full_command(
            command, workspace_path, app_name, apply_nuke_fixes
        )

        # 3. Log command
        self._log_command(full_command)

        # 4. Execute via persistent terminal or new terminal
        return self._execute_command(full_command, app_name)

    def _execute_command(self, command: str, app_name: str) -> bool:
        """Execute command via persistent terminal or spawn new terminal."""
        # Persistent terminal path
        if self._can_use_persistent_terminal():
            return self._execute_in_persistent_terminal(command, app_name)

        # New terminal path
        return self._execute_in_new_terminal(command, app_name)

    def _execute_in_new_terminal(self, command: str, app_name: str) -> bool:
        """Spawn new terminal with comprehensive error handling."""
        terminal = self.env_manager.detect_terminal()
        if terminal is None:
            self._emit_error("No terminal emulator found...")
            return False

        try:
            term_cmd = self._build_terminal_command(terminal, command)
            process = subprocess.Popen(term_cmd)
            QTimer.singleShot(
                100, partial(self.process_executor.verify_spawn, process, app_name)
            )
            return True
        except FileNotFoundError as e:
            return self._handle_file_not_found_error(e, app_name)
        except PermissionError as e:
            return self._handle_permission_error(e, app_name)
        except OSError as e:
            return self._handle_os_error(e, app_name)
        except Exception as e:
            return self._handle_generic_error(e, app_name)

    # Then simplify the public API:
    def launch_app(self, app_name: str, options: LaunchOptions) -> bool:
        """Launch app with options."""
        if not self.current_shot:
            self._emit_error("No shot selected")
            return False

        # Build app-specific command
        command = self._prepare_app_command(app_name, options)

        # Use template method
        return self._execute_launch(
            command,
            self.current_shot.workspace_path,
            app_name,
            apply_nuke_fixes=(app_name == "nuke"),
        )
```

**Benefits**:
- ✅ **Single source of truth** for launch flow
- ✅ **DRY compliant** - bug fixes in one place
- ✅ **Easier to test** - test template method once
- ✅ **Easier to extend** - add new launch variants without duplication
- ✅ **Reduces CommandLauncher from 961 lines to ~400 lines**

**Verdict**: ❌ Critical architectural debt - code duplication must be addressed

---

## 4. Type System Design

### `type[Config]` Pattern - UNUSUAL AND QUESTIONABLE

**Current Usage**:
```python
def __init__(self, config: type[Config], ...):
    self.config: type[Config] = config

# Used as:
if self.config.USE_REZ_ENVIRONMENT:
    packages = self.config.APPS["nuke"]
```

**Why This Pattern Exists**:
- Config is a class with `ClassVar` fields, never instantiated
- Used like a namespace of constants
- `type[Config]` means "the Config class object", not "an instance of Config"

**Problems**:

1. **Tight Coupling**: Every component coupled to Config class structure
2. **Testing Difficulty**: Can't easily mock - would need to mock entire class
3. **Type Safety**: Less clear than protocol or dataclass
4. **Unusual Semantics**: Confusing to developers unfamiliar with this pattern
5. **Inflexible**: Can't swap configurations or have multiple config instances

**Better Alternatives**:

#### Option 1: Config Protocol (Recommended)

```python
class LaunchConfigProtocol(Protocol):
    """Protocol defining launch configuration interface."""
    USE_REZ_ENVIRONMENT: bool
    REZ_AUTO_DETECT: bool
    REZ_NUKE_PACKAGES: list[str]
    APPS: dict[str, str]
    PERSISTENT_TERMINAL_ENABLED: bool
    USE_PERSISTENT_TERMINAL: bool
    # ... only fields actually used

class EnvironmentManager:
    def is_rez_available(self, config: LaunchConfigProtocol) -> bool:
        if not config.USE_REZ_ENVIRONMENT:
            return False
        # ...
```

**Benefits**:
- ✅ Loose coupling - any object matching protocol works
- ✅ Easy mocking - create simple test objects
- ✅ Clear interface - documents what's actually needed
- ✅ Type-safe - basedpyright validates protocol compliance

#### Option 2: Config Dataclass Instances

```python
@dataclass(frozen=True)
class LaunchConfig:
    """Configuration for launch operations."""
    use_rez_environment: bool
    rez_auto_detect: bool
    rez_nuke_packages: list[str]
    apps: dict[str, str]
    persistent_terminal_enabled: bool
    use_persistent_terminal: bool

# Create singleton instance
DEFAULT_CONFIG = LaunchConfig(
    use_rez_environment=True,
    rez_auto_detect=True,
    rez_nuke_packages=["nuke", "python-3.11"],
    apps={"nuke": "nuke", "maya": "maya", "3de": "3de"},
    persistent_terminal_enabled=True,
    use_persistent_terminal=True,
)

class EnvironmentManager:
    def __init__(self, config: LaunchConfig = DEFAULT_CONFIG): ...
```

**Benefits**:
- ✅ True instances - can have multiple configurations
- ✅ Frozen dataclass - immutable and hashable
- ✅ Easy testing - construct test configs
- ✅ Type-safe field access

#### Option 3: Individual Parameters (Most Explicit)

```python
class EnvironmentManager:
    def is_rez_available(
        self, use_rez: bool, auto_detect: bool
    ) -> bool:
        if not use_rez:
            return False
        if auto_detect and os.environ.get("REZ_USED"):
            return True
        return shutil.which("rez") is not None
```

**Benefits**:
- ✅ Minimal coupling - only what's needed
- ✅ Self-documenting - clear parameter names
- ✅ Maximum flexibility

**Recommendation**: Use **Config Protocol** for balance of clarity, flexibility, and maintainability.

---

### Type Hints Comprehensiveness

**Strengths**:
1. ✅ Method signatures generally well-typed
2. ✅ ProcessExecutor signals have type annotations
3. ✅ Use of `| None` unions for optionals
4. ✅ `TYPE_CHECKING` guard for circular import avoidance
5. ✅ Constants use `Final` and proper types

**Gaps and Improvements**:

#### 1. Launch Options Should Be TypedDict

**Current**:
```python
def prepare_nuke_command(
    self, shot: Shot, base_command: str, options: dict[str, bool], ...
) -> tuple[str, list[str]]:
```

**Better**:
```python
class LaunchOptions(TypedDict):
    open_latest_scene: bool
    create_new_file: bool
    include_raw_plate: bool

def prepare_nuke_command(
    self, shot: Shot, base_command: str, options: LaunchOptions, ...
) -> tuple[str, list[str]]:
```

**Benefits**:
- Self-documenting - IDE autocomplete shows available options
- Type-safe - typos caught at type-check time
- Clear intent - not just "dict of bools"

#### 2. App Names Should Be Literal or Enum

**Current**:
```python
def launch_app(self, app_name: str, ...) -> bool:
```

**Better**:
```python
AppName = Literal["nuke", "maya", "3de", "rv", "publish"]

def launch_app(self, app_name: AppName, ...) -> bool:
```

**Benefits**:
- Type-safe - invalid app names caught at type-check time
- IDE autocomplete - shows valid app names
- Refactoring-friendly - rename propagates

#### 3. Return Types Should Use Result Pattern

**Current**:
```python
def launch_app(...) -> bool:  # Success/failure unclear
    try:
        # ...
    except FileNotFoundError as e:
        self._emit_error(...)
        return False
```

**Issues**:
- Bool return doesn't explain failure reason
- Error details lost (only emitted via signal)
- Caller can't distinguish error types

**Better**:
```python
from typing import Result, Ok, Err  # Python 3.13+ or use library

@dataclass
class LaunchError:
    kind: Literal["file_not_found", "permission_denied", "no_terminal"]
    message: str
    exception: Exception | None = None

def launch_app(...) -> Result[None, LaunchError]:
    try:
        # ...
        return Ok(None)
    except FileNotFoundError as e:
        error = LaunchError(
            kind="file_not_found",
            message=f"Cannot launch {app_name}: Application not found",
            exception=e,
        )
        self._emit_error(error.message)
        return Err(error)
```

**Benefits**:
- Explicit error handling - caller knows failure reasons
- Type-safe - can't forget to check result
- Testable - can assert on specific error types

#### 4. Config.APPS Should Be TypedDict

**Current**:
```python
APPS: ClassVar[dict[str, str]] = {
    "3de": "3de",
    "nuke": "nuke",
    "maya": "maya",
}
```

**Better**:
```python
class AppCommands(TypedDict):
    nuke: str
    maya: str
    threede: str  # Can't use "3de" as identifier
    rv: str
    publish: str

APPS: ClassVar[AppCommands] = {
    "nuke": "nuke",
    "maya": "maya",
    "threede": "3de",
    "rv": "rv",
    "publish": "publish_standalone",
}
```

**Verdict**: Type hints are comprehensive but could be more **semantic** with TypedDicts, Literals, and Result types.

---

## 5. Qt Integration

### ✅ Signals/Slots Usage - EXCELLENT

**ProcessExecutor Signals**:
```python
execution_started: Signal = Signal(str, str)  # timestamp, message
execution_progress: Signal = Signal(str, str)
execution_completed: Signal = Signal(bool, str)  # success, error_message
execution_error: Signal = Signal(str, str)
```

**Proper Connection Syntax**:
```python
_ = self.process_executor.execution_started.connect(self._on_execution_started)
_ = self.process_executor.execution_progress.connect(self._on_execution_progress)
```

**Benefits**:
- Type-annotated signals for clarity
- Proper underscore assignment (addresses connection return value)
- Clean async communication
- Thread-safe via Qt's signal/slot mechanism

### ⚠️ QObject Hierarchy - PARTIALLY CORRECT

**ProcessExecutor - ✅ CORRECT**:
```python
def __init__(
    self,
    persistent_terminal: PersistentTerminalManager | None,
    config: type[Config],
    parent: QObject | None = None,  # ✅ Parent parameter
):
    super().__init__(parent)  # ✅ Proper parent passing
```

**CommandLauncher - ❌ MISSING PARENT**:
```python
class CommandLauncher(LoggingMixin, QObject):
    def __init__(
        self,
        raw_plate_finder: type[RawPlateFinderType] | None = None,
        # ... other params
        # ❌ NO parent: QObject | None = None parameter
    ):
        super().__init__()  # ❌ No parent passed
```

**Issue**: CommandLauncher doesn't accept `parent` parameter.

**Impact**:
- ❌ Potential memory leak if CommandLauncher not explicitly deleted
- ❌ No automatic cleanup when parent destroyed
- ❌ Violates Qt ownership best practices

**Fix**:
```python
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
    threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
    maya_latest_finder: type[MayaLatestFinderType] | None = None,
    persistent_terminal: PersistentTerminalManager | None = None,
    parent: QObject | None = None,  # ✅ Add this
) -> None:
    super().__init__(parent)  # ✅ Pass to QObject
```

### ✅ Threading Concerns - MOSTLY SAFE

**Good Practices**:
1. ✅ `QTimer.singleShot()` used correctly for delayed verification
2. ✅ `functools.partial` instead of lambda (avoids capture race conditions)
3. ✅ Signal-based communication for async operations (thread-safe)

**Issues**:
⚠️ Private member access not thread-safe:
```python
if self.persistent_terminal._fallback_mode:  # pyright: ignore
```

**Problem**: `_fallback_mode` accessed without synchronization. If persistent terminal changes state in another thread, race condition possible.

**Better**:
```python
# In PersistentTerminalManager
@property
def is_in_fallback_mode(self) -> bool:
    """Thread-safe property for fallback mode check."""
    with self._lock:
        return self._fallback_mode

# In ProcessExecutor
if self.persistent_terminal.is_in_fallback_mode():
```

### ✅ Parent Ownership - PARTIALLY HANDLED

**ProcessExecutor**: ✅ Proper parent parameter
**CommandLauncher**: ❌ No parent parameter - must be managed externally

**Recommendation**: Add parent parameter to CommandLauncher for consistent Qt ownership.

---

## 6. Maintainability Analysis

### Is the Code Easy to Extend?

**✅ Good Extensibility**:
- **CommandBuilder**: Static methods are composable - easy to add new transformations
- **ProcessExecutor**: Signals make it easy to add new observers
- **EnvironmentManager**: Easy to add new detection methods

**⚠️ Challenging Extensibility**:
- **CommandLauncher**: Adding new launch scenarios requires duplicating error handling
- **ProcessExecutor.GUI_APPS**: Hardcoded set - need to modify class to add apps
- **Config dependency**: Every new config value requires passing through entire chain

**❌ Difficult Extensibility**:
- **Three launch methods**: Changes need to be made in 3 places (700 lines of duplication)
- **No shared launch flow**: High maintenance burden for cross-cutting changes

**Example - Adding New App Type**:
```python
# Current: Must modify ProcessExecutor class
class ProcessExecutor:
    GUI_APPS: Final[set[str]] = {
        "3de", "nuke", "maya", "rv", "houdini", "mari", "katana", "clarisse",
        # Must add new app here ❌
    }

# Better: Config-driven
class Config:
    GUI_APPS: ClassVar[set[str]] = {"nuke", "maya", ...}

class ProcessExecutor:
    def __init__(self, ..., gui_apps: set[str] | None = None):
        self.gui_apps = gui_apps or set(config.GUI_APPS)  # ✅ Configurable
```

### Is the API Surface Clean?

**CommandLauncher Public API**:
```python
# Current API
set_current_shot(shot: Shot | None) -> None
launch_app(
    app_name: str,
    include_raw_plate: bool = False,
    open_latest_threede: bool = False,
    open_latest_maya: bool = False,
    open_latest_scene: bool = False,
    create_new_file: bool = False,
    selected_plate: str | None = None,
) -> bool  # 7 parameters!
launch_app_with_scene(app_name: str, scene: ThreeDEScene) -> bool
launch_app_with_scene_context(app_name: str, scene: ThreeDEScene, include_raw_plate: bool = False) -> bool
```

**Issues**:
1. ❌ `launch_app()` has **7 parameters** - violates clean code guidelines (max 3-4)
2. ❌ Three launch methods with overlapping concerns - confusing
3. ❌ Unclear when to use `launch_app` vs `launch_app_with_scene_context`
4. ❌ Boolean parameters create combinatorial explosion (2^7 = 128 possible states)

**Better API Design**:
```python
class LaunchOptions(TypedDict, total=False):
    """Options for launching applications."""
    open_latest_scene: bool
    create_new_file: bool
    include_raw_plate: bool
    open_latest_threede: bool
    open_latest_maya: bool

class LaunchContext(TypedDict):
    """Context for launching applications."""
    shot: Shot | None
    scene: ThreeDEScene | None
    selected_plate: str | None

class CommandLauncher:
    def launch(
        self,
        app: AppName,
        context: LaunchContext,
        options: LaunchOptions | None = None,
    ) -> Result[None, LaunchError]:
        """Unified launch method.

        Replaces launch_app, launch_app_with_scene, launch_app_with_scene_context.
        """
```

**Benefits**:
- ✅ Single launch method - no confusion
- ✅ 3 parameters - clean code compliant
- ✅ TypedDict options - self-documenting, extensible
- ✅ Result return - explicit error handling
- ✅ Easier to test - fewer method combinations

### Are Interfaces Stable?

**Signal Interfaces**: ✅ STABLE
- ProcessExecutor signals are well-defined
- Unlikely to change

**ComponentAPIs**: ⚠️ MODERATELY STABLE
- EnvironmentManager, CommandBuilder, ProcessExecutor are stable
- But CommandLauncher API is complex and may need breaking changes

**Legacy Patterns**: ❌ UNSTABLE
- Legacy dependency injection marked "deprecated"
- Suggests ongoing migration and future breaking changes

**Verdict**: ⚠️ Maintainability is MODERATE - good foundations but duplication and complex API hinder long-term maintenance

---

## 7. Coupling Analysis

### Component Dependencies

**EnvironmentManager**:
- ➡️ `Config` (type[Config]) - MODERATE coupling
- ➡️ `shutil.which` (direct call) - TIGHT coupling
- ➡️ `os.environ` (direct call) - TIGHT coupling

**CommandBuilder**:
- ➡️ `Config` (for Nuke fixes, logging) - MODERATE coupling
- ➡️ `shlex`, `Path` (stdlib) - LOOSE coupling

**ProcessExecutor**:
- ➡️ `PersistentTerminalManager` (protocol/duck-typed) - LOOSE coupling ✅
- ➡️ `Config` (type[Config]) - MODERATE coupling
- ➡️ `NotificationManager` (static calls) - TIGHT coupling
- ➡️ `subprocess`, `QTimer` (framework) - LOOSE coupling

**CommandLauncher**:
- ➡️ `EnvironmentManager` (composed) - LOOSE coupling ✅
- ➡️ `ProcessExecutor` (composed) - LOOSE coupling ✅
- ➡️ `NukeLaunchRouter` (composed) - LOOSE coupling ✅
- ➡️ `Config` (static) - MODERATE coupling
- ➡️ `NotificationManager` (static) - TIGHT coupling
- ➡️ Legacy finders (4 classes) - TIGHT coupling (deprecated)

### Key Coupling Issues

#### 1. Config Passed Everywhere as `type[Config]`

**Problem**: Creates global coupling - every component depends on Config class structure.

**Impact**:
- Changes to Config ripple through all components
- Testing requires mocking entire Config class
- Can't swap configurations easily

**Solution**: Use Config Protocol or dataclass instances (see Section 4)

#### 2. NotificationManager Static Calls

```python
NotificationManager.error("Launch Failed", f"{app_name} crashed immediately")
```

**Problem**: Not mockable - static calls can't be intercepted in tests.

**Impact**:
- Tests trigger real notification system
- Can't verify notification calls
- Tight coupling to notification implementation

**Solution**: Inject notification protocol:
```python
class Notifier(Protocol):
    def error(self, title: str, message: str) -> None: ...

class ProcessExecutor:
    def __init__(
        self, ..., notifier: Notifier = NotificationManager
    ): ...
```

#### 3. Legacy Dependency Injection

```python
if raw_plate_finder is None:
    from raw_plate_finder import RawPlateFinder
    self._raw_plate_finder = RawPlateFinder
```

**Problem**: Conditional imports, mixed patterns (types vs instances), marked deprecated.

**Impact**: Confusing for maintainers, technical debt

**Solution**: Remove legacy pattern entirely (noted in comments as planned)

#### 4. EnvironmentManager Direct Calls

```python
if shutil.which(term) is not None:  # Direct dependency
```

**Problem**: Not injected - hard to test, can't swap implementations.

**Solution**: Inject `WhichChecker` protocol:
```python
class WhichChecker(Protocol):
    def which(self, command: str) -> str | None: ...

class EnvironmentManager:
    def __init__(self, which_checker: WhichChecker = shutil): ...
```

**Verdict**: ⚠️ Coupling is MODERATE to TIGHT - could be looser with protocols and dependency injection

---

## 8. Architectural Debt and Code Smells

### Technical Debt Inventory

#### 1. ⚠️ HIGH PRIORITY: Code Duplication (700 lines)

**Location**: CommandLauncher - three launch methods

**Impact**:
- Bug fixes need 3 applications
- New features need 3 implementations
- High maintenance burden
- Defect probability increases

**Effort to Fix**: ~4-6 hours (extract template method)

**Risk**: HIGH - every change to launch flow is 3× work

---

#### 2. ⚠️ MEDIUM PRIORITY: Legacy Dependency Injection

**Location**: CommandLauncher.__init__ lines 98-139

```python
# Comments acknowledge this is deprecated
if raw_plate_finder is None:
    from raw_plate_finder import RawPlateFinder
    self._raw_plate_finder = RawPlateFinder
# ... 3 more similar blocks
```

**Impact**:
- Confusing API - mixed type[Class] and instances
- Technical debt acknowledged in code
- Backward compatibility burden

**Effort to Fix**: ~2-3 hours (remove deprecated code paths)

**Risk**: MEDIUM - marked for removal, affects existing consumers

---

#### 3. ⚠️ MEDIUM PRIORITY: Private Member Access

**Location**: ProcessExecutor, multiple methods

```python
if self.persistent_terminal._fallback_mode:  # pyright: ignore
```

**Impact**:
- Breaking encapsulation
- Requires type checker suppression
- Potential thread safety issues
- Fragile to PersistentTerminalManager refactoring

**Effort to Fix**: ~1 hour (add public property)

**Risk**: LOW - localized change

---

#### 4. ⚠️ LOW PRIORITY: Stateful Caching in EnvironmentManager

**Location**: EnvironmentManager._rez_available_cache, _available_terminal_cache

**Impact**:
- Requires instantiation for caching
- reset_cache() needed for testing
- More complex than necessary

**Effort to Fix**: ~2 hours (convert to static methods with @lru_cache)

**Risk**: LOW - internal implementation detail

---

### Architectural Smells

#### 1. 🔴 Feature Envy

**Location**: CommandLauncher

**Smell**: CommandLauncher knows too much about how to construct commands.

**Evidence**:
```python
# CommandLauncher doing CommandBuilder's job
ws_command = f"ws {safe_workspace_path} && {env_fixes}{command}"
full_command = f'rez env {packages_str} -- bash -ilc "{ws_command}"'
```

**Impact**: Responsibilities blurred between components.

**Fix**: Use CommandBuilder.build_full_command() consistently.

---

#### 2. 🔴 Long Method

**Location**: CommandLauncher.launch_app() - 293 lines

**Smell**: Single method doing too many things.

**Impact**: Hard to understand, test, and maintain.

**Fix**: Extract template method (see Section 3).

---

#### 3. 🔴 Long Parameter List

**Location**: CommandLauncher.launch_app() - 7 parameters

```python
def launch_app(
    self,
    app_name: str,
    include_raw_plate: bool = False,
    open_latest_threede: bool = False,
    open_latest_maya: bool = False,
    open_latest_scene: bool = False,
    create_new_file: bool = False,
    selected_plate: str | None = None,
) -> bool:
```

**Smell**: Too many parameters - violates clean code principles.

**Impact**: Hard to remember parameter order, easy to make mistakes.

**Fix**: Use LaunchOptions TypedDict (see Section 6).

---

#### 4. 🟡 Primitive Obsession

**Location**: Throughout - using `dict[str, bool]` instead of LaunchOptions

**Smell**: Using primitives instead of small objects.

**Impact**: Less type-safe, not self-documenting.

**Fix**: Use TypedDict for options (see Section 4).

---

#### 5. 🟡 Data Clumps

**Location**: workspace_path, app_name, command always travel together

**Smell**: Same group of variables passed around together.

**Impact**: Suggests missing abstraction.

**Fix**: Extract LaunchContext value object (see Section 6).

---

#### 6. 🟡 Middle Man

**Location**: CommandLauncher signal forwarding methods

```python
def _on_execution_started(self, operation: str, message: str) -> None:
    timestamp = datetime.now(tz=UTC).strftime("%H:%M:%S")
    self.command_executed.emit(timestamp, f"[{operation}] {message}")
```

**Smell**: Method just delegates to another method.

**Impact**: Adds indirection without value.

**Fix**: Consider direct signal connection or eliminate forwarding.

---

## 9. Architectural Risks

### Risk Matrix

| Risk | Severity | Probability | Impact | Mitigation |
|------|----------|-------------|--------|------------|
| Code Duplication | HIGH | HIGH | Bug fixes applied inconsistently | Extract template method (Phase 2) |
| Tight Config Coupling | MODERATE | MODERATE | Config changes break multiple components | Use Config Protocol |
| API Complexity | MODERATE | MODERATE | Users misuse launch methods | Unify to single launch() method |
| Legacy Injection | MODERATE | LOW | Confusing for new developers | Remove deprecated code |
| Memory Leak (No Parent) | LOW | LOW | CommandLauncher not cleaned up | Add parent parameter |
| Thread Safety (_fallback_mode) | LOW-MODERATE | LOW | Race condition in terminal check | Add public property with lock |

---

### Critical Path Fragility

**Launch Flow** (duplicated 3 times):
1. ✅ Validate workspace
2. Build command with app-specific logic
3. ✅ Detect terminal
4. ✅ Wrap with rez
5. ✅ Add logging
6. ✅ Execute with error handling

**Steps marked ✅ are duplicated** across all three launch methods.

**Fragility Analysis**:
- **Single Point of Failure**: Terminal detection - if it fails, all launches fail
- **Error Handling Consistency**: Same error handling in 3 places - easy to miss updates
- **Configuration Changes**: Config changes affect all 3 methods independently

**Risk**: Changes to launch flow require coordinated updates across 3 methods - high defect probability.

---

## 10. Recommended Improvements

### Immediate Improvements (Low Effort, High Impact)

#### 1. Extract Launch Flow Template Method (~4-6 hours)

**Priority**: 🔴 CRITICAL - Highest ROI

**Problem**: 700 lines of duplicated code across 3 launch methods.

**Solution**:
```python
class CommandLauncher:
    def _execute_launch(
        self,
        command: str,
        workspace_path: str,
        app_name: str,
        apply_nuke_fixes: bool = False,
    ) -> bool:
        """Template method for common launch flow."""
        # 1. Validate workspace
        if not self._validate_workspace_before_launch(workspace_path, app_name):
            return False

        # 2. Build full command
        full_command = self._build_full_command(
            command, workspace_path, app_name, apply_nuke_fixes
        )

        # 3. Log command
        self._log_command(full_command)

        # 4. Execute
        return self._execute_command(full_command, app_name)

    def _execute_command(self, command: str, app_name: str) -> bool:
        """Execute via persistent terminal or new terminal."""
        if self._can_use_persistent_terminal():
            return self._execute_in_persistent_terminal(command, app_name)
        return self._execute_in_new_terminal(command, app_name)

    def _execute_in_new_terminal(self, command: str, app_name: str) -> bool:
        """Spawn new terminal with comprehensive error handling."""
        terminal = self.env_manager.detect_terminal()
        if terminal is None:
            self._emit_error("No terminal emulator found...")
            return False

        try:
            term_cmd = self._build_terminal_command(terminal, command)
            process = subprocess.Popen(term_cmd)
            QTimer.singleShot(
                100, partial(self.process_executor.verify_spawn, process, app_name)
            )
            return True
        except FileNotFoundError as e:
            return self._handle_file_not_found_error(e, app_name)
        except PermissionError as e:
            return self._handle_permission_error(e, app_name)
        except OSError as e:
            return self._handle_os_error(e, app_name)
        except Exception as e:
            return self._handle_generic_error(e, app_name)
```

**Benefits**:
- ✅ Reduces duplication from ~700 lines to ~150 lines
- ✅ Single point of change for bug fixes
- ✅ DRY compliant
- ✅ Easier to test
- ✅ Reduces CommandLauncher from 961 lines to ~400 lines

**Effort**: 4-6 hours
**Risk**: LOW - backward compatible, tests verify behavior
**Impact**: HIGH - eliminates primary architectural debt

---

#### 2. Add Parent Parameter to CommandLauncher (~30 mins)

**Priority**: 🟡 MEDIUM

**Problem**: CommandLauncher doesn't accept parent, violates Qt best practices.

**Solution**:
```python
def __init__(
    self,
    raw_plate_finder: type[RawPlateFinderType] | None = None,
    nuke_script_generator: type[NukeScriptGeneratorType] | None = None,
    threede_latest_finder: type[ThreeDELatestFinderType] | None = None,
    maya_latest_finder: type[MayaLatestFinderType] | None = None,
    persistent_terminal: PersistentTerminalManager | None = None,
    parent: QObject | None = None,  # ✅ Add this
) -> None:
    super().__init__(parent)  # ✅ Pass to QObject
```

**Benefits**:
- ✅ Fixes Qt ownership
- ✅ Prevents memory leaks
- ✅ Consistent with ProcessExecutor

**Effort**: 30 minutes
**Risk**: LOW - simple addition
**Impact**: MEDIUM - prevents memory issues

---

#### 3. Use TypedDict for Launch Options (~1-2 hours)

**Priority**: 🟡 MEDIUM

**Problem**: `dict[str, bool]` is not self-documenting or type-safe.

**Solution**:
```python
class LaunchOptions(TypedDict, total=False):
    """Options for launching applications."""
    open_latest_scene: bool
    create_new_file: bool
    include_raw_plate: bool
    open_latest_threede: bool
    open_latest_maya: bool

def launch_app(self, app_name: str, options: LaunchOptions | None = None) -> bool:
```

**Benefits**:
- ✅ IDE autocomplete
- ✅ Type-safe - typos caught
- ✅ Self-documenting

**Effort**: 1-2 hours
**Risk**: LOW - incremental improvement
**Impact**: MEDIUM - better developer experience

---

### Medium-Term Refactoring (4-8 hours)

#### 4. Extract LaunchContext ValueObject (~2 hours)

**Priority**: 🟡 MEDIUM

**Problem**: workspace_path, app_name, command always travel together.

**Solution**:
```python
@dataclass(frozen=True)
class LaunchContext:
    """Context for application launch."""
    shot: Shot
    workspace_path: str
    app_name: str
    command: str
    selected_plate: str | None = None
    scene: ThreeDEScene | None = None

def _execute_launch(self, context: LaunchContext, options: LaunchOptions) -> bool:
```

**Benefits**:
- ✅ Reduces parameter passing
- ✅ Groups related data
- ✅ Type-safe value object

**Effort**: 2 hours
**Risk**: LOW - internal refactoring
**Impact**: MEDIUM - cleaner code

---

#### 5. Replace `type[Config]` with Protocol (~2-3 hours)

**Priority**: 🟡 MEDIUM

**Problem**: Tight coupling to Config class.

**Solution**:
```python
class LaunchConfigProtocol(Protocol):
    USE_REZ_ENVIRONMENT: bool
    REZ_AUTO_DETECT: bool
    APPS: dict[str, str]
    PERSISTENT_TERMINAL_ENABLED: bool
    USE_PERSISTENT_TERMINAL: bool

class EnvironmentManager:
    def is_rez_available(self, config: LaunchConfigProtocol) -> bool:
```

**Benefits**:
- ✅ Loose coupling
- ✅ Easy mocking
- ✅ Clear interface

**Effort**: 2-3 hours
**Risk**: LOW - protocol matches existing usage
**Impact**: MEDIUM - better testability

---

#### 6. Remove Legacy Dependency Injection (~2-3 hours)

**Priority**: 🟡 MEDIUM

**Problem**: Deprecated code creates confusion.

**Solution**: Delete lines 98-139 in CommandLauncher.__init__, update call sites.

**Benefits**:
- ✅ Cleaner code
- ✅ Less confusing
- ✅ Removes technical debt

**Effort**: 2-3 hours (includes updating tests)
**Risk**: MEDIUM - breaking change, but deprecated
**Impact**: MEDIUM - debt removal

---

### Long-Term Architecture (1-2 weeks)

#### 7. Unify Launch API (~1 week)

**Priority**: 🔵 LOW (after immediate improvements)

**Problem**: Three launch methods create confusion.

**Solution**:
```python
def launch(
    self,
    app: AppName,
    context: LaunchContext,
    options: LaunchOptions | None = None,
) -> Result[None, LaunchError]:
    """Unified launch method."""
```

**Benefits**:
- ✅ Single, clear API
- ✅ Result-based error handling
- ✅ Extensible

**Effort**: 1 week (includes migration)
**Risk**: HIGH - breaking change
**Impact**: HIGH - major API improvement

---

#### 8. Implement Result Types (~3-4 days)

**Priority**: 🔵 LOW

**Problem**: Boolean returns don't explain failures.

**Solution**: Use Result[T, E] pattern throughout.

**Effort**: 3-4 days
**Risk**: MEDIUM - requires library or Python 3.13+
**Impact**: HIGH - explicit error handling

---

#### 9. Add LaunchStrategy Interface (~2-3 days)

**Priority**: 🔵 LOW

**Problem**: Strategy pattern is implicit.

**Solution**:
```python
class LaunchStrategy(Protocol):
    def prepare_command(self, shot: Shot, options: LaunchOptions) -> tuple[str, list[str]]: ...

class SimpleLaunchStrategy: ...
class ComplexLaunchStrategy: ...
```

**Effort**: 2-3 days
**Risk**: LOW - internal refactoring
**Impact**: MEDIUM - clearer architecture

---

#### 10. Convert to Command Pattern (~1 week)

**Priority**: 🔵 LOW (future enhancement)

**Problem**: No undo/logging of launch commands.

**Solution**: Implement Command pattern for launches.

**Effort**: 1 week
**Risk**: MEDIUM - architectural change
**Impact**: LOW-MEDIUM - enables undo, better logging

---

## 11. Testing Assessment

### Test Coverage

The refactoring includes comprehensive test suites:

**Launch Components**:
- `test_command_builder.py` - 6 test classes covering path validation, command assembly
- `test_environment_manager.py` - 4 test classes covering rez detection, terminal detection, caching
- `test_process_executor.py` - 6 test classes covering GUI detection, terminal execution, signals

**Launch Methods**:
- `test_command_launcher.py` - Full CommandLauncher tests
- `test_nuke_launch_handler.py` - Nuke-specific tests
- `test_nuke_launch_router.py` - Routing logic tests
- `test_simple_nuke_launcher.py` - Simple launcher tests

**Integration Tests**:
- `test_launcher_workflow_integration.py`
- `test_launcher_panel_integration.py`
- `test_threede_launch_signal_fix.py`

**Assessment**: ✅ Test coverage is EXCELLENT - extracted components have dedicated test suites.

**Gap**: Template method extraction will need new tests, but existing tests provide safety net.

---

## 12. Long-Term Maintainability Analysis

### Maintainability Score: **B** (Good, with improvements needed)

**Strengths** (60%):
- ✅ Clear component separation (EnvironmentManager, CommandBuilder, ProcessExecutor)
- ✅ Signal-based communication for async operations
- ✅ Comprehensive test coverage
- ✅ Type hints throughout
- ✅ Security-focused validation (CommandBuilder)
- ✅ Good documentation and comments

**Weaknesses** (40%):
- ❌ Code duplication (700 lines) - PRIMARY ISSUE
- ❌ Complex launch API (7 parameters, 3 methods)
- ❌ Config coupling throughout
- ❌ Legacy dependency injection
- ❌ Private member access
- ❌ No Result types for error handling

### Trajectory Assessment

**Without Further Refactoring**:
- Maintainability will **DECLINE** over time
- Code duplication will lead to inconsistent bug fixes
- API complexity will confuse new developers
- Technical debt will accumulate

**With Immediate Improvements** (Phase 2):
- Maintainability will **IMPROVE** significantly
- Template method eliminates duplication
- Cleaner API reduces confusion
- Better foundation for future enhancements

**Recommended Timeline**:
1. **Phase 2** (Immediate - 1 week): Template method + parent parameter + TypedDict
2. **Phase 3** (Medium-term - 1-2 weeks): LaunchContext + Config Protocol + Remove legacy code
3. **Phase 4** (Long-term - 1 month): Unified API + Result types + Strategy interface

---

## 13. Summary: Design Strengths and Weaknesses

### 🟢 Design Strengths

1. **Clear Component Separation**: EnvironmentManager, CommandBuilder, ProcessExecutor are well-focused
2. **Signal-Based Communication**: Excellent use of Qt signals for async operations
3. **Security-Conscious**: CommandBuilder has robust injection prevention
4. **Functional Design**: CommandBuilder's static methods are composable and testable
5. **Dependency Injection**: ProcessExecutor properly injects dependencies
6. **Type Safety**: Comprehensive type hints throughout
7. **Test Coverage**: Excellent test suites for extracted components
8. **Qt Integration**: Proper signal usage, mostly correct parent handling

### 🔴 Design Weaknesses

1. **Code Duplication** (CRITICAL): ~700 lines duplicated across 3 launch methods
2. **CommandLauncher Still Too Large**: 961 lines with too many responsibilities
3. **Complex API**: 7 parameters on launch_app(), 3 overlapping launch methods
4. **Config Coupling**: type[Config] pattern creates tight coupling throughout
5. **Legacy Injection**: Deprecated dependency injection creates confusion
6. **Private Member Access**: Breaking encapsulation with _fallback_mode
7. **Hardcoded Configuration**: GUI_APPS not extensible
8. **Missing Parent Parameter**: CommandLauncher violates Qt ownership best practices
9. **No Result Types**: Boolean returns don't explain failure reasons
10. **Primitive Obsession**: Using dict[str, bool] instead of TypedDict

---

## 14. Conclusion

**Phase 1 Status**: ✅ **SUCCESSFUL**

The extraction of EnvironmentManager, CommandBuilder, and ProcessExecutor represents significant architectural progress. These components are well-designed, focused, and maintainable.

**Phase 2 Critical**: ⚠️ **REQUIRED**

However, CommandLauncher remains at 961 lines with ~700 lines of code duplication. This is the **highest-priority architectural debt** that must be addressed to maintain long-term code health.

**Recommended Next Steps**:

1. **Immediate** (1 week):
   - Extract launch flow template method (4-6 hours)
   - Add parent parameter to CommandLauncher (30 mins)
   - Use TypedDict for LaunchOptions (1-2 hours)

2. **Medium-term** (1-2 weeks):
   - Extract LaunchContext value object
   - Replace type[Config] with Protocol
   - Remove legacy dependency injection

3. **Long-term** (1+ month):
   - Unify launch API to single method
   - Implement Result types
   - Add explicit LaunchStrategy interface

**Overall Architecture Grade**: **B** (Good foundations, critical duplication issue)

With Phase 2 improvements, this would become an **A** architecture - clean, maintainable, and extensible.

---

**End of Architectural Assessment**
