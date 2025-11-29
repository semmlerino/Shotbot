# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Shotbot is a PySide6-based GUI application for VFX production management. The application provides shot tracking, media management, and workflow automation for visual effects pipelines.

## Security Posture

**This is a personal tool running in an isolated VFX production environment.** Security vulnerabilities are NOT a concern for this project.

**Acceptable patterns that would be security issues in other contexts:**
- ✅ `subprocess.Popen(..., shell=True)` - Needed for complex shell commands
- ✅ `eval()` in bash scripts - Simplifies command execution
- ✅ Command injection vectors - Controlled input from trusted user
- ✅ Path traversal - User has full filesystem access anyway
- ✅ Untrusted input handling - All input is from single trusted user

**Why security is not a priority:**
- Single user (developer) on isolated VFX server
- No network exposure or remote access
- No untrusted input sources
- User has full filesystem and process access
- Flexibility and convenience > security hardening

**Code review focus areas:**
- ✅ Correctness and reliability
- ✅ Performance and resource management
- ✅ Maintainability and code organization
- ✅ Qt best practices and thread safety
- ❌ NOT security vulnerabilities (acceptable trade-off)

## Development Environment

### Primary Development Location (Linux Filesystem)
**The codebase resides on the Linux filesystem for optimal performance**:

- **Primary Location**: `~/projects/shotbot` (Linux native filesystem)
- **Symlink**: `/mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot` → `~/projects/shotbot`
- **Performance**: ~7.5x faster than Windows filesystem (`/mnt/c`)
  - Test suite: 16s (Linux) vs 120s (Windows)
  - Type checking: 6s (Linux) vs 15-20s (Windows)
  - Dependency install: <0.5s (Linux) vs 5-10s (Windows)

**Both paths work identically** due to the symlink, but all file I/O occurs on the fast Linux filesystem.

### Deployment Environment

**Shotbot runs on a remote VFX production environment**, not on the development machine:

- **Production Location**: `/nethome/gabriel-h/Python/Shotbot/` (Remote Linux VFX server)
- **Deployment Method**: Encoded bundle transfer via `encoded-releases` branch

### Encoded Bundle System
The application uses an automated encoding/deployment system:

1. **Development**: Code changes are committed to `master` branch
2. **Auto-Encoding**: Post-commit hook automatically creates base64-encoded bundle
3. **Auto-Push**: Bundle is pushed to `encoded-releases` branch on GitHub
4. **Remote Deployment**: Bundle is pulled and decoded on the VFX server
5. **Execution**: Application runs in production environment with VFX tools

**Bundle Files**:
- `shotbot_latest.txt` - Base64-encoded compressed application bundle
- `shotbot_latest_metadata.json` - Bundle metadata (commit info, size, timestamp)

### Why This Architecture?
- **Isolated Environments**: Dev machine (Windows/WSL) ≠ Production (Linux VFX pipeline)
- **Dependency Isolation**: VFX environment has specific Python/Qt versions
- **Easy Deployment**: Single base64 file transfer instead of complex file sync
- **Version Control**: GitHub acts as deployment artifact repository

## Development Commands

**All commands should be run from the Linux filesystem location** for best performance:

```bash
cd ~/projects/shotbot  # Or cd /mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot (symlink)
```

### Running Locally (Development)
```bash
# Run the application
~/.local/bin/uv run python shotbot.py
```

### Testing Before Deployment
```bash
# Run type checking (6 seconds on Linux)
~/.local/bin/uv run basedpyright

# Run linting
~/.local/bin/uv run ruff check .

# Run tests (serial execution – easiest when iterating on a single module)
~/.local/bin/uv run pytest tests/

# Run the full suite with parallelism (recommended before deployment)
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup
# or pin worker count if you prefer
~/.local/bin/uv run pytest tests/ -n 2 --dist=loadgroup
```

**Test Execution Notes**:
- Default `pytest tests/` still runs serially (good for quick local loops)
- Full regression now passes with `-n auto --dist=loadgroup` thanks to the early
  QApplication bootstrap, qtbot wait patch, and automatic grouping of Qt-heavy suites
- If you need deterministic timing, cap workers (e.g., `-n 4 --dist=loadgroup`)
- Individual files generally don’t need `--dist=loadgroup`, but keep it for
  whole-suite runs so Qt fixtures share the serialized worker
