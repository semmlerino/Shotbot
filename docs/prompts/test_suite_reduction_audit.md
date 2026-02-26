# Test Suite Reduction Audit

Perform a reduction-focused audit of the current testing setup, test suite, and related documentation.

The primary objective is to **shrink the test surface area** of a codebase that has grown significantly in size and complexity — without sacrificing meaningful behavioral guarantees.

## Workflow: Verify First, Then Plan

This audit has two distinct phases. Do not skip to planning.

### Phase 1: Discovery and Verification

Identify reduction candidates across two categories (see sections below). For each candidate, **run verification before including it in findings.** Claims about code — what exists, what's unused, what delegates to what — must be backed by evidence you gathered during this phase, not deferred to execution.

### Phase 2: Execution Plan

Only verified findings enter the execution plan. Unverified candidates go in a separate appendix (see "Execution Plan Requirements").

---

## Category A: Dead Code (Fixtures, Helpers, Infrastructure)

Identify fixtures, helper classes, test doubles, and infrastructure code with zero callers.

### Verification Standard

Every "zero callers" or "unused" claim must include the verification method used and its output. Simple single-line grep is **insufficient**. You must use at least one of:

1. `pytest --collect-only` after trial deletion — catches fixture resolution failures immediately
2. AST-based import analysis (`import ast; ...`) — handles multiline imports correctly
3. `rg --multiline` or `grep -Pzo` — multiline-aware text search
4. For fixtures specifically: search for the fixture name as a **function parameter** across all test files, combined with `pytest --fixtures` output

### Common False Positive Patterns

These patterns have caused incorrect "dead code" claims in past audits. Check for each before claiming something is unused.

| Pattern | Why simple grep misses it | How to verify correctly |
|---------|--------------------------|----------------------|
| Multiline `from x import (\n    Foo,\n    Bar\n)` | Line grep for `Foo` doesn't match across the `(` | `rg --multiline 'from\s+\w+.*import\s*\([^)]*Foo'` |
| Pytest fixture injection | Fixtures are resolved by parameter name, never imported | Search for the name as a function parameter: `rg 'def test_\w+\(.*fixture_name'` |
| Re-export shim modules | Grep finds zero imports of the *source* module, misses the shim that re-exports it | Trace the full chain: source → shim → consumers |
| `conftest.py` autouse fixtures | Never explicitly referenced anywhere | Check `autouse=True` and `conftest.py` scope — these are active even with zero callers |
| Fixtures used only by other fixtures | No test calls the fixture directly, but another fixture depends on it | `pytest --fixtures -v` shows the dependency chain |

### Evidence Requirements

For each dead code finding, include:
- **File and symbol**: exact path and name
- **Verification method**: which tool/command you ran
- **Verification output**: the actual result (e.g., "0 matches" from multiline grep, or "collection succeeded" from pytest)

---

## Category B: Redundant and Low-Value Tests

Identify tests that can be removed, merged, or parameterized without losing behavioral coverage.

### Evaluation Criteria

- Redundancy and duplication (same behavior tested from slightly different angles)
- Tests that validate **implementation details** (mock call assertions, private method routing) instead of externally observable behavior
- Subclass tests that re-verify base class behavior already tested elsewhere
- Contract test overlap (individual finder tests duplicating parameterized contract tests)
- Tests that can be collapsed via `@pytest.mark.parametrize`
- Overly defensive micro-tests for trivially correct code
- Misalignment between test volume and actual risk

### Evidence Requirements

For each redundant test finding, include:
- **Which tests overlap**: exact test names and file:line references
- **What behavioral guarantee they share**: the specific behavior both tests verify
- **What remains after reduction**: which test(s) still cover the behavior
- **What's lost**: any edge case or scenario that loses coverage (even if acceptable)

### Read Before Claiming

Every claim about what code does — "delegates to X," "has N callers," "tests the same behavior as Y" — must cite the file:line where you verified it. Do not infer code structure from names or patterns alone.

---

## Output Structure

1. Group findings by module or feature area
2. Separate Category A (dead code) from Category B (redundant tests)
3. Prioritize by impact (High / Medium / Low)
4. For each finding include:
   - Issue description
   - Why it matters (maintenance cost, noise, etc.)
   - Verification evidence (method + output)
   - Recommended reduction strategy
   - Risk/tradeoff
   - Expected test count or line reduction (estimate)
   - What minimal guardrails must remain

## Risk Classification

Do not label anything "verified zero risk" unless confirmed by AST analysis, multiline grep, or test collection. Use this scale:

| Label | Meaning |
|-------|---------|
| **Verified zero risk** | AST-confirmed or `pytest --collect-only` confirmed — no callers in any import path or fixture resolution |
| **Low risk (grep-verified)** | Multiline-aware grep found no matches, but implicit callers (fixture injection, dynamic imports) not yet ruled out |
| **Low risk** | Behavioral tests cover the same ground; removal unlikely to create blind spots |
| **Low-moderate risk** | Cosmetic or notification behavior loses coverage; functional behavior still covered |

**Note:** "Low risk (grep-verified)" requires multiline grep (`rg --multiline` or equivalent), not single-line grep. Single-line-only grep findings are **unverified** and must go in the appendix.

## Execution Plan Requirements

End with a concrete **test suite slimming plan** organized into phases:

- Immediate deletions (verified zero risk)
- Safe consolidations (low risk)
- Structural refactors (low-moderate risk)
- Longer-term simplifications

### What enters the plan

Only findings with verified evidence enter the main execution plan. Unverified or partially verified findings go in a **"Candidates Requiring Verification" appendix** with the specific verification command to run before acting on them.

### Phase requirements

Each phase must:

1. **Include an immediate smoke check** after each group of deletions (`pytest --collect-only` or `pytest -x --tb=line`)
2. **Group deletions so each group can be independently verified and rolled back** — don't mix unrelated deletions in one step
3. **Specify file ownership per agent** if the plan will be executed by parallel agents — no file should be assigned to multiple agents

### Appendix: Candidates Requiring Verification

For each unverified candidate, specify:
- The finding and why it's tentative
- The exact verification command to run
- The expected output if the finding is correct
- What to do if verification fails (skip, or investigate further)

---

Be direct and pragmatic. Favor lean, high-signal tests that protect real behavior over exhaustive but noisy coverage.
