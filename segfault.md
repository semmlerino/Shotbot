# Segfault Triage Playbook (Condensed Version)

A shorter, no‑nonsense checklist for agents troubleshooting segfaults in pytest.

---

## 1. Reproduce the Crash (No Truncation)

Run:

```bash
cd /mnt/c/CustomScripts/Python/shotbot
PYTHONFAULTHANDLER=1 uv run pytest tests -x -vv 2>&1 | tee /tmp/segv.log
```

Record:

* Last test printed
* Tail of the log (40–60 lines)

If this *doesn’t* segfault, state it and note which command does.

---

## 2. Check Order Sensitivity

Run:

```bash
PYTHONFAULTHANDLER=1 uv run pytest tests -x -vv --randomly-seed=789 2>&1 | tee /tmp/segv-rand.log
```

Answer clearly:

* Does it still crash?
* If yes: which test was last?

If randomization changes behavior → likely **state contamination**.

---

## 3. Manually Bisect the Failing Set (Don’t Guess)

Run:

```bash
# Example: split candidate files in half and rerun each half
PYTHONFAULTHANDLER=1 uv run pytest tests/unit -x -vv 2>&1 | tee /tmp/bisect-unit.log
PYTHONFAULTHANDLER=1 uv run pytest tests/integration -x -vv 2>&1 | tee /tmp/bisect-integration.log
```

Report:

* Which half still crashes
* Which half stops crashing
* The minimal interaction you isolated after repeating that split

Repeat the split on the crashing half until the interaction is isolated. If that still
doesn’t isolate it, state that and move on.

---

## 4. Check With Worker Isolation

Run:

```bash
PYTHONFAULTHANDLER=1 uv run pytest tests -x -vv -n 1 --dist=loadgroup 2>&1 | tee /tmp/worker.log
```

Interpret:

* **No crash** → strong evidence of ordering or shared-state contamination in the default serial path
* **Crash still happens** → bug is likely local to one test/group, not just full-suite accumulation

---

## 5. Narrow Down by Groups

Run separately:

```bash
uv run pytest tests/unit -x -vv
uv run pytest tests/integration -x -vv
```

If each passes alone but full suite crashes → interaction issue.

Then binary-search subsets until you find:

> Running A before B → segfault

---

## 6. Qt / PySide Crash Checklist

Check for:

* Multiple `QApplication` instances (should be *one* session fixture)
* QThreads not stopped/joined
* QObjects created in one thread, destroyed in another
* Global Qt state created at import time

If found → propose concrete fixture/teardown fixes.

---

## 7. Enable More Diagnostics (If Needed)

Use:

```bash
export PYTHONMALLOC=debug
export QT_FATAL_WARNINGS=1
```

Re-run the minimal failing case.

If needed:

```bash
gdb --args .venv/bin/python -m pytest <minimal tests> -x -vv
run
bt
```

---

## 8. How to Report Findings

Each report must include:

1. **Minimal reproducer command**
2. **Observed last test + log tail**
3. **Conclusion with evidence** (order-sensitive? Qt misuse? leftover threads?)
4. **Concrete fixes** (fixture adjustments, teardown additions, removing globals)

No vague statements like “accumulated state” unless you show *which* tests cause it.

---

This condensed version is the default flow your troubleshooting agent should follow. It cuts noise while keeping all high-impact steps that reliably isolate segfault sources.