- Qt state cleanup between tests relies on `process_qt_events()` (see Qt Widget
  Guidelines below); avoid adding raw `qtbot.wait(1)` calls

### Creating Deployment Bundle
The bundle is automatically created on commit, but can be manually triggered:
```bash
# Manual bundle creation
~/.local/bin/uv run python bundle_app.py -c transfer_config.json

# Check bundle was created
ls -lh encoded_app_*.txt
```

### Deploying to Remote Environment
On the **remote VFX server**:
```bash
# Pull latest encoded release
git checkout encoded-releases
git pull origin encoded-releases

# Decode and extract bundle
python decode_app.py shotbot_latest.txt

# Run the application
cd shotbot_bundle_temp
python shotbot.py
```

## Import Errors and Debugging

### Common Import Issues
If you see import errors like:
```
ImportError: cannot import name 'Config' from 'config'
```

This typically means:
1. **Bundle is out of sync** - The encoded bundle doesn't match current codebase
2. **Missing file in bundle** - `transfer_config.json` doesn't include the file
3. **Import path mismatch** - Module structure changed but imports weren't updated

### Fixing Import Errors
1. **Verify Local Imports Work**:
   ```bash
   ~/.local/bin/uv run python -c "from config import AppConfig; print('OK')"
   ```

2. **Check transfer_config.json**:
   ```bash
   cat transfer_config.json
   ```
   Ensure all required files are included in the bundle.

3. **Regenerate Bundle**:
   ```bash
   # Commit changes to trigger auto-bundle
   git commit -m "fix: Update imports"

   # Or manually create bundle
   ~/.local/bin/uv run python bundle_app.py -c transfer_config.json
   ```

4. **Test Decoded Bundle Locally**:
   ```bash
   python decode_app.py shotbot_latest.txt
   cd shotbot_bundle_temp
   python shotbot.py
   ```

## Auto-Push System

### Post-Commit Hook
The `.git/hooks/post-commit` script automatically:
1. Runs type checking and linting
2. Creates encoded application bundle
3. Copies bundle to `encoded_releases/` directory
4. Launches background script to push to GitHub

**Important**: The hook uses the virtual environment Python:
- `$PROJECT_ROOT/.venv/bin/python3` for all operations
- Ensures PySide6 and other dependencies are available

### Background Push Script
The `.git/hooks/push_bundle_background.sh` script:
1. Switches to `encoded-releases` branch
2. Updates `shotbot_latest.txt` and metadata
3. Commits and pushes to `origin/encoded-releases`
4. Switches back to original branch

### Troubleshooting Auto-Push
Check the logs in `.post-commit-output/`:
- `bundle.txt` - Bundle creation log
- `bundle-push.log` - Push to encoded-releases log
- `import-test.txt` - Import validation results
- `type-check.txt` - Type checking results

## Dependencies

### Development Environment
**Core Dependencies**:
- Python 3.11+ (via uv)
- PySide6 (Qt for Python)
- Pillow (PIL - image processing)
- psutil (system and process utilities)

**Development Tools**:
- basedpyright (type checking)
- ruff (linting and formatting)
- pytest, pytest-qt, pytest-xdist, pytest-timeout, pytest-mock
- hypothesis (property-based testing)

**Installation**:
```bash
cd ~/projects/shotbot
~/.local/bin/uv pip install -r requirements.txt
```

### Production Environment (VFX Server)
- Python 3.x (VFX pipeline version)
- PySide6 (matching VFX pipeline)
- Various VFX tools and libraries

**Note**: Production dependencies may differ from development. The encoded bundle is self-contained but requires compatible Python/Qt versions on the target system.

## Project Structure

```
shotbot/
├── controllers/       # Application controllers (launcher, settings, 3DE)
├── core/             # Core type definitions (shot_types.py)
├── launcher/         # Custom launcher system (models, repository, workers)
├── launch/           # Process execution (command building, env management)
├── tests/            # Test suite
│   ├── fixtures/     # Modular test fixtures
│   ├── integration/  # Integration tests
│   └── unit/         # Unit tests
├── docs/             # Documentation
├── .git/hooks/       # Git hooks for auto-push
├── shotbot.py        # Main entry point
├── main_window.py    # Main application window
├── command_launcher.py # Production app launcher
├── cache_manager.py  # Persistent caching system
├── singleton_mixin.py # Thread-safe singleton base class
├── bundle_app.py     # Bundle encoding script
├── decode_app.py     # Bundle decoding script
├── transfer_config.json  # Bundle configuration
└── encoded_releases/ # Local copy of encoded bundles
```

