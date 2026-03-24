# Shotbot: Development Setup Recommendations

Findings from a review of the development toolchain, workflow, and configuration. Ordered by impact.

## High Impact

### 1. Add pre-commit hooks

Currently all checks (ruff, basedpyright, deptry) run in the post-commit hook, which always exits 0. Broken code gets committed and you only notice if you check `.post-commit-output/`.

**Fix:** Create `.pre-commit-config.yaml` — adapt CurveEditor's config. Move lint/type checks there. Keep only deployment bundling in the post-commit hook.

**Effort:** Quick win.

### 2. Post-commit hook: use `uv run` instead of bare tool calls

Lines 27-50 of `.git/hooks/post-commit` call `ruff`, `basedpyright`, `deptry` directly. On WSL with uv-managed tools, these may not be on PATH (they live in `.venv/bin/`). The hook silently skips checks when it can't find them.

**Fix:** Replace `ruff check .` with `uv run ruff check .`, `basedpyright` with `uv run basedpyright`, `deptry .` with `uv run deptry .`.

**Effort:** Quick win — 4 line changes.

### 3. Expand `run_tests.sh` into a lane-based test runner

`run_tests.sh` exists, but it is currently only a thin wrapper around
`uv run pytest tests/ "$@"`. Running common subsets still requires
remembering raw pytest commands or looking them up in `CLAUDE.md`.

**Fix:** Expand `run_tests.sh` with lanes: `unit` (default, serial),
`parallel` (`-n auto`), `smoke`, `integration`, `regression`,
`performance`. Include Qt environment setup (`QT_QPA_PLATFORM=offscreen`,
`QT_LOGGING_RULES`).

**Effort:** Quick win — expand the existing script rather than adding a new one.

### 4. Include tests in type checking with relaxed rules

Tests are fully excluded from basedpyright (`exclude = ["tests/**"]`). Type errors in test helpers, fixtures, and assertions go undetected.

**Fix:** Remove `tests/**` from exclude. Add an `executionEnvironments` entry with relaxed rules (match CurveEditor's approach):
```toml
executionEnvironments = [
    {root = "tests", reportUnknownMemberType = "none", reportUnknownParameterType = "none", ...}
]
```

**Effort:** Medium — config change is quick, expect some initial fixes needed across 127 test files.

## Medium Impact

### 5. Standardize line length to 120

Currently 88 (Black default). CurveEditor uses 120. Qt code at 88 produces excessive wrapping — Qt method names and signal connections are verbose. Context-switching between projects breaks reading patterns.

**Fix:** Change `line-length = 120` in pyproject.toml, run `uv run ruff format .`.

**Effort:** Quick win (one command, one commit).

### 6. Lower or remove mccabe max-complexity threshold

`max-complexity = 30` is effectively disabled (default is 10). A function needs to be nearly incomprehensible to trigger it. Creates false confidence that complexity is being monitored.

**Fix:** Lower to 15-20 (still generous, catches genuine messes) or remove the C90 rule entirely.

**Effort:** Quick win.

### 7. Audit `requirements.txt` for drift

`requirements.txt` exists alongside `pyproject.toml` + `uv.lock`. If anything reads `requirements.txt` instead of using `uv sync`, dependency versions can diverge.

**Fix:** If a non-uv consumer needs it, auto-generate it: `uv pip compile pyproject.toml -o requirements.txt`. If nothing reads it, delete it.

**Effort:** Quick win.

### 8. Restrict `T201` (print) to specific files instead of global ignore

Stray print statements in a GUI app are noise in the terminal and invisible to users. Currently globally ignored, which means leftover debug prints also pass.

**Fix:** Remove global `T201` ignore. Add per-file-ignores for files that legitimately print:
```toml
"shotbot.py" = ["T201"]
"deploy/**" = ["T201"]
"dev-tools/**" = ["T201"]
```

**Effort:** Quick win.
