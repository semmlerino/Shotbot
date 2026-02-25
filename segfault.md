# Segfault Triage Playbook (Condensed Version)

A shorter, no‑nonsense checklist for agents troubleshooting segfaults in pytest.

---

## 1. Reproduce the Crash (No Truncation)

Run:

```bash
cd ~/projects/shotbot
PYTHONFAULTHANDLER=1 pytest -x -vv 2>&1 | tee /tmp/segv.log
```

Record:

* Last test printed
* Tail of the log (40–60 lines)

If this *doesn’t* segfault, state it and note which command does.

---

## 2. Check Order Sensitivity

Run:

```bash
PYTHONFAULTHANDLER=1 pytest -x -vv -p randomly --randomly-seed=789 2>&1 | tee /tmp/segv-rand.log
```

Answer clearly:

* Does it still crash?
* If yes: which test was last?

If randomization changes behavior → likely **state contamination**.

---

## 3. Use `pytest --bisect` (Don’t Guess)

Run:

```bash
PYTHONFAULTHANDLER=1 pytest --bisect -p randomly --randomly-seed=789 2>&1 | tee /tmp/bisect.log
```

Report:

* Good test/set
* Bad test/set
* The minimal interaction that causes the crash

If bisect can’t isolate: state it and move on.

---

## 4. Check With Process Isolation

Run:

```bash
PYTHONFAULTHANDLER=1 pytest tests -x --forked 2>&1 | tee /tmp/forked.log
```

Interpret:

* **No crash** → strong evidence of cross-test contamination
* **Crash still happens** → bug is local to one test/group

---

## 5. Narrow Down by Groups

Run separately:

```bash
pytest tests/unit -x\pytest tests/integration -x
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
gdb --args python -m pytest <minimal tests> -x -vv
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