## Type Safety

The project uses basedpyright for type checking with strict settings:
- All refactored code has comprehensive type hints
- `reportOptionalMemberAccess` enabled (no suppressions)
- Configuration in `pyproject.toml` and `pyrightconfig.json`

Current status: **0 errors, 0 warnings, 0 notes** ✅

## Singleton Pattern & Test Isolation

**All singleton classes should inherit from `SingletonMixin`** which provides thread-safe singleton behavior and automatic `reset()` for test isolation:

```python
from singleton_mixin import SingletonMixin

class MySingleton(SingletonMixin):
    """Example singleton using the mixin."""

    def _initialize(self) -> None:
        """Called once when singleton is first created."""
        self._my_state = {}

    @classmethod
    def _cleanup_instance(cls) -> None:
        """Optional: Custom cleanup before reset. Override if needed."""
        if cls._instance is not None:
            cls._instance._my_state.clear()
```

**Why this matters:**
- Enables parallel test execution (`pytest -n auto`)
- Prevents test contamination from singleton state
- `SingletonMixin.reset()` handles thread-safe cleanup automatically
- Used by `tests/fixtures/singleton_registry.py` for centralized cleanup

**Existing singletons using SingletonMixin:**
- `ProgressManager` - Clears operation stack, closes dialogs
- `NotificationManager` - Calls cleanup(), resets instance
- `ProcessPoolManager` - Calls shutdown(), resets instance
- `FilesystemCoordinator` - Clears directory cache

**When creating new singletons:**
1. Inherit from `SingletonMixin`
2. Implement `_initialize()` for first-time setup
3. Optionally override `_cleanup_instance()` for custom cleanup
4. Register in `tests/fixtures/singleton_registry.py`

## Qt Widget Guidelines

### Parent Parameter Requirement
**ALL QWidget subclasses MUST accept an optional parent parameter** and pass it to `super().__init__()`:

```python
class MyWidget(QtWidgetMixin, QWidget):
    """Example widget with proper parent handling."""

    def __init__(
        self,
        # ... other parameters ...
        parent: QWidget | None = None,  # ✅ REQUIRED
    ) -> None:
        """Initialize widget.

        Args:
            parent: Optional parent widget for proper Qt ownership
        """
        super().__init__(parent)  # ✅ REQUIRED - pass parent to Qt
        # ... rest of initialization ...
```

**Why This Matters**:
- Missing parent parameter causes Qt C++ crashes during initialization
- Crashes occur even in serial (non-parallel) test execution
- Error manifests as `Fatal Python error: Aborted` at `logging_mixin.py:269` → `qt_widget_mixin.py:63` → Qt C++
- Fix verified: Adding parent parameter resolved 36+ test failures

**Common Mistake**:
```python
# ❌ WRONG - No parent parameter
def __init__(self, cache_manager: CacheManager | None = None) -> None:
    super().__init__()  # Qt C++ will crash!

# ✅ CORRECT - Accept and pass parent
def __init__(
    self,
    cache_manager: CacheManager | None = None,
    parent: QWidget | None = None,
) -> None:
    super().__init__(parent)  # Qt handles ownership properly
```

### Qt State Cleanup in Tests
Tests using Qt widgets should include cleanup fixtures:

```python
@pytest.fixture(autouse=True)
def cleanup_qt_state(qtbot: QtBot):
    """Autouse fixture to ensure Qt state is cleaned up after each test."""
    yield
    process_qt_events()  # Provided by tests.test_helpers
```

> ℹ️ `process_qt_events` lives in `tests.test_helpers` and is also used by the
> session autouse patch that reroutes tiny `qtbot.wait()` calls, so keep using it
> (or `qtbot.waitUntil`) instead of raw `qtbot.wait(1)`.

## Testing

**📖 See [UNIFIED_TESTING_V2.MD](./UNIFIED_TESTING_V2.MD) for comprehensive testing guidance**, including:
- Quick Start commands
- 5 Basic Qt Testing Hygiene Rules (essential for reliable tests)
- Test isolation and parallel execution patterns
- Qt-specific testing patterns and pitfalls
- Debugging workflows and common issues

