# Skylos Dead Code Detection

Skylos is a Python static analyser that combines call-trace data with AST analysis to detect unused functions, imports, parameters, variables, and classes.

## Quick Start

```bash
# Step 1: generate trace data (run once, or after significant test changes)
uv run python scripts/generate_skylos_trace.py

# Optional: widen pytest's marker filter to trace more code paths
uv run python scripts/generate_skylos_trace.py --markexpr "legacy or not legacy"

# Step 2: analyse (auto-loads .skylos_trace)
uv run skylos . --table --exclude-folder tests --exclude-folder archive

# JSON output for scripting
uv run skylos . --exclude-folder tests --exclude-folder archive --json
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

### Discovery

```python
def discover_test_files(markexpr: str | None) -> list[Path]:
    # Runs: pytest --collect-only -q tests
    # Parses collected node IDs back to unique test-file paths
```

This is intentionally based on pytest's configured collection rules (`testpaths`, `python_files`, and any marker override), rather than a second hand-written discovery rule.

### Per-file tracing

Each test file is run in a subprocess via:

```python
from skylos.tracer import CallTracer

tracer = CallTracer(exclude_patterns=[
    "site-packages", "venv", ".venv", "pytest", "_pytest", "pluggy",
])
tracer.start()
try:
    ret = pytest.main(["-q", "--tb=no", "--no-header", *pytest_run_args(markexpr), "<test_file>"])
finally:
    tracer.stop()
    tracer.save("<partial_trace_path>")
```

- Default outer timeout: `300s` per test file.
- Override timeout: `--per-file-timeout <seconds>` (`0` disables the outer timeout).
- Optional marker override: `--markexpr "<expr>"` passes a custom `-m` expression to both collection and traced runs.
- Output per file: `.skylos_traces/<path_slug>.json` (derived from the relative test path, so same-named files in different folders do not collide).

### Merge

`merge_traces()` reads all partial JSON files and deduplicates by `(file, function, line)`, summing call counts. Final output: `.skylos_trace` (JSON, version 1 schema).

### Resume mode

```bash
uv run python scripts/generate_skylos_trace.py --resume
```

Skips test files whose partial trace already exists and is still valid. Stale partial traces for removed or renamed test files are pruned automatically.

### Failure handling

If any traced test file crashes, errors out before writing trace data, or hits the outer timeout, the script still merges whatever partial data exists but exits non-zero by default.

When that happens, the script also writes `.skylos_trace_failures.json` with one entry per non-clean file, including the exit code or signal, whether a partial trace was saved, and the tail of captured `stdout`/`stderr`. That file is the first place to look before re-running the whole suite blind.

Use `--allow-partial` only when you intentionally want to inspect a best-effort trace despite known gaps:

```bash
uv run python scripts/generate_skylos_trace.py --allow-partial
```

---

## File Layout

| Path | Description |
|------|-------------|
| `.skylos_trace` | Merged trace consumed by Skylos analyzer |
| `.skylos_traces/` | Partial per-file traces (intermediate) |
| `.skylos_trace_failures.json` | Failure manifest for crashed, timed out, or otherwise non-clean traced files |
| `scripts/generate_skylos_trace.py` | Custom trace generator |
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

For one-off exceptions, prefer an inline `# skylos: ignore` on the exact symbol line instead of a name-based whitelist. Inline suppression is narrower, avoids matching unrelated symbols with the same name, and travels with the code that needs the exception.

For intentionally unused parameters that must remain for API, protocol, Qt slot, or test-double compatibility, prefer an explicit no-op use in code such as `_ = param` (or `_ = a, b`) instead of a Skylos ignore. That keeps the signature intact without adding to the suppression count.

If you cannot annotate the source line directly, use a named whitelist entry only as a fallback and keep the scope as narrow as the tool allows.

Broad name patterns are convenient but risky. A name like `run` can match legitimate worker entry points and unrelated helpers in the same codebase. Prefer the narrowest rule that solves the actual false positive.

---

## Known False Positive Patterns

When Skylos can't resolve a call through indirection, it can report the callee as unused. The following patterns are common sources of false positives:

### 1. Stored-reference attribute calls

```python
# Skylos sees the attribute assignment but can't resolve the method call
self.manager = SomeManager()
self.manager.get_some_value()
```

This is common in controllers, managers, and UI composition layers.

### 2. Multi-hop stored references

Same pattern but two hops:

```python
self.window.some_model.some_method()
```

### 3. Module aliasing or deferred imports

```python
helpers = importlib.import_module("some_module")
helpers.SomeClass.method()
```

The same issue can also appear with ordinary import aliases if the analyzer loses the link between the alias and the original symbol.

### 4. Internal delegation and framework orchestration

Methods that are only reached through a coordinator, registry, dispatcher, or base-class template may look unused even though they are part of a valid execution path.

### 5. Annotation-only members

Protocol fields, enum members, `NamedTuple` fields, and similar symbols are often reported as dead even though they exist for typing or data-shape contracts rather than direct calls.

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

---

## Maintenance

| When | Action |
|------|--------|
| Test files change significantly | Re-run `generate_skylos_trace.py` (full) |
| Adding a few new tests | `generate_skylos_trace.py --resume` |
| You want higher accuracy from trace coverage | Re-run with a broader marker expression, for example `--markexpr "legacy or not legacy"` |
| After removing dead code | Re-run Skylos — transitively dead items surface |
| Whitelist grows unexpectedly | Audit: each entry needs a documented reason |
| Intentional unused-parameter findings recur | Prefer explicit no-op parameter uses in code before adding Skylos suppressions |

Timeouts and runtimes depend heavily on the project. If some files are consistently slow, raise the outer timeout with `--per-file-timeout`, or split especially heavy integration tests into smaller files.

Treat an incomplete trace run as a failed input, not a successful report. If the trace step exits non-zero, fix the timeout/crash first or rerun explicitly with `--allow-partial` so the reduced confidence is intentional.

---

## Adapting to Another Project

To use this workflow in another project:

1. **If `--trace` works natively**, skip `generate_skylos_trace.py` entirely and run:
   ```bash
   uv run skylos . --trace --table --exclude-folder tests --exclude-folder archive
   ```

2. **If global tracing is unstable** (crashes, hangs, or incomplete trace output), copy `scripts/generate_skylos_trace.py` and adjust:
   - The pytest collection target or arguments if your suite does not collect from `tests`
   - `CallTracer(exclude_patterns=[...])` — add your venv and framework internals
   - The default outer timeout if your slowest stable test files need more time
   - Any marker expressions you want to run as separate trace passes for broader coverage

3. **Configure `[tool.skylos]` in `pyproject.toml`** with whitelists for:
   - Framework callback patterns you have verified as false positives
   - Protocol/ABC methods that are reached indirectly
   - Methods only triggered by external events (webhooks, user input)

4. **Gitignore** `.skylos_trace` and `.skylos_traces/`.
   If you keep the failure manifest enabled, gitignore `.skylos_trace_failures.json` too.

5. **Keep the whitelist minimal.** Every name pattern is a blind spot. Prefer inline `# skylos: ignore` for exact exceptions; use name-based whitelists only when a code-local ignore is not practical.
