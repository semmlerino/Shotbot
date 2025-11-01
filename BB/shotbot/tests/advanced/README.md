# Advanced Testing Suite for ShotBot

This directory contains advanced testing approaches that go beyond basic integration tests, providing comprehensive quality assurance through property-based testing, mutation testing, contract validation, and performance monitoring.

## Table of Contents

1. [Property-Based Testing](#property-based-testing)
2. [Mutation Testing](#mutation-testing)
3. [Contract Testing](#contract-testing)
4. [Snapshot Testing](#snapshot-testing)
5. [Performance Regression Testing](#performance-regression-testing)
6. [Test Quality Patterns](#test-quality-patterns)

## Property-Based Testing

### Overview

Property-based testing uses Hypothesis to generate random test inputs and verify that certain properties always hold true, regardless of the specific input values.

### Key Components

- **Custom Strategies**: Domain-specific data generators for shots, plates, versions, etc.
- **Invariant Testing**: Verifies that certain conditions always remain true
- **Stateful Testing**: Tests complex state machines with random operations

### Example Usage

```python
from hypothesis import given, strategies as st
from tests.advanced.test_property_based import shot_name_strategy

@given(shot_name=shot_name_strategy())
def test_shot_name_format(shot_name):
    # Property: All shot names follow the pattern XXX_YYY_ZZZZ
    parts = shot_name.split("_")
    assert len(parts) == 3
    assert parts[0].isdigit()
    assert parts[1].isalpha()
    assert parts[2].isdigit()
```

### Benefits

- **Finds edge cases**: Discovers bugs in corner cases you didn't think of
- **Better coverage**: Tests with hundreds of random inputs
- **Documentation**: Properties serve as specification

## Mutation Testing

### Overview

Mutation testing modifies your code to verify that tests actually catch bugs. If a test suite doesn't fail when code is broken, the tests need improvement.

### Mutation Strategies

1. **Boundary Mutations**: Changes comparison operators (`<` to `<=`)
2. **Return Value Mutations**: Swaps return values (`True` to `False`)
3. **Exception Mutations**: Removes or changes exception handling
4. **Path Mutations**: Modifies file system operations

### Example Usage

```python
from tests.advanced.test_mutation_strategies import MutationTestRunner

runner = MutationTestRunner()
result = runner.run_mutation_test(
    function=RawPlateFinder.find_latest_raw_plate,
    test_function=test_find_latest_raw_plate,
)

print(f"Mutation Score: {result['mutation_score']}%")
```

### Interpreting Results

- **Mutation Score > 80%**: Good test quality
- **Survived Mutations**: Indicate missing test cases
- **Killed Mutations**: Tests successfully caught the bug

## Contract Testing

### Overview

Contract testing ensures that components honor their interfaces and that integrations between components remain stable.

### Contract Types

1. **Interface Contracts**: Verify method signatures and return types
2. **Signal Contracts**: Validate Qt signal/slot connections
3. **Data Contracts**: Ensure data structures meet requirements
4. **Behavioral Contracts**: Verify expected behaviors

### Example Usage

```python
from tests.advanced.test_contract_validation import ContractValidator, CacheContract

# Verify a component implements a contract
cache = CacheManager()
assert ContractValidator.validate_interface(cache, CacheContract)

# Monitor contracts at runtime
monitor = ContractMonitor()
monitor.check_contract(cache, CacheContract, "Cache initialization")
```

### Benefits

- **Early detection**: Catches interface violations immediately
- **Documentation**: Contracts serve as API documentation
- **Refactoring safety**: Ensures changes don't break contracts

## Snapshot Testing

### Overview

Snapshot testing captures the state of your application at a point in time and compares it against future runs to detect unexpected changes.

### Snapshot Types

1. **UI State Snapshots**: Widget properties and hierarchy
2. **Cache State Snapshots**: Cache contents and statistics
3. **Configuration Snapshots**: Settings and preferences
4. **Data Snapshots**: Complex data structures

### Example Usage

```python
from tests.advanced.test_snapshot import SnapshotAssertion

def test_main_window_state(snapshot_tester):
    window = MainWindow()
    state = capture_widget_state(window)
    
    # First run creates snapshot, subsequent runs compare
    snapshot_tester.assert_matches_snapshot(
        state,
        "main_window_initial",
        update=False  # Set to True to update baseline
    )
```

### Workflow

1. **Create baseline**: First test run creates snapshot
2. **Detect changes**: Subsequent runs compare against baseline
3. **Review changes**: Decide if changes are intentional
4. **Update baseline**: Accept changes with `update=True`

## Performance Regression Testing

### Overview

Performance regression testing establishes baselines and monitors for performance degradation across releases.

### Key Features

1. **Benchmarking**: Measure execution time and memory usage
2. **Memory Leak Detection**: Identify memory leaks over iterations
3. **Performance Baselines**: Compare against historical performance
4. **CI/CD Integration**: Automated regression detection

### Example Usage

```python
from tests.advanced.test_performance_regression import PerformanceBenchmark

benchmark = PerformanceBenchmark(warmup_runs=2, test_runs=10)

# Benchmark execution time
metrics = benchmark.benchmark(model.refresh_shots)
assert metrics["median_time"] < 2.0  # Fail if slower than 2 seconds

# Check for memory leaks
detector = MemoryLeakDetector()
result = detector.check_leak(create_widgets, iterations=100)
assert not result["has_leak"]
```

### CI/CD Integration

```python
# In CI pipeline
monitor = CIPerformanceMonitor()
has_regression, details = monitor.check_regression(
    current_metrics,
    baseline_file=Path("baselines/performance.json"),
    threshold_percent=20  # Allow 20% degradation
)

if has_regression:
    raise AssertionError(f"Performance regression: {details}")
```

## Test Quality Patterns

### Overview

Test quality patterns provide reusable components for writing maintainable, isolated, and expressive tests.

### Key Patterns

#### 1. Test Data Factories

```python
from tests.advanced.test_quality_patterns import ShotFactory

# Create consistent test data
shot = ShotFactory.create(sequence="108", scene="CHV")
shots = ShotFactory.create_batch(10, status="pending")
```

#### 2. Builder Pattern

```python
from tests.advanced.test_quality_patterns import ShotModelBuilder

# Build complex test objects
model = (
    ShotModelBuilder()
    .with_shots(test_shots)
    .with_cache_disabled()
    .with_mock_ws_output("mocked output")
    .build()
)
```

#### 3. Isolation Patterns

```python
from tests.advanced.test_quality_patterns import IsolatedTest

class TestWithIsolation(IsolatedTest):
    def test_with_isolated_filesystem(self):
        with self.isolated_filesystem() as tmpdir:
            # Test with temporary directory
            test_file = tmpdir / "test.txt"
            test_file.write_text("content")
            
        # Automatically cleaned up
```

#### 4. Mock Builders

```python
from tests.advanced.test_quality_patterns import MockBuilder

# Create complex mocks easily
mock_process = MockBuilder.create_mock_process(
    returncode=0,
    stdout="Success output"
)

mock_widget = MockBuilder.create_mock_widget(
    QPushButton,
    text="Test Button",
    enabled=True
)
```

### Benefits

- **Consistency**: Factories ensure consistent test data
- **Maintainability**: Builders reduce test setup complexity
- **Isolation**: Prevents test interference
- **Readability**: Clear, expressive test code

## Running Advanced Tests

### Install Dependencies

```bash
pip install hypothesis psutil
```

### Run Specific Test Categories

```bash
# Property-based tests
pytest tests/advanced/test_property_based.py -v --hypothesis-show-statistics

# Mutation tests
pytest tests/advanced/test_mutation_strategies.py -v -m mutation

# Contract tests
pytest tests/advanced/test_contract_validation.py -v -m contract

# Snapshot tests
pytest tests/advanced/test_snapshot.py -v -m snapshot

# Performance tests
pytest tests/advanced/test_performance_regression.py -v -m performance

# Test quality examples
pytest tests/advanced/test_quality_patterns.py -v -m quality
```

### Update Snapshots

```bash
# Update all snapshots
pytest tests/advanced/test_snapshot.py --snapshot-update

# Or programmatically
snapshot_tester.assert_matches_snapshot(data, "snapshot_id", update=True)
```

### Generate Performance Baseline

```python
from tests.advanced.test_performance_regression import PerformanceReporter

benchmark = PerformanceBenchmark()
metrics = benchmark.benchmark(your_function)

# Save as baseline
PerformanceReporter.save_baseline(
    benchmark,
    Path("baselines/performance.json")
)
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Advanced Tests

on: [push, pull_request]

jobs:
  advanced-tests:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install hypothesis psutil
    
    - name: Run property-based tests
      run: pytest tests/advanced/test_property_based.py --hypothesis-profile=ci
    
    - name: Check performance regression
      run: |
        pytest tests/advanced/test_performance_regression.py -v
        python -m tests.advanced.check_regression
    
    - name: Validate contracts
      run: pytest tests/advanced/test_contract_validation.py -v
    
    - name: Upload performance results
      uses: actions/upload-artifact@v2
      with:
        name: performance-results
        path: performance_report.json
```

## Best Practices

### Property-Based Testing

1. **Start simple**: Begin with basic properties, add complexity gradually
2. **Think in invariants**: What should always be true?
3. **Use custom strategies**: Create domain-specific generators
4. **Set appropriate bounds**: Limit input sizes for performance

### Mutation Testing

1. **Focus on critical code**: Test business logic thoroughly
2. **Iterative improvement**: Address survived mutations incrementally
3. **Balance coverage**: 100% mutation score isn't always practical
4. **Document exceptions**: Some mutations may be acceptable

### Contract Testing

1. **Define clear contracts**: Be explicit about expectations
2. **Version contracts**: Handle contract evolution
3. **Test both sides**: Provider and consumer should validate
4. **Monitor production**: Use contract monitoring in production

### Snapshot Testing

1. **Review changes**: Don't blindly update snapshots
2. **Exclude volatile data**: Remove timestamps, IDs, etc.
3. **Commit snapshots**: Track snapshot changes in version control
4. **Keep snapshots small**: Focus on essential state

### Performance Testing

1. **Establish baselines early**: Before optimization
2. **Test realistic scenarios**: Use production-like data
3. **Monitor trends**: Track performance over time
4. **Set reasonable thresholds**: Allow for minor variations

## Troubleshooting

### Common Issues

1. **Hypothesis deadline exceeded**
   ```python
   @settings(deadline=None)  # Disable deadline
   ```

2. **Snapshot mismatches**
   - Review the diff carefully
   - Update if change is intentional
   - Fix code if change is a bug

3. **Performance test flakiness**
   - Increase warmup runs
   - Use median instead of mean
   - Run on consistent hardware

4. **Memory leak false positives**
   - Force garbage collection
   - Check for caching
   - Verify cleanup code

## Contributing

When adding new advanced tests:

1. Choose appropriate testing approach
2. Document the test purpose
3. Add to relevant test category
4. Update this README
5. Ensure CI/CD compatibility

## Resources

- [Hypothesis Documentation](https://hypothesis.readthedocs.io/)
- [Mutation Testing Introduction](https://en.wikipedia.org/wiki/Mutation_testing)
- [Contract Testing Guide](https://martinfowler.com/bliki/ContractTest.html)
- [Snapshot Testing Best Practices](https://jestjs.io/docs/snapshot-testing)
- [Performance Testing Strategies](https://martinfowler.com/articles/performance-testing.html)