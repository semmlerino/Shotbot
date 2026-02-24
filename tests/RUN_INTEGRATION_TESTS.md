# Integration Test Guide

## Quick Start

```bash
# Run all integration tests
~/.local/bin/uv run pytest tests/integration/ -v

# Run with parallelism (recommended for full suite)
~/.local/bin/uv run pytest tests/integration/ -n auto --dist=loadgroup

# Run a specific test file
~/.local/bin/uv run pytest tests/integration/test_real_subprocess.py -v
```

## Available Integration Tests

| File | Focus |
|------|-------|
| `test_real_subprocess.py` | Real subprocess execution, launcher stack smoke tests |
| `test_real_process_pool_manager.py` | ProcessPoolManager with real bash execution |
| `test_subprocess_smoke.py` | Basic subprocess operations validation |
| `test_shot_model_refresh.py` | Shot refresh workflow with test doubles |
| `test_shot_workflow_integration.py` | End-to-end shot workflow scenarios |
| `test_threede_scanner_integration.py` | 3DE scene discovery pipeline |
| `test_threede_launch_integration.py` | 3DE launch command building |
| `test_threede_discovery_full.py` | Full 3DE discovery with filesystem |
| `test_threede_parallel_discovery.py` | Concurrent 3DE scene discovery |
| `test_threede_worker_workflow.py` | 3DE worker thread coordination |
| `test_cache_corruption_recovery.py` | Cache resilience and recovery |
| `test_cache_merge_correctness.py` | Incremental cache merge logic |
| `test_incremental_caching_workflow.py` | Cache TTL and refresh behavior |
| `test_main_window_coordination.py` | Main window lifecycle and signals |
| `test_main_window_complete.py` | Complete MainWindow integration |
| `test_cross_component_integration.py` | Cross-component signal workflows |
| `test_async_workflow_integration.py` | Async operation coordination |
| `test_qt_lifecycle.py` | Qt object lifecycle management |
| `test_e2e_real_components.py` | End-to-end with real components |
| `test_user_workflows.py` | User interaction workflows |
| `test_feature_flag_switching.py` | Feature flag toggle behavior |
| `test_thumbnail_discovery_integration.py` | Thumbnail discovery and caching |
| `test_cache_persistence.py` | Cache persistence across restarts |
| `test_feature_flag_simplified.py` | Feature flag simplified workflow |
| `test_process_pool_contract.py` | ProcessPoolManager contract verification |
| `test_real_command_patterns.py` | Real command pattern execution |
| `test_real_workspace_commands.py` | Real workspace command behavior |
| `test_shutdown_sequence.py` | Graceful shutdown sequence |
| `test_ws_parsing_real.py` | Real ws command output parsing |

## Test Markers

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.real_subprocess` | Uses real subprocess (not mocked) |
| `@pytest.mark.integration` | Integration test (slower, cross-component) |
| `@pytest.mark.qt` | Requires Qt event loop |
| `@pytest.mark.qt_heavy` | Qt test requiring serialization |
| `@pytest.mark.slow` | Longer-running test |

## Running by Category

```bash
# Real subprocess tests only (no mocking)
~/.local/bin/uv run pytest tests/integration/ -m real_subprocess -v

# 3DE-related tests
~/.local/bin/uv run pytest tests/integration/ -k threede -v

# Cache-related tests
~/.local/bin/uv run pytest tests/integration/ -k cache -v

# Main window tests
~/.local/bin/uv run pytest tests/integration/ -k main_window -v

# Skip slow tests
~/.local/bin/uv run pytest tests/integration/ -m "not slow" -v
```

## Troubleshooting

### Qt Crashes in WSL
Ensure offscreen mode is enabled:
```bash
QT_QPA_PLATFORM=offscreen ~/.local/bin/uv run pytest tests/integration/ -v
```

### Timeout Issues
Increase timeout for slower systems:
```bash
~/.local/bin/uv run pytest tests/integration/ --timeout=120 -v
```

### Parallel Test Failures
If parallel tests fail but serial passes, use `--dist=loadgroup`:
```bash
~/.local/bin/uv run pytest tests/integration/ -n 4 --dist=loadgroup -v
```

## Test Development

When adding new integration tests:
1. Place in `tests/integration/test_*.py`
2. Add appropriate markers (`@pytest.mark.integration`, `@pytest.mark.qt` if using Qt)
3. Use test doubles from `tests.fixtures.test_doubles` or `tests.test_doubles_library`
4. Follow patterns in existing tests for signal waiting and cleanup
