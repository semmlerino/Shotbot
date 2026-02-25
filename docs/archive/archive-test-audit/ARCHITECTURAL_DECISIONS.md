# Architectural Decision Records (ADRs)

## Overview
This document captures key architectural decisions made during the Week 2 refactoring of the ShotBot application. Each decision is documented with context, alternatives considered, and rationale.

---

## ADR-001: Python 3.12 Type System Migration

### Status
Accepted and Implemented

### Context
The codebase used Python 3.9-style type hints with `Optional[T]` and `Union[A, B]` syntax. Python 3.12 introduced the `|` operator for type unions, providing cleaner, more readable type annotations.

### Decision
Migrate all type hints to Python 3.12 syntax using the `|` operator.

### Consequences
**Positive:**
- Cleaner, more readable type annotations
- Reduced import dependencies on `typing` module
- Better IDE support and autocomplete
- Aligned with modern Python practices

**Negative:**
- Requires Python 3.10+ for runtime
- Needs `from __future__ import annotations` for forward references
- Initial migration created syntax errors requiring manual fixes

### Alternatives Considered
1. **Keep Python 3.9 syntax**: Rejected - missing modern improvements
2. **Mixed syntax**: Rejected - inconsistent codebase
3. **Wait for Python 3.13**: Rejected - 3.12 syntax stable and available

---

## ADR-002: Modular Cache Architecture

### Status
Accepted and Implemented

### Context
The original `cache_manager.py` was a 1,476-line monolithic class handling storage, thumbnails, memory management, and validation. This violated SOLID principles and made testing difficult.

### Decision
Decompose into specialized components:
- `StorageBackend`: Atomic file operations
- `FailureTracker`: Exponential backoff logic
- `MemoryManager`: LRU eviction
- `ThumbnailProcessor`: Image processing
- `CacheValidator`: Consistency checks

### Consequences
**Positive:**
- Each component has single responsibility
- Easier unit testing with focused interfaces
- Better error isolation
- Reusable components

**Negative:**
- More files to manage
- Slightly increased import complexity
- Need facade for backward compatibility

### Alternatives Considered
1. **Keep monolithic**: Rejected - unmaintainable
2. **Microservices**: Rejected - overengineering for desktop app
3. **Inheritance hierarchy**: Rejected - composition preferred

---

## ADR-003: Qt Signal Optimization Strategy

### Status
Proposed

### Context
Analysis revealed 1,130% overhead from Qt signal operations (107 signals causing 113µs overhead on 10µs operations).

### Decision
Implement three-tier optimization:
1. **Batch signals**: Combine multiple emissions
2. **Coalesce signals**: Merge rapid successive signals
3. **Direct calls**: Replace same-thread signals

### Consequences
**Positive:**
- 90% reduction in signal overhead
- Improved UI responsiveness
- Better battery life on laptops

**Negative:**
- Added complexity with batching logic
- Potential latency from batching
- Need careful tuning of batch windows

### Alternatives Considered
1. **Keep current signals**: Rejected - unacceptable overhead
2. **Remove all signals**: Rejected - breaks Qt architecture
3. **Custom event system**: Rejected - reinventing Qt

---

## ADR-004: Future Annotations for Forward References

### Status
Accepted and Implemented

### Context
Using `|` operator with string type hints (forward references) causes `TypeError`. Python's `from __future__ import annotations` enables postponed annotation evaluation.

### Decision
Add `from __future__ import annotations` to all modules using forward references with modern syntax.

### Consequences
**Positive:**
- Enables modern syntax with forward references
- Consistent annotation style
- No runtime type checking overhead

**Negative:**
- Extra import in 13+ files
- Annotations become strings at runtime
- Some tools may need updates

### Alternatives Considered
1. **Import actual types**: Rejected - circular dependencies
2. **Use old syntax for forward refs**: Rejected - inconsistent
3. **Avoid forward references**: Rejected - poor design

---

## ADR-005: Test Strategy - Doubles Over Mocks

### Status
Accepted

### Context
Mock-heavy tests were brittle, hard to understand, and often tested implementation rather than behavior.

### Decision
Prefer test doubles (fakes, stubs) over mocks following the UNIFIED_TESTING_GUIDE principles.

### Consequences
**Positive:**
- Tests focus on behavior, not implementation
- More readable test code
- Better type safety with protocols
- Easier refactoring

**Negative:**
- More test double code to write
- Need to maintain test doubles
- Initial learning curve

### Alternatives Considered
1. **Continue with mocks**: Rejected - too brittle
2. **Integration tests only**: Rejected - slow feedback
3. **No tests**: Rejected - obviously bad

---

## ADR-006: Lazy Loading for Startup Performance

### Status
Proposed

### Context
Startup profiling showed 1,316ms total time with 559ms (42%) spent importing PySide6.QtWidgets.

### Decision
Implement lazy loading strategy:
- Defer Qt widget imports
- Create tabs on activation
- Load data asynchronously

