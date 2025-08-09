# Test Mocking Refactoring Guide for ShotBot

## Executive Summary

This guide identifies over-mocked tests in the ShotBot test suite and provides concrete recommendations for simplification. The goal is to make tests more readable, maintainable, and focused on testing real behavior rather than mock implementations.

## Key Principles

1. **Use real implementations when possible** - Temp directories, real Qt widgets, actual files
2. **Mock only external dependencies** - System commands, network calls, external services  
3. **Keep mocks simple and readable** - Avoid deeply nested mock chains
4. **Test behavior, not implementation** - Focus on outcomes rather than internal calls

## File-by-File Analysis

### 1. test_threede_scene_finder.py - NEEDS MAJOR REFACTORING

**Current Problems:**
- 90% of the test is mocking Path operations
- Complex nested mock chains (lines 84-123) that are hard to understand
- Testing mock behavior instead of actual file discovery logic

**Necessary Mocks:**
- `PathUtils.build_path()` - Only when testing network path validation
- Nothing else really needs mocking

**Recommended Refactoring:**
```python
# BEFORE: Complex path mocking (lines 31-67)
mock_user = Mock()
mock_user.is_dir.return_value = True
mock_user.name = "john-d"
mock_scene_file = Mock(spec=Path)
mock_scene_file.relative_to.return_value = Path("BG01/subfolder/scene.3de")
# ... 30+ more lines of mocking

# AFTER: Real filesystem
john_dir = tmp_path / "user" / "john-d" / "scenes" / "BG01"
john_dir.mkdir(parents=True)
(john_dir / "scene.3de").write_text("3DE data")
```

### 2. test_main_window.py - NEEDS MODERATE REFACTORING

**Current Problems:**
- Mocking QTimer when we could use short intervals
- Creating MagicMock of MainWindow instead of real instances (lines 86-129)
- Mocking widget methods that could be tested with real widgets

**Necessary Mocks:**
- `subprocess.run` for ws command
- `QMessageBox` for user dialogs
- File operations when testing error conditions

**Recommended Refactoring:**
```python
# BEFORE: Mocked MainWindow (lines 90-130)
window = MagicMock(spec=MainWindow)
window.shot_model = MagicMock()
window.shot_grid = MagicMock()
# ... lots of mock setup

# AFTER: Real MainWindow with qtbot
window = MainWindow()
qtbot.addWidget(window)
window.refresh_timer.setInterval(10)  # Fast for testing
```

### 3. test_raw_plate_finder.py - GOOD EXAMPLE, NO CHANGES NEEDED ✓

**Why it's good:**
- Uses tmp_path fixture effectively
- Creates real directory structures
- No unnecessary mocking
- Tests actual filesystem behavior

This file should be used as a template for refactoring other tests.

### 4. test_shot_model.py - NEEDS MINOR REFACTORING

**Current Problems:**
- Repetitive cache manager mocking in every test
- Could use fixtures more effectively

**Necessary Mocks:**
- `subprocess.run` for ws command (external shell function)
- `CacheManager` for test isolation

**Recommended Refactoring:**
```python
# Create reusable fixture
@pytest.fixture
def shot_model_with_mock_cache(monkeypatch):
    mock_cache = Mock()
    mock_cache.get_cached_shots.return_value = None
    monkeypatch.setattr("shot_model.CacheManager", lambda: mock_cache)
    return ShotModel(), mock_cache
```

## Specific Refactoring Strategies

### Strategy 1: Replace Path Mocks with Temp Directories

**When to use:** Any test that mocks Path, os.path, or file operations

**How to implement:**
1. Use pytest's `tmp_path` fixture
2. Create real directory structures
3. Write actual files with minimal content
4. Test real filesystem behavior

**Benefits:**
- Tests actual path handling logic
- Catches real filesystem edge cases
- More readable test setup

### Strategy 2: Use Real Qt Widgets with qtbot

**When to use:** Any test mocking Qt widgets or signals

**How to implement:**
1. Create real widget instances
2. Use qtbot.addWidget() for cleanup
3. Use qtbot.waitSignal() for async operations
4. Override long timers with short intervals

**Benefits:**
- Tests real Qt behavior
- Catches signal/slot issues
- Tests actual widget state

### Strategy 3: Simplify Mock Chains

**When to use:** Any mock setup longer than 5 lines

**How to implement:**
1. Use simple Mock() objects with clear attributes
2. Create builder/factory functions for complex test data
3. Use fixtures for reusable mock setups

**Benefits:**
- More readable tests
- Easier to maintain
- Clear test intent

### Strategy 4: Builder Pattern for Test Data

**When to use:** Complex test data setup

**How to implement:**
```python
class TestDataBuilder:
    def add_shot(self, ...): ...
    def with_thumbnail(self): ...
    def with_3de_scene(self): ...
    def build(self): ...
```

**Benefits:**
- Reusable test data creation
- Self-documenting test setup
- Reduces duplication

## Implementation Priority

### High Priority (Fix First)
1. `test_threede_scene_finder.py` - Complex path mocking
2. `test_main_window.py` lines 86-129 - MagicMock MainWindow

### Medium Priority
3. `test_shot_model.py` - Fixture extraction
4. `test_main_window.py` - Timer mocking

### Low Priority (Nice to Have)
5. Extract common fixtures to conftest.py
6. Create integration test suite with minimal mocking

## Testing Anti-Patterns to Avoid

1. **Mock Spaghetti**: Deeply nested mock.return_value.method.return_value chains
2. **Testing Mocks**: Assertions that only verify mock calls, not behavior
3. **Over-Isolation**: Mocking everything, even simple Python objects
4. **Magic Mocks Everywhere**: Using MagicMock when Mock would suffice
5. **Mock State Management**: Complex mock state that mirrors implementation

## Best Practices Going Forward

1. **Start with real objects**, add mocks only when necessary
2. **Mock at boundaries** - external services, not internal components
3. **Use fixtures** for common mock setups
4. **Document why** each mock is necessary
5. **Review mock complexity** - if setup > 10 lines, reconsider approach
6. **Prefer integration tests** with minimal mocking for critical paths

## Example Refactoring Checklist

When refactoring a test file:

- [ ] Identify all mocked components
- [ ] Categorize as "necessary" or "replaceable"
- [ ] Replace path mocks with tmp_path
- [ ] Replace widget mocks with real widgets + qtbot
- [ ] Extract repetitive mocks to fixtures
- [ ] Simplify complex mock chains
- [ ] Add comments explaining remaining mocks
- [ ] Verify tests still pass and are more readable

## Conclusion

The ShotBot test suite would benefit significantly from reducing mock complexity. The main issues are:

1. **Path operations** that should use real temp directories
2. **Qt widgets** that should use real instances with qtbot
3. **Complex mock chains** that obscure test intent

By following the strategies in this guide, the test suite will become:
- More maintainable
- More reliable at catching real bugs
- Easier for new developers to understand
- Better at testing actual behavior vs implementation details