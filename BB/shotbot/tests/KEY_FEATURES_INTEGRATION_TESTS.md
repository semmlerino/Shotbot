# Key Features Integration Tests

This document describes the comprehensive integration tests created for the key ShotBot features that were recently fixed and enhanced.

## Overview

The integration tests are located in `/tests/integration/test_key_features_integration.py` and cover four critical areas:

1. **Raw Plate Finder with Flexible Patterns**
2. **File URL Generation for Folder Opening**
3. **3DE Scene Deduplication**
4. **3DE Scene Caching Persistence**

## Test Structure

The tests are organized into distinct test classes, each focusing on a specific feature area:

### 1. TestRawPlateFinderIntegration

Tests the enhanced raw plate discovery system with flexible pattern matching and priority ordering.

**Key Tests:**
- `test_discover_plate_directories_priority_ordering`: Verifies that plates are discovered in correct priority order (BG01 > bg01 > FG01 > FG02)
- `test_raw_plate_finder_priority_selection`: Tests that BG01 is preferred over FG01 even if FG01 has newer versions
- `test_raw_plate_finder_version_selection_within_same_plate`: Tests version selection within the same plate type
- `test_raw_plate_finder_color_space_detection`: Tests automatic color space detection from file naming patterns
- `test_raw_plate_verification_workflow`: Tests complete workflow from discovery to verification

**Features Tested:**
- `PathUtils.discover_plate_directories()` with priority ordering
- Flexible plate naming pattern support (FG01, BG01, bg01, etc.)
- Color space extraction (aces, lin_rec709, srgb)
- Version detection and selection
- Graceful handling of missing data

### 2. TestFileUrlGenerationIntegration

Tests the non-blocking folder opening functionality with proper URL generation.

**Key Tests:**
- `test_folder_opener_worker_url_generation`: Verifies URLs have proper leading slashes for file protocol
- `test_folder_opener_fallback_mechanisms`: Tests fallback to system commands when Qt fails
- `test_folder_opener_platform_specific_commands`: Tests correct platform commands (open/explorer/xdg-open)
- `test_folder_opener_linux_gio_fallback`: Tests Linux gio fallback when xdg-open fails
- `test_folder_opener_thread_pool_integration`: Tests actual Qt thread pool execution

**Features Tested:**
- `FolderOpenerWorker` non-blocking execution
- Proper file:// URL generation with leading slashes
- Platform-specific command selection
- Error handling for non-existent paths
- Concurrent operation support

### 3. TestThreeDESceneDeduplicationIntegration

Tests the 3DE scene deduplication system that ensures only one scene per shot is displayed.

**Key Tests:**
- `test_scene_deduplication_one_per_shot`: Verifies that multiple scenes are reduced to one per shot
- `test_scene_selection_criteria_priority_and_mtime`: Tests priority-based selection (plate type → modification time)
- `test_display_name_simplification`: Verifies that plate info is removed from display names after deduplication
- `test_deduplication_with_file_access_errors`: Tests graceful handling of file access errors
- `test_deduplication_empty_results_handling`: Tests handling of empty discovery results

**Features Tested:**
- Scene deduplication logic in `ThreeDESceneModel`
- Priority-based scene selection (FG01 vs BG01 vs mtime)
- Simplified display names without plate information
- Error resilience with file system issues
- Change detection between refreshes

### 4. TestThreeDESceneCachePersistenceIntegration

Tests the caching system for 3DE scenes across application restarts and TTL refresh mechanisms.

**Key Tests:**
- `test_cache_persistence_across_app_restarts`: Tests that deduplicated scenes persist across app restarts
- `test_cache_ttl_refresh_mechanism`: Tests cache expiry and refresh behavior
- `test_cache_corruption_recovery`: Tests graceful recovery from corrupted cache files
- `test_concurrent_cache_access`: Tests multiple models sharing the same cache
- `test_cache_size_limits_and_cleanup`: Tests cache performance with large datasets

**Features Tested:**
- Cache persistence in `CacheManager`
- TTL-based cache expiration
- Recovery from corrupt cache data
- Concurrent access patterns
- Memory and storage efficiency

### 5. TestKeyFeaturesWorkflowIntegration

Tests complete workflows that combine multiple features working together.

**Key Tests:**
- `test_complete_shot_workflow`: Tests end-to-end workflow combining raw plate discovery, 3DE scene deduplication, and folder opening
- `test_workflow_with_missing_data_resilience`: Tests workflow resilience when some data is missing
- `test_workflow_performance_with_large_dataset`: Tests performance with 50+ shots

**Features Tested:**
- Complete feature integration
- Data resilience and error recovery
- Performance characteristics
- Real-world usage scenarios

## Test Data and Fixtures

The tests use sophisticated fixtures that create realistic directory structures:

### plate_structure_setup
Creates a comprehensive raw plate structure with:
- Multiple plate types (FG01, BG01, bg01, FG02, plate)
- Different versions (v001, v002, v003)
- Various color spaces (aces, lin_rec709, srgb)
- Realistic file timestamps for version testing

### folder_structure
Creates various folder types for URL testing:
- Normal folders
- Folders with spaces and special characters
- Unicode folder names
- Deep nested structures
- Relative paths

### scene_deduplication_setup
Creates isolated cache environments with:
- Temporary cache directories
- Multiple test shots
- Realistic scene data with different modification times

## Running the Tests

```bash
# Run all key features integration tests
python run_tests.py tests/integration/test_key_features_integration.py

# Run specific test class
python run_tests.py tests/integration/test_key_features_integration.py::TestRawPlateFinderIntegration

# Run specific test
python run_tests.py tests/integration/test_key_features_integration.py::TestRawPlateFinderIntegration::test_discover_plate_directories_priority_ordering

# Run with verbose output
python run_tests.py tests/integration/test_key_features_integration.py -v
```

## Test Coverage

The integration tests provide comprehensive coverage of:

✅ **Raw Plate Discovery**
- Flexible pattern matching (all common naming conventions)
- Priority-based selection (BG01 > FG01 > others)
- Version selection within plate types
- Color space detection and extraction
- Error handling for missing data

✅ **Folder Opening**
- Non-blocking worker thread execution
- Proper file:// URL generation
- Platform-specific command fallbacks
- Concurrent operation handling
- Error scenarios (missing paths, permission issues)

✅ **3DE Scene Management**
- Deduplication (multiple scenes → one per shot)
- Priority-based scene selection
- Display name simplification
- File access error resilience
- Change detection between discoveries

✅ **Cache Persistence**
- Cross-restart data persistence
- TTL-based refresh mechanisms
- Corruption recovery
- Concurrent access patterns
- Performance with large datasets

✅ **Workflow Integration**
- End-to-end feature interaction
- Data resilience patterns
- Performance characteristics
- Real-world scenario simulation

## Quality Assurance

The tests follow best practices for integration testing:

- **Isolated Test Environments**: Each test uses temporary directories and isolated caches
- **Realistic Data**: Test fixtures create realistic file structures and scenarios
- **Error Scenarios**: Tests cover both success and failure cases
- **Performance Testing**: Large dataset tests ensure scalability
- **Concurrent Operations**: Tests verify thread safety and concurrent access
- **Cross-Platform Compatibility**: Tests work on Linux, macOS, and Windows
- **Comprehensive Mocking**: Strategic mocking of external dependencies while testing real integration points

## Test Results

All 26 integration tests pass consistently:

```
============================== 26 passed in 1.15s ==============================
```

The tests provide confidence that the key ShotBot features work correctly both individually and in combination, handle edge cases gracefully, and maintain data integrity across application restarts and concurrent operations.