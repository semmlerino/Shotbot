# Skylos Dead Code Detection

Skylos is a Python static analyser that combines call-trace data with AST analysis to detect unused functions, imports, parameters, variables, and classes.

## Quick Start

```bash
# Step 1: generate trace data (run once, or after significant test changes)
uv run python scripts/generate_skylos_trace.py

# Optional: trace only a targeted subset of tests
uv run python scripts/generate_skylos_trace.py --markexpr "gui_mainwindow or qt_heavy"

# Optional: merge multiple targeted marker passes into one trace
# Note: the default unfiltered pass already covers the full collected suite.
uv run python scripts/generate_skylos_trace.py \
  --include-default-pass \
  --markexpr "gui_mainwindow or qt_heavy" \
  --markexpr "integration_unsafe or persistent_cache"

# Step 2: analyse the repo's fast first-pass queue (auto-loads .skylos_trace)
uv run skylos . --table --exclude-folder tests --exclude-folder archive --confidence 80

# JSON output for scripting or verification
uv run skylos . --exclude-folder tests --exclude-folder archive --confidence 80 --json

# Optional: run a cheap text-reference pass before manual review/removal
uv run python scripts/verify_skylos_candidates.py /tmp/skylos_report_conf80.json

# Step 3: after the 80-confidence queue is exhausted, broaden to Skylos's
# default confidence tier for a larger manual review pass
uv run skylos . --table --exclude-folder tests --exclude-folder archive --confidence 60
```

---

## Why a Custom Trace Script?

Skylos ships a `--trace` flag that runs your test suite with `sys.setprofile()` active and saves the call data at exit. That is the simplest option when it is stable.

For GUI-heavy or C-extension-heavy projects, global profiling can be fragile in practice: a test process may crash, hang, or exit before the trace is written. The exact failure mode is environment-specific, so do not assume a single framework call or library boundary is the root cause unless you have a reproducible case.

`scripts/generate_skylos_trace.py` is a more defensive alternative:

1. Uses **pytest's own collection** so the traced file list matches the real configured suite.
2. Runs **each test file in its own subprocess** with `CallTracer` active.
3. Each subprocess saves a **partial trace file** immediately in its `finally` block.
4. If a subprocess crashes or times out, only **that file's data is lost**; all other completed files are already saved.
5. The main process **merges all partial traces** into `.skylos_trace`.
6. The script exits non-zero by default if any file times out or crashes, so incomplete traces do not look "successful" by accident.

---

## How `generate_skylos_trace.py` Works

The script runs in three stages:

1. **Discovery** — uses `pytest --collect-only` to find test files, matching the real configured suite.
2. **Per-file tracing** — runs each test file in its own subprocess with `CallTracer` active. Default timeout: 300s per file (`--per-file-timeout` to override). Each subprocess saves a partial trace immediately in its `finally` block, so crashes only lose that file's data.
3. **Merge** — deduplicates all partial traces by `(file, function, line)` into `.skylos_trace`.

Key flags: `--resume` (skip already-traced files), `--allow-partial` (accept incomplete traces), `--markexpr "<expr>"` (filter by marker, repeatable), `--include-default-pass` (include unfiltered pass alongside marker passes).

On failure, the script writes `.skylos_trace_failures.json` with exit codes, partial trace status, and captured output per failed file. It retries once on pytest internal errors (`exit 3`). Exits non-zero by default if any file fails.

---

## File Layout

| Path | Description |
|------|-------------|
| `.skylos_trace` | Merged trace consumed by Skylos analyzer |
| `.skylos_traces/` | Partial per-file traces (intermediate) |
| `.skylos_trace_failures.json` | Failure manifest for crashed, timed out, or otherwise non-clean traced files |
| `scripts/generate_skylos_trace.py` | Custom trace generator |
| `scripts/verify_skylos_candidates.py` | Cheap textual verification helper for Skylos hits |
| `pyproject.toml` `[tool.skylos]` | Whitelist configuration |

`.skylos_trace`, `.skylos_traces/`, and `.skylos_trace_failures.json` should be **gitignored** — they are build artefacts.

---

## Configuration Pattern (`pyproject.toml`)

