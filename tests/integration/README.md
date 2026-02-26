# Integration Tests

13 integration test files covering:
- async and cross-component workflows
- cache correctness and recovery
- subprocess/process-pool real behavior
- 3DE discovery and launch flows
- main window coordination and shutdown lifecycle

## Quick Start

```bash
# Run all integration tests
~/.local/bin/uv run pytest tests/integration/ -v

# Run in parallel with Qt-safe grouping
~/.local/bin/uv run pytest tests/integration/ -n auto --dist=loadgroup
```
