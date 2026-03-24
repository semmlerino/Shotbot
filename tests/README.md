# Testing

Canonical test execution policy and common commands for this repository.

## Execution Policy

- `uv run pytest tests/` is the default local run and the primary CI correctness gate.
- `uv run pytest tests/ -n auto` is a secondary isolation check for shared-state, teardown, and worker-safety bugs.
- Parallel execution is retained for diagnostic value, not because it is materially faster in this codebase.
- Qt tests require xdist grouping with `--dist=loadgroup`. This is already set in `pyproject.toml`; if you override `--dist`, keep `loadgroup`.

## Common Commands

```bash
# Primary suite: serial/default
uv run pytest tests/

# Secondary isolation check: parallel with Qt-safe grouping from pyproject.toml
uv run pytest tests/ -n auto

# Integration suite only
uv run pytest tests/integration/ -v

# Integration isolation check
uv run pytest tests/integration/ -n auto --dist=loadgroup
```

## When To Use Which

- Use the serial run for normal development and before treating a change as correct.
- Use the parallel run when you need to stress shared-state cleanup, singleton resets, Qt teardown, or worker isolation.
- If a test only fails in parallel, treat that as a real isolation bug rather than a speed-only concern.
