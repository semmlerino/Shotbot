# Mock Reduction Analysis for ShotBot Tests

## Executive Summary
Analysis of 58 test files reveals significant over-mocking, particularly in:
- **test_threede_scene_finder.py**: 47 mock occurrences (worst offender)
- **test_command_launcher.py**: 32 mock occurrences (mostly necessary)
- **test_shot_model.py**: 10 mock occurrences

## Critical Issues Found

### 1. test_threede_scene_finder.py - SEVERE OVER-MOCKING
**Current State**: 47 mock occurrences, mocking Path objects and filesystem operations

**Problems**:
- Mocking `Path()` objects instead of using real filesystem
- Complex mock chains that are hard to understand
- Testing mock behavior rather than actual functionality
- Mock setup is longer than the actual test logic

**Example of Current Over-Mocking**:
```python
# BEFORE: Complex Path mocking
mock_user = Mock()
mock_user.is_dir.return_value = True
mock_user.name = "john-d"
mock_scene_file = Mock(spec=Path)
mock_scene_file.relative_to.return_value = Path("BG01/subfolder/scene.3de")
# ... 20+ more lines of mock setup
```

**Recommended Refactoring**:
```python
# AFTER: Use real filesystem with tmp_path
def test_find_scenes_for_shot_with_scenes(self, tmp_path):
    # Create real directory structure
    user_dir = tmp_path / "user" / "john-d" / "mm" / "3de" / "mm-default" / "scenes" / "scene" / "BG01"
    user_dir.mkdir(parents=True)
    scene_file = user_dir / "scene.3de"
    scene_file.write_text("3DE scene data")
    
    scenes = ThreeDESceneFinder.find_scenes_for_shot(
        str(tmp_path), "test_show", "AB_123", "0010", {"gabriel-h"}
    )
    
    assert len(scenes) == 1
    assert scenes[0].user == "john-d"
```

**Estimated Reduction**: 80% less mocking code

### 2. test_command_launcher.py - MOSTLY NECESSARY MOCKING
**Current State**: 32 mock occurrences, primarily `subprocess.Popen`

**Analysis**:
- `@patch("subprocess.Popen")` - ✅ NECESSARY (don't want to launch real apps)
- Mock Signal captures - ✅ NECESSARY (testing Qt signals)
- Mock Shot objects - ❌ UNNECESSARY (could use real Shot instances)

**Recommended Changes**:
```python
# BEFORE: Mocking Shot
shot = Mock(spec=Shot)
shot.show = "testshow"
shot.sequence = "101"

# AFTER: Use real Shot
shot = Shot(
    show="testshow",
    sequence="101",
    shot="0010",
    workspace_path="/test/path"
)
```

**Estimated Reduction**: 20% less mocking (keep subprocess mocks)

### 3. test_shot_model.py - MODERATE MOCKING
**Current State**: 10 mock occurrences

**Issues**:
- Repeated cache manager mocking in every test
- Could use fixtures more effectively

**Recommended Fixture**:
```python
@pytest.fixture
def shot_model_with_cache(qtbot, tmp_path):
    """Create ShotModel with real cache using tmp_path."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    model = ShotModel(cache_dir=str(cache_dir))
    qtbot.addWidget(model)
    return model
```

## Patterns to Eliminate

### ❌ Path Mocking (Use tmp_path instead)
```python
# BAD
with patch("pathlib.Path") as mock_path:
    mock_path.exists.return_value = True
    
# GOOD
def test_something(tmp_path):
    real_path = tmp_path / "test_dir"
    real_path.mkdir()
```

### ❌ Simple Data Object Mocking
```python
# BAD
shot = Mock(spec=Shot)
shot.show = "test"

# GOOD
shot = Shot(show="test", sequence="01", shot="001", workspace_path="/test")
```

### ❌ Qt Widget Mocking (Use real widgets with qtbot)
```python
# BAD
widget = MagicMock(spec=QWidget)

# GOOD
def test_widget(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
```

## Files Requiring Immediate Attention

### Priority 1 (Severe Over-Mocking)
1. **test_threede_scene_finder.py** - 47 mocks → ~10 mocks
2. **test_main_window.py** - Complex widget mocking → Real widgets
3. **test_shot_grid.py** - Mock widgets → Real widgets with qtbot

### Priority 2 (Moderate Issues)
4. **test_shot_model.py** - Repeated mocks → Fixtures
5. **test_thumbnail_widget.py** - Mock QPixmap → Real QPixmap
6. **test_cache_manager.py** - Mock filesystem → tmp_path

### Priority 3 (Minor Improvements)
7. **test_undistortion_finder.py** - Already improved but could extract fixtures
8. **test_command_launcher.py** - Keep subprocess mocks, fix data objects

## Implementation Plan

### Phase 1: Quick Wins (2 hours)
- Replace all `Mock(spec=Shot)` with real Shot objects
- Replace all `Mock(spec=ThreeDEScene)` with real objects
- Extract repeated mock setups to fixtures

### Phase 2: Filesystem Refactoring (4 hours)
- Replace Path mocking with tmp_path in all tests
- Use real file operations instead of mocked ones
- Create helper functions for common directory structures

### Phase 3: Qt Widget Refactoring (3 hours)
- Replace MagicMock widgets with real Qt widgets
- Use qtbot for proper lifecycle management
- Override long timers with short test intervals

## Expected Benefits

### Quantitative
- **Code Reduction**: ~40% less test code
- **Mock Reduction**: ~60% fewer mock objects
- **Performance**: ~20% faster test execution
- **Coverage**: Better real-world scenario testing

### Qualitative
- ✅ Tests verify actual behavior, not mock implementation
- ✅ More readable and maintainable tests
- ✅ Catches real bugs that mocks would miss
- ✅ Easier to understand test intent
- ✅ Better documentation through realistic examples

## Example: Complete Refactoring

### Before (68 lines with heavy mocking):
```python
def test_find_scenes_complex(self):
    with patch("pathlib.Path") as mock_path:
        mock_user_dir = Mock()
        mock_user = Mock()
        mock_scene_base = Mock()
        # ... 50+ lines of mock setup
        
        result = ThreeDESceneFinder.find_scenes(...)
        
        # Assertions mostly verify mock calls
        mock_user_dir.iterdir.assert_called()
```

### After (25 lines with real filesystem):
```python
def test_find_scenes_complex(self, tmp_path):
    # Create real test structure
    scene_dir = tmp_path / "user" / "john-d" / "mm" / "3de" / "scenes" / "BG01"
    scene_dir.mkdir(parents=True)
    (scene_dir / "test.3de").write_text("3DE content")
    
    result = ThreeDESceneFinder.find_scenes(str(tmp_path))
    
    # Assertions verify actual behavior
    assert len(result) == 1
    assert result[0].plate == "BG01"
```

## Conclusion

The ShotBot test suite suffers from severe over-mocking that:
1. Makes tests hard to understand and maintain
2. Tests mock behavior instead of real functionality
3. Creates brittle tests that break when implementation changes
4. Misses real bugs that only surface with actual objects

**Immediate Action**: Start with test_threede_scene_finder.py refactoring to demonstrate the value, then systematically refactor other high-priority files.

**Long-term Goal**: Establish testing guidelines that prefer real objects and filesystem operations over mocks, using mocks only for external dependencies (subprocess, network, etc.).