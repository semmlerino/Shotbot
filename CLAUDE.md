# CLAUDE.md

Agent-facing operational guide for this repository.

## Project Context

Shotbot is a PySide6 GUI for matchmove workflow execution at BlueBolt (`3DEqualizer -> Maya -> Nuke -> Publish`). Single-user tool in an isolated VFX environment.

**Security posture:** Do not prioritize generic security findings (`shell=True`, path traversal, command injection, etc.). Prioritize correctness, maintainability, performance, and Qt thread safety.

## Project Layout

**Flat structure** — all application modules live at the repository root (no `src/` package). Key directories:

- `cache/` — cache abstraction layer (shot, thumbnail, scene, latest-file)
- `controllers/` — business logic orchestrators for UI coordination
- `launch/` — DCC launcher implementations
- `commands/` — command builders for DCC execution
- `tests/` — test suite (`unit/`, `integration/`, `advanced/`, `regression/`)
- `tests/fixtures/` — shared fixture modules (see `tests/fixtures/README.md`)
- `docs/` — architecture and design documentation
- `scripts/` — VFX tool scripts (tde4, sgtk, Nuke hooks)

**Import pattern:** Lazy imports are used throughout to avoid circular dependencies. When adding new imports between modules, check for circular import risk — use `from __future__ import annotations` and `TYPE_CHECKING` guards as needed.

## Development Commands

```bash
# Run with mock data (no VFX environment needed)
uv run python shotbot.py --mock

# Lint (auto-fixes)
uv run ruff check <files>

# Type check — fix all errors before committing (pre-existing warnings OK)
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

## Deployment-Critical Files (DO NOT DELETE)

These form the encoded-releases deployment pipeline. Deleting any breaks automated deployment:

- `bundle_app.py` — bundles application files for encoding
- `transfer_cli.py` — base64 encodes bundles (called by `bundle_app.py`)
- `transfer_config.json` — bundle inclusion/exclusion rules
- `.git/hooks/post-commit` — triggers bundle creation on commit
- `.git/hooks/push_bundle_background.sh` — pushes bundle to `encoded-releases` branch

## Non-Negotiable Rules

### Qt Patterns

1. Widget constructors must accept `parent: QWidget | None = None` and call `super().__init__(parent)`.
2. `except Exception` that does not re-raise **must** call `logger.exception()` or `logger.error(..., exc_info=True)`. Silent swallowing hides production bugs.

### Testing

3. Serial `uv run pytest tests/` is the default run. Parallel (`-n auto`) is a secondary isolation check only.
4. New singletons must use `SingletonMixin` (from `singleton_mixin.py`) and be registered in `tests/fixtures/singleton_fixtures.py` with a `reset()` method.
5. Use `process_qt_events()` (from `tests.test_helpers`) for Qt event flushing — not `time.sleep()` or small real-time waits.
6. Qt widgets added to `qtbot` must not also be manually `deleteLater()`'d in teardown. Close/hide them and let `qtbot` own destruction.
7. Integration tests should assert on controller/orchestrator delegation — don't re-run deeper refresh or launch internals that already have dedicated unit coverage. Example: assert `controller.launch()` was called, don't re-test what `launch()` does internally.

## Canonical References

- Deployment and recovery: `docs/DEPLOYMENT_SYSTEM.md`
- Caching behavior: `docs/CACHING_ARCHITECTURE.md`
- Launcher and BlueBolt environment: `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`
- Threading model: `docs/THREADING_ARCHITECTURE.md`
- MainWindow signal invariants: `docs/SIGNAL_ROUTING.md`
- Dead-code workflow: `docs/SKYLOS_DEAD_CODE_DETECTION.md`
- Test fixture catalog: `tests/fixtures/README.md`
- Crash triage runbook: `segfault.md`
- Full docs index: `docs/README.md`
