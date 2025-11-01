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
| deep-debugger | Opus | Complex bugs | performance-profiler |
| venv-keeper | Sonnet | Environment | None (exclusive) |
| api-documentation-specialist | Sonnet | API design + docs | All analysis agents |

## Common Workflows

### 🚀 New Feature
```
architect → implementation-specialist → (review + type-check) → test
```

### 🐛 Debug Issue
```
(deep-debugger + profiler) → review → implementation-specialist → test
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

### Analysis Team (All Parallel)
- python-code-reviewer
- type-system-expert
- performance-profiler

### Qt Team (All Parallel)
- qt-ui-modernizer
- ui-ux-validator
- qt-modelview-painter
- qt-concurrency-architect

### Testing Team (Parallel)
- test-development-master
- test-type-safety-specialist

### Debug Team (Parallel)
- deep-debugger
- performance-profiler

## Quick Decision Rules

1. **One file, multiple agents?** → Queue them
2. **Implementation complete?** → Parallel analysis team
3. **Qt GUI work?** → Qt team in parallel
4. **Unknown bug?** → Debug team in parallel
5. **Need refactoring?** → Solo code-refactoring-expert

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

❌ Multiple agents editing same file simultaneously
❌ Running tests while code is being modified
❌ venv-keeper while other agents are running
❌ Refactoring without review first
❌ Type checking without implementation
❌ Using python-expert-architect for simple tasks
❌ Using python-implementation-specialist for complex patterns

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