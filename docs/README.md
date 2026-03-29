# Shotbot Documentation Index

This index separates active documentation from historical artifacts and
covers current root-level reference docs as well as `docs/`.

## Start Here

- `README.md` - User-facing project overview and quick start
- `CLAUDE.md` - Agent-facing development rules and constraints

## Project-Root References

- `RECOMMENDATIONS.md` - Current development workflow and tooling recommendations
- `BLUEBOLT_REZ_PACKAGES.md` - Curated BlueBolt Rez inventory notes and key package findings
- `BLUEBOLT_REZ_PACKAGES_FULL.md` - Full BlueBolt Rez package snapshot captured for this project
- `segfault.md` - Crash triage runbook

## Active Documentation

- `docs/SKYLOS_DEAD_CODE_DETECTION.md` - Canonical Skylos workflow and dead-code triage guidance
- `docs/DEPLOYMENT_SYSTEM.md` - Bundle/deployment workflow, remote log locations, DCC wrapper triage, and in-DCC Toolkit/workfiles context inspection
- `bundle_workflow_template/README.md` - Portable copy of the encoded-bundle workflow for reuse in another repository
- `docs/CACHING_ARCHITECTURE.md` - Cache design decisions and invariants
- `docs/LAUNCHER_AND_VFX_ENVIRONMENT.md` - Launcher behavior, BlueBolt shell environment, wrapper-vs-Rez diagnostics, and delayed-context Toolkit/workfiles debugging
- `docs/THREADING_ARCHITECTURE.md` - Threading model and guardrails
- `docs/SIGNAL_ROUTING.md` - MainWindow signal-routing invariants and change checklist

## Module-Scoped Reference Docs

- `tests/README.md` - Canonical testing policy and common commands
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
