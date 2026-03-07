# Shotbot Documentation Index

This index separates active documentation from historical artifacts.

## Start Here

- `README.md` - User-facing project overview and quick start
- `CLAUDE.md` - Agent-facing development rules and constraints

## Active Documentation

- `UNIFIED_TESTING_V2.md` - Canonical testing guidance (Qt rules, isolation, parallel execution)
- `docs/SKYLOS_DEAD_CODE_DETECTION.md` - Canonical Skylos workflow and dead-code triage guidance
- `docs/DEPLOYMENT_SYSTEM.md` - Bundle/deployment workflow and operational recovery
- `bundle_workflow_template/README.md` - Portable copy of the encoded-bundle workflow for reuse in another repository
- `docs/CACHING_ARCHITECTURE.md` - Cache design decisions and invariants
- `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md` - Launcher behavior and BlueBolt shell environment
- `docs/THREADING_ARCHITECTURE.md` - Threading model and guardrails
- `docs/SIGNAL_ROUTING.md` - MainWindow signal-routing invariants and change checklist
- `segfault.md` - Crash triage runbook

## Module-Scoped Reference Docs

- `tests/fixtures/README.md` - Fixture catalog and usage notes
- `tests/integration/README.md` - Integration-suite scope and commands
- `dev-tools/README.md` - Development-only scripts

## Archive Boundaries

- `docs/archive/` and `archive/` are historical material (audits, plans, reports, prior analyses).
- Do not treat archived documents as current behavior unless explicitly revalidated.

## Maintenance Rule

When adding or editing docs:

1. Prefer one canonical file per topic.
2. Put commands in one place and link to it from elsewhere.
3. Document invariants and failure modes, not code-level implementation details that are trivially discoverable.