### Consequences
**Positive:**
- Reduce startup time to <500ms
- Better perceived performance
- Progressive enhancement

**Negative:**
- More complex initialization
- Need to handle loading states
- Potential for lazy loading bugs

### Alternatives Considered
1. **Eager loading**: Rejected - slow startup
2. **Precompilation**: Rejected - doesn't help imports
3. **Native implementation**: Rejected - loses Python benefits

---

## ADR-007: Process Pool for Subprocess Management

### Status
Accepted and Implemented

### Context
Multiple components needed subprocess execution with similar patterns: timeout handling, output parsing, and error management.

### Decision
Centralize subprocess management in `ProcessPoolManager` with:
- Command caching (30s TTL)
- Session reuse
- Automatic retry logic
- Consistent error handling

### Consequences
**Positive:**
- Reduced code duplication
- Consistent subprocess handling
- Better performance with caching
- Easier testing with single mock point

**Negative:**
- Single point of failure
- Cache invalidation complexity
- Extra abstraction layer

### Alternatives Considered
1. **Direct subprocess calls**: Rejected - duplication
2. **Thread pool only**: Rejected - doesn't help subprocesses
3. **External process manager**: Rejected - overengineering

---

## ADR-008: TypedDict for Configuration

### Status
Accepted and Implemented

### Context
Dictionary-based configurations lacked type safety, leading to runtime errors and poor IDE support.

### Decision
Use TypedDict for all configuration dictionaries:
- `ShotDict`
- `ThumbnailCacheDict`
- `PerformanceMetricsDict`
- `ValidationResultDict`

### Consequences
**Positive:**
- Type safety for dictionary operations
- IDE autocomplete and validation
- Clear documentation of structure
- Runtime validation possible

**Negative:**
- More verbose than plain dicts
- Need to maintain synchronization
- Some runtime overhead

### Alternatives Considered
1. **Plain dicts**: Rejected - no type safety
2. **Dataclasses**: Rejected - breaking change
3. **Pydantic**: Rejected - extra dependency

---

## ADR-009: Lock-Free Architecture

### Status
Proposed

### Context
Thread safety through locking adds overhead and complexity. Modern Python offers lock-free alternatives.

### Decision
Migrate to lock-free patterns:
- Queue for thread communication
- Actor model for workers
- Atomic operations where possible
- Async/await for I/O

### Consequences
**Positive:**
- Eliminated lock overhead
- No deadlock possibility
- Better scalability
- Simpler reasoning

**Negative:**
- Learning curve for team
- Potential race conditions
- Need careful design

### Alternatives Considered
1. **Keep locks**: Rejected - overhead
2. **Single-threaded**: Rejected - poor UX
3. **Process-based**: Rejected - IPC overhead

---

## ADR-010: Exponential Backoff for Failed Operations

### Status
Accepted and Implemented

### Context
Thumbnail loading failures would retry immediately, causing system thrashing when resources were constrained.

### Decision
Implement exponential backoff:
- 5 minutes → 15 minutes → 45 minutes → 2 hours
- Reset on success
- Track failures per path

### Consequences
**Positive:**
- Prevents system thrashing
- Graceful degradation
- Self-healing behavior

**Negative:**
- Delayed retry for transient failures
- Memory for failure tracking
- Complexity in failure tracker

### Alternatives Considered
1. **No retry**: Rejected - poor UX
2. **Fixed retry interval**: Rejected - still thrashes
3. **Circuit breaker**: Rejected - overengineering

---

## Principles Derived

From these decisions, key architectural principles emerge:

1. **Composition over inheritance**: Modular components with clear interfaces
2. **Type safety first**: Comprehensive type hints and validation
3. **Performance by design**: Profile, measure, optimize
4. **Progressive enhancement**: Fast initial load, enhance progressively
5. **Fail gracefully**: Exponential backoff, fallback strategies
6. **Test behavior, not implementation**: Test doubles over mocks
7. **Modern Python**: Use latest stable features
8. **Single responsibility**: Each component does one thing well
9. **Lock-free when possible**: Prefer message passing to shared state
10. **Cache aggressively**: But invalidate intelligently

## Future Considerations

### Short Term (1-2 weeks)
- Implement lazy loading for startup performance
- Complete Qt signal optimization
- Add comprehensive benchmarking

### Medium Term (1-2 months)
- Migrate to async/await for I/O operations
- Implement actor model for workers
- Add telemetry for performance monitoring

### Long Term (3-6 months)
- Consider Rust extensions for performance-critical paths
- Evaluate WebGPU for thumbnail processing
- Investigate Qt Quick for modern UI

## Conclusion

These architectural decisions prioritize:
- **Developer experience** through type safety and clear patterns
- **User experience** through performance optimization
- **Maintainability** through modular architecture
- **Reliability** through graceful failure handling

The decisions are living documents and should be revisited as the application evolves and new requirements emerge.