```toml
[tool.skylos]
# Use a trace-first workflow when Skylos's built-in --trace is unreliable.
# Generate .skylos_trace with a custom script, then run Skylos normally.

[tool.skylos.whitelist]
names = [
    # Broad callback patterns only when you have confirmed stable false positives.
    "on_*",          # framework callbacks
    "_on_*",         # private callback naming convention
    "contextMenuEvent",
]

# Prefer exact-line suppressions for one-off exceptions:
# def some_indirect_symbol(...):  # skylos: ignore
# some_protocol_field: SomeType  # skylos: ignore
```

> **Note:** This example is abridged. See `pyproject.toml` `[tool.skylos.whitelist]` for the full whitelist.

### Whitelist rationale

Use whitelists for patterns you have already reviewed and found to be consistent false positives. Common candidates are:

| Pattern | Reason |
|---------|--------|
| `on_*`, `_on_*` | Framework or UI callbacks reached indirectly by event wiring |
| Lifecycle methods such as `run` | Worker entry points often invoked indirectly and may need manual review |
| UI event handlers such as `contextMenuEvent` | Only exercised when tests simulate the relevant interaction |
| Template or abstract methods | Called through base-class orchestration rather than directly |
| Annotation-only symbols | Protocol, `NamedTuple`, enum, or structural-typing members are often not "dead code" in the normal sense |

Prefer inline `# skylos: ignore` for one-off exceptions. For unused parameters kept for API/protocol compatibility, prefer `_ = param` over suppression. Use name-based whitelist entries only as a fallback when code-local annotation is impractical.

---

## Known False Positive Patterns

Skylos reports false positives when it cannot resolve calls through indirection:

- **Stored-reference attribute calls** — `self.manager.method()` where the analyzer loses the link through attribute assignment
- **Multi-hop stored references** — `self.window.model.method()`
- **Module aliasing or deferred imports** — `importlib.import_module()` or import aliases
- **Internal delegation** — methods reached through coordinators, registries, or base-class templates
- **Annotation-only members** — Protocol fields, enum members, `NamedTuple` fields used for typing contracts

---

## Triage Strategy

Focus effort on **high-signal locations** where false positives are less common:

- Standalone utility modules
- Pure functions and explicit public APIs
- Modules with minimal framework wiring or object indirection

**Low-signal / high-FP locations** (review last):

- Manager/controller classes
- Heavily callback-driven UI layers
- Objects commonly stored on `self` and used through one or more attribute hops

Start with `--confidence 80` (or higher) for the first cleanup pass. Lower-confidence findings are still useful, but they are much more likely to include indirect-call false positives and should be reviewed after the obvious removals are gone.

For this repo, treat `--confidence 80` as a **noise-reduction shortcut**, not as a universal Skylos best practice. Skylos's default confidence is `60`, and that broader tier should be the follow-up pass once the high-signal queue is gone.

Before deleting code, run the report through `scripts/verify_skylos_candidates.py` to catch obvious textual references that Skylos may have missed. That script is only a quick filter, not proof of liveness, but it helps reduce avoidable false positives before manual inspection.

---

## Maintenance

| When | Action |
|------|--------|
| Test files change significantly | Re-run `generate_skylos_trace.py` (full) |
| Adding a few new tests | `generate_skylos_trace.py --resume` |
| You want to focus trace generation on specific test categories | Run with `--markexpr "<expr>"`, or merge multiple targeted passes with repeated `--markexpr` (optionally with `--include-default-pass`) |
| You finished reviewing the `--confidence 80` queue | Re-run Skylos at `--confidence 60` for the next broader review tier |
| After removing dead code | Re-run Skylos — transitively dead items surface |
| Whitelist grows unexpectedly | Audit: each entry needs a documented reason |
| Intentional unused-parameter findings recur | Prefer explicit no-op parameter uses in code before adding Skylos suppressions |

Timeouts and runtimes depend heavily on the project. If some files are consistently slow, raise the outer timeout with `--per-file-timeout`, or split especially heavy integration tests into smaller files.

Treat an incomplete trace run as a failed input, not a successful report. If the trace step exits non-zero, fix the timeout/crash first or rerun explicitly with `--allow-partial` so the reduced confidence is intentional.

