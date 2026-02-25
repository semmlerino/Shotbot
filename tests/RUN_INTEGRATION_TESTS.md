# Integration Test Guide

## Quick Start

```bash
# Run all integration tests
~/.local/bin/uv run pytest tests/integration/ -v

# Run in parallel (Qt-safe)
~/.local/bin/uv run pytest tests/integration/ -n auto --dist=loadgroup

# Run via utility wrapper
~/.local/bin/uv run python tests/utilities/run_all_integration_tests.py
```

## Current Integration Files (22)

| File | Focus |
|------|-------|
| `test_async_workflow_integration.py` | Async callback and workflow coordination |
| `test_cache_corruption_recovery.py` | Corrupt cache recovery behavior |
| `test_cache_merge_correctness.py` | Incremental merge correctness |
| `test_cache_persistence.py` | Cache load/persist compatibility checks |
| `test_cross_component_integration.py` | Cross-tab and cross-component coordination |
| `test_e2e_real_components.py` | End-to-end behavior with real components |
| `test_incremental_caching_workflow.py` | Multi-step caching workflow |
| `test_main_window_coordination.py` | MainWindow lifecycle and UI coordination |
| `test_process_pool_contract.py` | ProcessPoolManager thread/signal contracts |
| `test_qt_lifecycle.py` | Qt object/thread lifecycle contracts |
| `test_real_process_pool_manager.py` | Real process pool execution and cache behavior |
| `test_real_subprocess.py` | Real subprocess and launcher stack smoke behavior |
| `test_shot_model_refresh.py` | Shot refresh and change detection workflow |
| `test_shutdown_sequence.py` | Graceful shutdown behavior |
| `test_threede_discovery_full.py` | End-to-end 3DE discovery |
| `test_threede_launch_integration.py` | 3DE launch command integration |
| `test_threede_parallel_discovery.py` | Parallel 3DE discovery |
| `test_threede_scanner_integration.py` | Scanner/cache integration for 3DE discovery |
| `test_threede_worker_workflow.py` | 3DE worker lifecycle/workflow |
| `test_thumbnail_discovery_integration.py` | Thumbnail discovery and fallback behavior |
| `test_user_workflows.py` | High-level user launch/selection workflows |
| `test_ws_parsing_real.py` | Real ws output parsing behavior |

## Useful Filters

```bash
# Real subprocess paths only
~/.local/bin/uv run pytest tests/integration/ -m real_subprocess -v

# 3DE-focused integration tests
~/.local/bin/uv run pytest tests/integration/ -k threede -v

# Cache-focused integration tests
~/.local/bin/uv run pytest tests/integration/ -k cache -v
```

## Notes

- Integration tests are marked with `@pytest.mark.integration`.
- Qt-using tests should run with `--dist=loadgroup` in parallel mode.
- Default global marker policy is defined in `pyproject.toml`.
