# Integration Tests

29 integration test files covering async workflows, cache correctness, Qt lifecycle,
subprocess behavior, 3DE scene discovery, and main window coordination.

## Quick Start

```bash
# Run all integration tests
~/.local/bin/uv run pytest tests/integration/ -v

# Run with parallelism
~/.local/bin/uv run pytest tests/integration/ -n auto --dist=loadgroup
```

See `tests/RUN_INTEGRATION_TESTS.md` for the full test file inventory and category filters.
