# CLAUDE.md

This file is the agent-facing operational guide for this repository.

## Project Overview

Shotbot is a PySide6 GUI for matchmove workflow execution at BlueBolt:

`3DEqualizer -> Maya -> Nuke -> Publish`

Core behavior:

- Browse shots from workspace context (`ws -sg`)
- Launch DCC applications with shot context
- Support "Other 3DE scenes" collaboration and Previous Shots recovery

## Security Posture

This is a single-user tool in an isolated VFX environment.
Do not prioritize generic security findings (`shell=True`, path traversal, command injection hardening, etc.).
Prioritize correctness, maintainability, performance, and Qt thread safety.

## Development Environment

- Preferred dev location: `/mnt/c/CustomScripts/Python/shotbot`
- Production target: `/nethome/gabriel-h/Python/Shotbot/`
- Deployment path: encoded bundle flow on `encoded-releases` branch
- Dependencies and toolchain are defined in `pyproject.toml`

## Development Commands

See `README.md` for development commands.

## Non-Negotiable Rules

1. Qt widget constructors must accept `parent: QWidget | None = None` and call `super().__init__(parent)`.
2. Use `--dist=loadgroup` for whole-suite parallel test runs.
3. New singletons should use `SingletonMixin` and be registered in `tests/fixtures/singleton_registry.py`.
4. Use `process_qt_events()` for Qt event flushing in tests (not tiny real-time waits).
5. `except Exception` that does not re-raise **must** call `logger.exception()` or `logger.error(..., exc_info=True)`. Silent swallowing hides production bugs.

## Canonical References

- Testing policy: `UNIFIED_TESTING_V2.md`
- Deployment and recovery: `docs/DEPLOYMENT_SYSTEM.md`
- Caching behavior: `docs/CACHING_ARCHITECTURE.md`
- Launcher and BlueBolt environment: `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md`
- Threading model: `docs/THREADING_ARCHITECTURE.md`
- MainWindow signal invariants: `docs/SIGNAL_ROUTING.md`
- Full docs index: `docs/README.md`
