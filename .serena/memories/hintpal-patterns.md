# Shotbot Codebase Patterns

## Project: shotbot
- PySide6 VFX pipeline tool for single Matchmove artist at BlueBolt
- Tooling: ruff, basedpyright (strict, 0 errors), pytest with parallel support
- Style: PEP 8 naming, type hints, `from __future__ import annotations`, dataclasses
- Pattern: lazy imports (double-check locking) to break circular dependencies between modules
- Pattern: `ClassVar` for class-level state shared across instances
- Pattern: LoggingMixin base class for all scanner/finder classes
- Testing: 3500+ tests, `--dist=loadgroup` for parallel Qt safety
- Key files: filesystem_scanner.py (scan strategies), thumbnail_finders.py (thumbnail search)

## filesystem_scanner.py patterns
- Three scan strategies: find_3de_files_python_optimized, find_3de_files_subprocess_optimized, find_3de_files_progressive
  - Progressive is the actual entrypoint; python/subprocess are delegated strategies
  - MEDIUM_WORKLOAD_THRESHOLD and CONCURRENT_THRESHOLD are dead constants (never referenced in logic)
- _run_subprocess_with_streaming_read: low-level pipe-reading primitive (cancellable, streaming)
- _run_find_with_polling: higher-level; calls streaming_read + parses results into tuples
  - Despite "polling" in name, actual polling is done by streaming_read, not this method
- find_all_3de_files_in_show_targeted: 248-line god function; decomposable into:
  1. parser lazy init
  2. _build_find_commands (user + publish/mm)
  3. _run_user_search
  4. _run_publish_mm_search (inline; could be helper)
  5. _merge_and_filter_results
  6. _log_completion_summary
- file_count and parsed_count in find_all_3de_files_in_show_targeted are always equal (both set to len(results)); parsed_count is redundant
- `import threading` appears at module level AND inside __init__ (redundant)
- `import traceback` inside find_all_3de_files_in_show_targeted (should be module-level)

## thumbnail_finders.py patterns
- find_shot_thumbnail: cascade fallback (editorial → turnover → any publish EXR)
  - Uses positive if/else nesting instead of early-return guard clauses → deep nesting
  - All branches end with the same trailing log + return None (duplicated)
- find_user_workspace_jpeg_thumbnail: 10-level nesting (worst in codebase)
  - Decomposable: extract _search_user_workspace(user_path) helper
  - Inner loop tries ["jpeg", ""] path variants; then iterates resolution dirs
- find_turnover_plate_thumbnail: two identical `return first_frame` after size check is redundant -- both branches return same thing
- Nested function extract_frame_number defined inside loop (should be module-level)
- plate_priority defined as nested function inside method (fine for small helpers)
