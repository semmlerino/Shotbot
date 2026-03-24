# Integration Tests

Integration test coverage includes:
- async and cross-component workflows
- cache correctness and recovery
- subprocess/process-pool real behavior
- 3DE discovery and launch flows
- main window coordination and shutdown lifecycle

For the canonical test execution policy, see `tests/README.md`.

## Quick Start

```bash
# Run all integration tests
uv run pytest tests/integration/ -v

# Optional isolation check: run in parallel with Qt-safe grouping
uv run pytest tests/integration/ -n auto --dist=loadgroup
```
