Shotbot is a PySide6 GUI for matchmove workflow execution at BlueBolt (`3DEqualizer -> Maya -> Nuke -> Publish`). Single-user tool in an isolated VFX environment.

**Python version:** Target Python 3.10+. Do not use 3.11-only stdlib APIs or typing features unless the file already guards them. Use `typing_extensions` when needed.

**Security posture:** Single-user internal tool. Do not generate generic web-app audit noise, but do not introduce unsafe shell or path handling when writing new code. Prioritize correctness, maintainability, performance, and Qt thread safety.

## Project Layout

Application modules live at the repository root (no `src/` package), organized into domain packages. Key directories:

- `cache/` — cache abstraction layer (shot, thumbnail, scene, latest-file)
- `controllers/` — business logic orchestrators for UI coordination
- `deploy/` — bundle, encode, and decode for deployment pipeline
- `dcc/` — DCC file table and integration components
- `discovery/` — file/thumbnail/plate discovery, latest-file finding, frame range extraction
- `nuke/` — Nuke launch handling, script generation, workspace management
- `launch/` — DCC launcher implementations, command launching, RV integration
- `commands/` — command builders for DCC execution
- `managers/` — persistence managers (pins, notes, hide, settings, notifications, progress)
- `workers/` — threading infrastructure (ThreadSafeWorker, ProcessPoolManager, QRunnableTracker, diagnostics)
- `paths/` — path construction, validation, and filesystem coordination
- `previous_shots/` — previous-shots model and persistence
- `ui/` — base grid views, item models, delegates, design system, dialogs
- `tests/` — test suite (`unit/`, `integration/`, `regression/`, `performance/`)
- `tests/fixtures/` — shared fixture modules (see `tests/fixtures/README.md`)
- `docs/` — architecture and design documentation
- `scripts/` — VFX tool scripts (tde4, sgtk, Nuke hooks)
- `scrub/` — hover-to-scrub frame preview system
- `shots/` — shot model, info panel, shot-level UI components
- `threede/` — 3DEqualizer scene model, discovery coordinator, filesystem scanner
- `bundle_workflow_template/` — portable encoded-bundle deployment workflow for reuse in other repos
- `wrapper/` — DCC launch wrapper scripts (e.g., ShotGrid Desktop pre-launch for 3DEqualizer)
- `cachetools/` — vendored `cachetools` library (not available in BlueBolt rez environment)
- `archive/` — historical materials, audits, and obsolete documentation (see `docs/README.md` Archive Boundaries)
- `dev-tools/` — development-only utility scripts (profiling, thread checks, type-check helpers)
- `encoded_releases/` — deployment artifact directory (encoded bundles for the encoded-releases branch)

**Import pattern:** Prefer normal imports. Use local imports only to break an existing cycle or defer an optional/heavy dependency. Put type-only imports under `TYPE_CHECKING`. **Caveat:** `from __future__ import annotations` makes all annotations strings at runtime, which can break PySide6 signal/slot type resolution and `get_type_hints()`. Test signal connections after adding this import to any module that defines signals.

## Development Commands

```bash
# Run with mock data (no VFX environment needed)
uv run python shotbot.py --mock

# Lint check (does not auto-fix; add --fix to apply fixes)
uv run ruff check <files>

# Type check — do not introduce new errors in touched files
uv run basedpyright <files>

# Primary test run (serial, main correctness gate)
uv run pytest tests/

# Secondary isolation check (parallel)
uv run pytest tests/ -n auto

# Dead code detection
uv run python scripts/generate_skylos_trace.py
uv run skylos . --table --exclude-folder tests --exclude-folder archive
```

**Pre-commit checks:** Run `ruff check` and `basedpyright` on changed files before committing.

**Post-commit hook:** `.git/hooks/post-commit` automatically runs ruff, basedpyright, deptry, then creates a deployment bundle and pushes it to the `encoded-releases` branch in the background. Do not duplicate these checks manually after committing.

## Deployment-Critical Files

These form the encoded-releases deployment pipeline. Do not delete or rename without explicit request and deployment validation:

- `deploy/bundle_app.py` — bundles application files for encoding
- `deploy/transfer_cli.py` — base64 encodes bundles (called by `bundle_app.py`)
- `transfer_config.json` — bundle inclusion/exclusion rules
- `.git/hooks/post-commit` — triggers bundle creation on commit
- `.git/hooks/push_bundle_background.sh` — pushes bundle to `encoded-releases` branch

## Non-Negotiable Rules

### Qt Patterns

1. Widget constructors must accept `parent: QWidget | None = None` and call `super().__init__(parent)`.
2. Broad `except Exception` for unexpected failures **must** call `logger.exception()` or `logger.error(..., exc_info=True)`. Expected recovery paths and noisy cleanup can use `logger.debug()` or `logger.warning()` without stack traces.
3. Use signals for cross-thread UI updates. For `ThreadSafeWorker` wiring, use `safe_connect(..., Qt.QueuedConnection)`. Never emit signals while holding a mutex. Never call widget methods directly from worker threads.

### Testing

4. Serial `uv run pytest tests/` is the default run — Qt resource contention and singleton state make parallel execution unreliable as a primary gate. Parallel (`-n auto`) is a secondary check for unintended test interdependencies.
5. New singletons should use `SingletonMixin` (from `singleton_mixin.py`) and be registered in `tests/fixtures/singleton_fixtures.py` with a `reset()` method. Exception: QObject-based singletons or classes with unusual MRO constraints may use a custom pattern — document the reason (see `ProcessPoolManager`).
6. Use `drain_qt_events()` (from `tests.test_helpers`) for Qt event flushing — not `time.sleep()` or small real-time waits.
7. Qt widgets added to `qtbot` must not also be manually `deleteLater()`'d in teardown. Close/hide them and let `qtbot` own destruction.
8. Integration tests cover real multi-component workflows: cross-component coordination, shutdown lifecycle, cache recovery, process-pool behavior, and launch flows. They exercise actual interaction, not just delegation checks. Unit tests cover isolated component behavior.
9. For log output assertions, use `caplog` instead of patching logger methods.
10. Use `mocker` (pytest-mock) for mocks and patching. Use `monkeypatch` for simple overrides (env vars, attribute swaps). Only import `unittest.mock` directly when `mocker` is unavailable (e.g., non-test code, standalone scripts).

## When to Consult Docs

- **Changing worker lifecycle, locking, or cross-thread routing** → read `docs/THREADING_ARCHITECTURE.md`, run `pytest tests/ -k "thread or concurrent or race or zombie"`
- **Changing signal connections in MainWindow or controllers** → read `docs/SIGNAL_ROUTING.md`, run its change checklist integration tests
- **Changing cache or persistence behavior** → read `docs/CACHING_ARCHITECTURE.md`
- **Changing launcher, DCC commands, or environment assumptions** → read `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`
- **Changing deployment pipeline** → read `docs/DEPLOYMENT_SYSTEM.md`
- **Investigating a crash or segfault** → follow `segfault.md` triage runbook
- **Removing dead code** → follow `docs/SKYLOS_DEAD_CODE_DETECTION.md` workflow
- **Adding or changing test fixtures** → check `tests/fixtures/README.md` catalog
- **Full docs index** → `docs/README.md`