### Test Fixture Architecture

Test fixtures are organized in modular files under `tests/fixtures/`:

| Module | Purpose |
|--------|---------|
| `determinism.py` | Seed control for reproducible tests |
| `temp_directories.py` | Temporary directory management |
| `test_doubles.py` | Mock objects and test doubles |
| `subprocess_mocking.py` | Subprocess isolation |
| `qt_safety.py` | Qt thread safety validation |
| `qt_cleanup.py` | Qt state cleanup between tests |
| `singleton_isolation.py` | Singleton reset fixtures |
| `singleton_registry.py` | Central registry for singleton cleanup |
| `caching.py` | Cache isolation and behavior testing |
| `data_factories.py` | Test data generation |

**Session-scoped Qt fixtures** (`qapp`, `_patch_qtbot_short_waits`) remain in `tests/conftest.py` for proper xdist compatibility.

**Key fixture: `process_qt_events()`** - Use this instead of `qtbot.wait(1)` for Qt event processing:
```python
from tests.test_helpers import process_qt_events

# In test cleanup
process_qt_events()  # ✅ Process pending Qt events
model.deleteLater()
process_qt_events()  # ✅ Execute deleteLater
```

### Current Test Status
- **3,100+ tests passing** (`pytest tests/ -n auto --dist=loadgroup`)
- Grouped-parallel runs match serial reliability thanks to the early QApplication
  bootstrap, qtbot wait patch, and xdist grouping
- Comprehensive coverage across:
  - Core business logic
  - Controllers and managers
  - UI components (Qt widgets)
  - Integration scenarios

### Quick Start
```bash
# Full regression (Qt-safe parallel)
~/.local/bin/uv run pytest tests/ -n auto --dist=loadgroup

# Cap worker count if needed
~/.local/bin/uv run pytest tests/ -n 4 --dist=loadgroup

# Serial run (quick local loop)
~/.local/bin/uv run pytest tests/

# Single test / subset
~/.local/bin/uv run pytest tests/unit/test_shot_model.py -v
~/.local/bin/uv run pytest tests/ -k "test_cache" -v
```

### Debugging Test Failures and Crashes

**CRITICAL: When debugging test failures or crashes, do NOT use lossy pipes like `grep | head`.**

Hard aborts (Fatal Python error, segfaults) often don't print nice FAILED/ERROR lines, and piping throws away the diagnostic output you need.

**Step 1: Run ONE diagnostic test with full output to a log file**
```bash
cd ~/projects/shotbot
export PYTHONFAULTHANDLER=1 && ~/.local/bin/uv run pytest tests/unit/ \
  -vv -x --maxfail=1 --tb=short -s \
  --log-cli-level=DEBUG \
  2>&1 | tee /tmp/shotbot_pytest_diag.log
```

What each flag buys you:
- `PYTHONFAULTHANDLER=1` → stack trace even on hard aborts
- `-vv` → show which tests are running, not just dots
- `-x --maxfail=1` → stop on first failure/crash
- `-s` → let prints/logging through
- `--log-cli-level=DEBUG` → logging handlers surface
- `tee /tmp/shotbot_pytest_diag.log` → persistent log to inspect

**Step 2: Inspect the log, DON'T rerun tests**
```bash
# Top of run
sed -n '1,160p' /tmp/shotbot_pytest_diag.log

# Last part of run
tail -n 120 /tmp/shotbot_pytest_diag.log

# Find fatal errors / tracebacks
grep -n "Fatal Python error" /tmp/shotbot_pytest_diag.log || true
grep -n "Traceback" /tmp/shotbot_pytest_diag.log | tail -20

# Zoom in around a line number
sed -n '320,380p' /tmp/shotbot_pytest_diag.log
```

**Step 3: Narrow to specific file/test once crash is understood**
```bash
# Single file
~/.local/bin/uv run pytest tests/unit/test_specific.py \
  -vv -x --tb=short -s 2>&1 | tee /tmp/shotbot_pytest_diag.log

# Single test
~/.local/bin/uv run pytest tests/unit/test_specific.py::TestClass::test_method \
  -vv --tb=short -s 2>&1 | tee /tmp/shotbot_pytest_diag.log
```

