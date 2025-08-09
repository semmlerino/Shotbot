# Running ShotBot Integration Tests

## Quick Start

### Prerequisites
```bash
# Ensure you're in the ShotBot directory
cd /mnt/c/CustomScripts/Python/PyFFMPEG/BB/shotbot

# Activate virtual environment (if using one)
source venv/bin/activate
```

### Run All New Integration Tests
```bash
# Run the new comprehensive integration tests
python run_tests.py tests/integration/test_raw_plate_finder_integration.py
python run_tests.py tests/integration/test_folder_opener_integration.py  
python run_tests.py tests/integration/test_threede_cache_persistence_integration.py
python run_tests.py tests/integration/test_performance_benchmarks_integration.py
python run_tests.py tests/integration/test_concurrent_stress_integration.py
```

### Run by Test Category

#### Critical Workflow Tests (Fast)
```bash
# Raw plate finder - comprehensive workflow tests
python run_tests.py tests/integration/test_raw_plate_finder_integration.py::TestRawPlateFinderIntegration

# Folder opener - filesystem operations  
python run_tests.py tests/integration/test_folder_opener_integration.py::TestFolderOpenerWorkerIntegration

# 3DE cache persistence - app restart simulation
python run_tests.py tests/integration/test_threede_cache_persistence_integration.py::TestThreeDECachePersistenceIntegration
```

#### Performance Benchmarks (Medium Speed)
```bash
# Performance benchmarks for critical paths
python run_tests.py -m performance tests/integration/test_performance_benchmarks_integration.py

# Or run specific benchmark classes
python run_tests.py tests/integration/test_performance_benchmarks_integration.py::TestPerformanceBenchmarks::test_shot_model_refresh_performance
```

#### Stress Tests (Slow - Use Sparingly)
```bash  
# Concurrent operations stress tests
python run_tests.py -m stress tests/integration/test_concurrent_stress_integration.py

# Or run specific stress test
python run_tests.py tests/integration/test_concurrent_stress_integration.py::TestConcurrentStressIntegration::test_concurrent_cache_operations_stress
```

### Run with Coverage
```bash
# Generate coverage report for new integration tests
python run_tests.py --cov=raw_plate_finder --cov=thumbnail_widget_base --cov=threede_scene_model --cov=cache_manager tests/integration/test_raw_plate_finder_integration.py tests/integration/test_folder_opener_integration.py tests/integration/test_threede_cache_persistence_integration.py
```

### Selective Test Execution

#### Run Only Non-Stress Tests
```bash
# Run integration tests excluding performance and stress tests
python run_tests.py tests/integration/ -m "not performance and not stress"
```

#### Run Only Quick Tests
```bash
# Run specific quick test methods
python run_tests.py tests/integration/test_raw_plate_finder_integration.py::TestRawPlateFinderIntegration::test_full_workflow_complex_structure
python run_tests.py tests/integration/test_folder_opener_integration.py::TestFolderOpenerWorkerIntegration::test_open_normal_directory
```

#### Run Performance Tests Only
```bash
# Run only performance-marked tests
python run_tests.py tests/integration/ -m performance
```

## Test Categories Overview

### 1. Raw Plate Finder Integration Tests
**File:** `test_raw_plate_finder_integration.py`
**Focus:** Complete plate discovery workflow
**Duration:** ~30 seconds (includes performance tests)
**Key Tests:**
- Complex plate structure handling
- Color space detection
- Version priority selection
- Edge cases and error handling
- Performance benchmarks

### 2. Folder Opener Integration Tests  
**File:** `test_folder_opener_integration.py`
**Focus:** Non-blocking folder opening across platforms
**Duration:** ~20 seconds
**Key Tests:**
- Cross-platform compatibility
- Path handling (spaces, Unicode, special chars)
- Error scenarios and recovery
- Concurrent operations
- Thread safety

### 3. 3DE Cache Persistence Integration Tests
**File:** `test_threede_cache_persistence_integration.py`  
**Focus:** Cache lifecycle and app restart simulation
**Duration:** ~40 seconds (includes MainWindow integration)
**Key Tests:**
- Cache creation and persistence
- TTL expiry and refresh
- App restart scenarios
- Cache corruption recovery
- Large dataset performance

### 4. Performance Benchmarks
**File:** `test_performance_benchmarks_integration.py`
**Focus:** Performance validation and regression detection  
**Duration:** ~60 seconds
**Key Tests:**
- Shot model refresh performance
- 3DE scene discovery benchmarks
- Cache operation speed
- Memory usage patterns
- Concurrent operation efficiency

### 5. Concurrent Stress Tests
**File:** `test_concurrent_stress_integration.py`
**Focus:** System behavior under high load and concurrency
**Duration:** ~90 seconds  
**Key Tests:**
- Concurrent cache operations
- Filesystem stress testing
- Resource exhaustion recovery
- Error handling under stress
- Long-running stability

## Expected Results

### Performance Targets
- **Raw Plate Finder**: <0.1s single shot, >100 shots/sec batch
- **Shot Model Refresh**: <2s cache miss, <0.5s cache hit  
- **3DE Scene Discovery**: <10s for 100 shots
- **Cache Operations**: <1s loading any size
- **Memory Usage**: <500MB for large datasets

### Success Criteria
- **Integration Tests**: >95% pass rate
- **Performance Tests**: Meet or exceed targets
- **Stress Tests**: >90% success rate under load
- **Error Handling**: Graceful degradation, no crashes

## Troubleshooting

### Common Issues

#### Import Errors
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Install missing dependencies
pip install -r requirements-dev.txt
```

#### Permission Errors (Linux/macOS)
```bash
# Some folder opener tests may require GUI session
export DISPLAY=:0  # If running in headless environment
```

#### Memory Issues (Stress Tests)
```bash
# Reduce concurrent workers if system is constrained
# Edit test files to reduce max_workers in ThreadPoolExecutor
```

#### Timeout Issues
```bash  
# Increase timeouts for slower systems
# Edit qtbot.waitUntil timeout values in test files
```

### Platform-Specific Notes

#### Linux (WSL)
- Folder opener may require file manager installation (`sudo apt install xdg-utils`)
- Some GUI tests may need X server setup

#### Windows  
- Folder opener should work with native Explorer
- Path handling tests cover Windows-specific scenarios

#### macOS
- Folder opener uses native `open` command
- All tests should work without additional setup

## Test Development

### Adding New Integration Tests
1. Create test file: `test_[feature]_integration.py`
2. Use existing fixtures from `conftest.py`
3. Add appropriate markers (`@pytest.mark.performance`, `@pytest.mark.stress`)
4. Follow naming convention: `test_[scenario]_[aspect]`
5. Include realistic error scenarios
6. Document expected performance characteristics

### Performance Test Guidelines
1. Establish baseline on reference hardware
2. Set reasonable tolerance ranges (±20% typically)  
3. Include warmup iterations for consistent results
4. Monitor memory usage and cleanup
5. Use `time.time()` for elapsed time measurement
6. Print results for trend monitoring

### Stress Test Guidelines
1. Use `ThreadPoolExecutor` for controlled concurrency
2. Include proper cleanup in try/finally blocks
3. Track success/failure rates, not just crashes
4. Test both resource exhaustion and recovery
5. Include realistic error injection
6. Monitor system resources (memory, file handles)

This comprehensive test suite ensures ShotBot's critical workflows are thoroughly validated across various real-world scenarios and edge cases.