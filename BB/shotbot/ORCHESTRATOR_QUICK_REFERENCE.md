# Orchestrator Quick Reference

## Agent Capabilities Matrix

| Agent | Model | Primary Use | Can Parallel With |
|-------|-------|-------------|-------------------|
| python-code-reviewer | Sonnet | Code review | type-system-expert, performance-profiler |
| code-refactoring-expert | Opus | Refactoring | None (exclusive) |
| python-expert-architect | Sonnet | Complex patterns, async, frameworks | All analysis agents |
| python-implementation-specialist | Sonnet | Standard implementation | None (modifies code) |
| test-development-master | Sonnet | Testing + TDD + Coverage + Qt | type-system-expert |
| test-type-safety-specialist | Sonnet | Type-safe tests | test-development-master |
| type-system-expert | Sonnet | Types + protocols | All except refactoring |
| qt-ui-modernizer | Opus | UI/UX + QML + Implementation | qt-modelview-painter |
| ui-ux-validator | Sonnet | UI validation from user perspective | All analysis agents |
| qt-concurrency-architect | Opus | Qt threading | qt-modelview-painter |
| qt-modelview-painter | Opus | Model/View + Implementation | qt-concurrency-architect |
| performance-profiler | Sonnet | Performance | All analysis agents |
| deep-debugger | Opus | Complex bugs | performance-profiler, threading-debugger |
| threading-debugger | Opus | Threading bugs, deadlocks, races | deep-debugger, performance-profiler |
| venv-keeper | Sonnet | Environment | None (exclusive) |
| api-documentation-specialist | Sonnet | API design + docs | All analysis agents |

## ⚠️ CRITICAL: Parallel Execution Rules

**Agents can ONLY run in parallel if:**
1. They work on **different files** (non-overlapping scopes)
2. They perform **read-only analysis** (no modifications)
3. They create **different new files** (no naming conflicts)

**"Can Parallel With" in the matrix means:**
- ✅ CAN run together IF given separate file scopes
- ❌ CANNOT both modify the same file
- ⚠️ Always verify scope separation before parallel deployment

## Common Workflows

### 🚀 New Feature
```
architect → implementation-specialist → (review + type-check) → test
```

### 🐛 Debug Issue
```
(deep-debugger + threading-debugger[if concurrent] + profiler) → review → implementation-specialist → test
```

### ♻️ Refactor Code
```
review → refactor → (type-check + test)
```

### 🎨 Qt Development
```
(ui-modernizer + modelview-painter) [both implement] → ui-validation → concurrency-check → test
```

### ⚡ Optimize Performance
```
profiler → architect [can implement] → refactor → (profiler + test)
```

## Parallel Execution Groups

### Analysis Team (Safe for Parallel - Read-Only)
- python-code-reviewer
- type-system-expert
- performance-profiler
✅ **Safe because:** Analysis only, no modifications

### Qt Team (⚠️ Parallel ONLY with Separate Files)
- qt-ui-modernizer → Assign specific UI files
- ui-ux-validator → Read-only validation
- qt-modelview-painter → Assign different model files
- qt-concurrency-architect → Assign different thread components
⚠️ **Warning:** Must assign non-overlapping file scopes

### Testing Team (⚠️ Parallel ONLY with Separate Scopes)
- test-development-master → Assign specific test categories
- test-type-safety-specialist → Assign different test files
⚠️ **Warning:** Both modify test files - MUST separate scopes

### Debug Team (Safe for Parallel - Analysis)
- deep-debugger → Investigates issues
- performance-profiler → Profiles performance
✅ **Safe because:** Both perform analysis, no file modifications

## Safe Parallel Patterns

### ✅ SAFE Parallel Examples
```python
# Different file scopes
Task 1: test-development-master → "Analyze tests/test_controller*.py"
Task 2: test-type-safety-specialist → "Fix types in tests/test_manager*.py"

# Read-only analysis
Task 1: deep-debugger → "Investigate failures in tests/"
Task 2: performance-profiler → "Profile test execution"

# Different directories
Task 1: python-implementation-specialist → "Fix issues in core/"
Task 2: test-development-master → "Create tests in tests/"
```

### ❌ UNSAFE Parallel Examples
```python
# Same files - WILL CONFLICT
Task 1: test-development-master → "Fix all test failures"
Task 2: test-type-safety-specialist → "Fix all type issues"

# Same file modifications
Task 1: python-implementation-specialist → "Update conftest.py"
Task 2: test-development-master → "Add fixtures to conftest.py"

# Overlapping scopes
Task 1: code-refactoring-expert → "Refactor tests/"
Task 2: test-type-safety-specialist → "Fix types in tests/"
```

## Pre-Deployment Checklist

Before deploying agents in parallel, verify:

1. **File Scope Check:**
   - [ ] Do agents modify different files? → Safe to parallel
   - [ ] Do agents modify same files? → Must run sequentially
   - [ ] Are scopes explicitly defined? → Required for parallel

2. **Operation Type Check:**
   - [ ] Read-only analysis? → Safe to parallel
   - [ ] Both creating new files? → Check naming conflicts
   - [ ] Both modifying code? → Verify non-overlapping scopes

3. **Resource Check:**
   - [ ] Heavy computation? → Consider resource limits
   - [ ] File system intensive? → May need sequencing
   - [ ] Network/API calls? → Check rate limits

## Quick Decision Rules

1. **One file, multiple agents?** → Queue them sequentially
2. **Implementation complete?** → Parallel analysis team (read-only)
3. **Qt GUI work?** → Qt team with SEPARATE file assignments
4. **Unknown bug?** → Debug team in parallel (analysis only)
5. **Need refactoring?** → Solo code-refactoring-expert
6. **Uncertain about overlap?** → Default to sequential

## Implementation Agent Selection

**python-expert-architect** for:
- Async/await, asyncio patterns
- Decorators, metaclasses, descriptors
- Framework or plugin systems
- Complex concurrency
- Performance-critical algorithms

**python-implementation-specialist** for:
- CRUD operations
- Data validation functions
- File parsing/processing
- API endpoints from specs
- Utility functions

## Red Flags (Don't Do This)

❌ **Multiple agents editing same file simultaneously** → Causes conflicts
❌ **Parallel deployment without explicit file scopes** → Leads to overlaps
❌ **Assuming "parallel" always means safe** → Check scope separation
❌ Running tests while code is being modified → Inconsistent results
❌ venv-keeper while other agents are running → Environment conflicts
❌ Refactoring without review first → May break working code
❌ Type checking without implementation → Premature optimization
❌ Using python-expert-architect for simple tasks → Overkill
❌ Using python-implementation-specialist for complex patterns → Insufficient

## Output Priority

1. 🔴 **Critical**: Crashes, data loss, security
2. 🟡 **Important**: Performance, major bugs
3. 🟢 **Improvements**: Code quality, optimizations
4. 🔵 **Enhancements**: Modernization, nice-to-haves

## Escalation Triggers

- Agent fails twice → Ask user for guidance
- Conflicting recommendations → Present options to user
- Missing capabilities → Suggest manual intervention
- Time-sensitive → Prioritize and inform user