**For Qt/PySide crashes, add:**
```bash
QT_DEBUG_PLUGINS=1 QT_QPA_PLATFORM=offscreen ~/.local/bin/uv run pytest ...
```

### Test Coverage

```bash
# Coverage is disabled by default for faster local runs
# Run with coverage manually:
~/.local/bin/uv run pytest tests/ --cov=. --cov-report=term-missing --cov-report=html:coverage_html

# View the HTML report
open coverage_html/index.html
```

#### Coverage Exclusions

Coverage reports may show lower percentages due to **intentional exclusions** of code that:
1. **Requires external VFX software** (Nuke, Maya, 3DEqualizer)
2. **Is primarily visual/interactive** (GUI widgets tested manually)
3. **Is legacy/deprecated** (archived code paths)

**Excluded from coverage** (see `pyproject.toml` `[tool.coverage.run]` → `omit`):
- **VFX integrations**: `nuke_*.py`, `maya_*.py`, `threede_*.py`
  - Require external software (Nuke, Maya, 3DEqualizer)
  - Tested manually in production environment
  - Low ROI for automated testing
- **GUI components**: `ui_components.py`, `accessibility_manager.py`, `thumbnail_widget*.py`
  - Primarily visual presentation
  - Tested via integration tests and manual QA
  - Hard to test comprehensively with automated tests

**Well-covered modules** (comprehensive test suites):
- ✅ **Core models**: `shot_model.py`, `type_definitions.py` (86%+)
- ✅ **Managers**: `cache_manager.py`, `settings_manager.py` (comprehensive)
- ✅ **Controllers**: `launcher_controller.py`, `threede_controller.py`
- ✅ **Business logic**: Shot validation, cache management, settings persistence

**Why exclude instead of test?**
- **VFX tools**: Would require mocking entire VFX applications (Nuke, Maya, etc.)
- **GUI widgets**: Visual testing requires manual QA or screenshot comparison
- **ROI trade-off**: Core business logic coverage is more valuable than GUI cosmetics

**Interpreting coverage numbers:**
- Overall coverage (~18-30%) includes excluded GUI/VFX code
- Core business logic coverage is **much higher** (70-90%+)
- Focus on **critical path coverage** (data integrity, cache, state management)

## Caching System

Shotbot uses persistent caching for performance optimization, with different strategies for different data types.

### My Shots Cache
- **File**: `~/.shotbot/cache/production/shots.json`
- **TTL**: 30 minutes (configurable)
- **Behavior**: Time-based expiration with manual refresh
- **Strategy**: Complete replacement on refresh

### Previous Shots Cache
- **File**: `~/.shotbot/cache/production/previous_shots.json`
- **TTL**: None (persistent)
- **Behavior**: Incremental accumulation
- **Strategy**: New shots added, old shots preserved indefinitely

### Other 3DE Scenes Cache
- **File**: `~/.shotbot/cache/production/threede_scenes.json`
- **TTL**: None (persistent) - Changed from 30 minutes
- **Behavior**: Persistent incremental caching
- **Strategy**:
  - Discovers all .3de files from all users across all shows
  - New scenes are added to cache
  - Previously cached scenes are preserved (even if not found in current scan)
  - Deduplication keeps one scene per shot (best by mtime + plate priority)
  - Deleted .3de files remain in cache (preserves history)

**Implementation Details**:
- Uses `CacheManager.get_persistent_threede_scenes()` - no TTL check
- Uses `CacheManager.merge_scenes_incremental()` - merges cached + fresh data
- Deduplication applied AFTER merge (ensures latest/best scene wins)
- Shot-level key `(show, sequence, shot)` for uniqueness
- Cache grows unbounded (limited by # of unique shots in production)

**Cache Workflow**:
1. Load persistent cache (no expiration)
2. Discover fresh scenes from filesystem
3. Merge: cached scenes + fresh scenes
4. Deduplicate: keep best scene per shot
5. Cache merged result (refreshes file timestamp)

**Benefits**:
- Faster startup (scenes load from cache immediately)
- Preserves scene history (deleted files remain visible)
- Incremental updates (only new discoveries processed)
- No cache expiration (persistent across restarts)

**Clear Cache** (if needed):
```python
cache_manager.clear_cache()  # Clears all caches including 3DE scenes
```

## Launcher System Architecture

### CommandLauncher (Production Launcher)

**CommandLauncher is the production launcher system** for application launching with shot context.

**File**: `command_launcher.py`

**Features**:
- Application launching with shot context
- Rez environment integration
- LaunchContext API for flexible launch options
- Scene-based launching support
- Spawns new terminal windows for each command

**Usage**:
```python
from command_launcher import CommandLauncher, LaunchContext

# Initialize
launcher = CommandLauncher(parent=self)

# Launch with context
context = LaunchContext(
    include_raw_plate=True,
    open_latest_threede=False,
    create_new_file=True
)
launcher.launch_app("nuke", context)
```

### Launcher Architecture

**Current Production Stack**:
- **CommandLauncher**: Application launching with shot context
- **LauncherManager**: Custom launcher management
- **ProcessPoolManager**: Process pool functionality

## VFX Environment Architecture

This section documents how the BlueBolt VFX environment works, which is critical for understanding the launcher system.

### Shell Initialization Chain

When a user logs in or opens a terminal, the following chain executes:

```
~/.bashrc
  → /etc/bashrc
    → bashrc.env
      → setbbplatform ${BLUEBOLT_PLATFORM}  ← REZ INITIALIZED HERE
        → Sets REZ_USED, loads rez packages, configures app paths
```

**Key insight**: Rez is initialized at shell startup, NOT by the `ws` command.

### The `ws` Command

`ws` is an alias to the `workspace` shell function that:
1. Generates a temporary workspace file via `$WRAPPERS/write_workspace_file`
2. Sources the generated file (sets SHOW, SEQUENCE, SHOT, WORKSPACE_PATH)
3. Sources hierarchical `env.sh` files for show/sequence/shot config
4. Does **NOT** handle Rez - Rez is already available from shell init

**Example**:
```bash
ws /shows/myshow/shots/sq010/sh0010
# Sets: SHOW=myshow, SEQUENCE=sq010, SHOT=sh0010, WORKSPACE_PATH=/shows/...
```

### Why `bash -ilc` is Required

Shell commands in the launcher use `bash -ilc` (interactive login shell) because:
- The `ws` function is defined in `.bashrc` (interactive shell config)
- Without `-i`, bash won't source `.bashrc` and `ws` won't be available
- The `-l` flag ensures login shell profile is also loaded
- The ~50ms startup overhead is acceptable for reliability

### Key Environment Variables

| Variable | Set By | Purpose |
|----------|--------|---------|
| `REZ_USED` | setbbplatform | Indicates Rez environment is active |
| `SHOW` | ws command | Current show name |
| `SEQUENCE` | ws command | Current sequence |
| `SHOT` | ws command | Current shot |
| `WORKSPACE_PATH` | ws command | Full workspace path |
| `SHOWS_ROOT` | bashrc.env | Root path for all shows (default: `/shows`) |

### Configuration: `REZ_MODE`

In `config.py`, the `REZ_MODE` setting (a `RezMode` enum) controls Rez wrapping behavior:

```python
class RezMode(Enum):
    DISABLED = auto()  # Never wrap with rez
    AUTO = auto()      # Skip if REZ_USED is set (BlueBolt default)
    FORCE = auto()     # Always wrap with app-specific packages
```

- **`RezMode.AUTO` (default)**: Skip outer Rez wrapping if `REZ_USED` env var is set because:
  - Shell initialization already set up Rez before `ws` runs
  - `REZ_USED` environment variable indicates Rez is active
  - Double-wrapping would cause package conflicts

- **`RezMode.DISABLED`**: Never wrap with Rez (for non-Rez environments)

- **`RezMode.FORCE`**: Always wrap with app-specific Rez packages

`AUTO` is correct for BlueBolt's environment. Other VFX facilities may need `DISABLED` or `FORCE` depending on their shell initialization.

### Debugging VFX Environment Issues

```bash
# Check if Rez is initialized
echo $REZ_USED  # Should show "1" if rez is active

# Check ws function availability
type ws  # Should show "ws is aliased to `workspace'"

# Debug ws command
DEBUG=1 ws /shows/myshow/shots/sq010/sh0010

# Trace shell init
bash -xl -c "echo done" 2>&1 | head -100
```

