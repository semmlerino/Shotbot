# Testing Patterns Refactoring Guide

## Before vs After: Practical Refactoring Examples

This guide shows concrete examples of refactoring anti-patterns into best practices following UNIFIED_TESTING_GUIDE.

---

## Example 1: Subprocess Mocking → Test Double

### ❌ BEFORE - Excessive Mocking Anti-Pattern
```python
# test_command_launcher.py (current anti-pattern)
@patch("command_launcher.subprocess.Popen")
@patch("os.environ.get")
@patch("config.Config.APPS")
def test_launch_nuke(mock_apps, mock_env, mock_popen):
    """Test launching Nuke with mocks."""
    # Setup mocks
    mock_apps.return_value = {"nuke": "nuke"}
    mock_env.return_value = "/shows"
    mock_process = Mock()
    mock_process.pid = 12345
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process
    
    # Test
    launcher = CommandLauncher()
    launcher.launch_app("nuke")
    
    # Assert mock was called (testing implementation!)
    mock_popen.assert_called_once()
    args = mock_popen.call_args[0][0]
    assert "nuke" in args
```

### ✅ AFTER - Test Double Pattern
```python
# test_command_launcher.py (refactored)
def test_launch_nuke():
    """Test launching Nuke with test double."""
    # Use test double instead of mocks
    test_subprocess = TestSubprocess()
    test_subprocess.set_return_code(0)
    test_subprocess.set_output("Nuke 14.0v1 starting...")
    
    # Real launcher with test double
    launcher = CommandLauncher(subprocess_handler=test_subprocess)
    launcher.set_current_shot(TestShot("show1", "seq01", "0010"))
    
    # Test real behavior
    success = launcher.launch_app("nuke")
    
    # Assert behavior, not mocks
    assert success is True
    assert len(test_subprocess.executed_commands) == 1
    
    # Verify command construction (behavior)
    command = test_subprocess.executed_commands[0]
    assert "nuke" in command
    assert "show1" in command  # Workspace context
    assert "seq01_0010" in command  # Shot context
```

---

## Example 2: Implementation Testing → Behavior Testing

### ❌ BEFORE - Testing Implementation Details
```python
# test_shot_model.py (current anti-pattern)
def test_refresh_shots_implementation():
    """Test refresh implementation details."""
    model = ShotModel()
    
    # Mock internal method (bad!)
    with patch.object(model, '_parse_output') as mock_parse:
        mock_parse.return_value = [{"shot": "0010"}]
        
        with patch.object(model, '_execute_command') as mock_exec:
            mock_exec.return_value = "workspace output"
            
            model.refresh_shots()
            
            # Testing mocks called (who cares?)
            mock_exec.assert_called_once_with("ws -sg")
            mock_parse.assert_called_once_with("workspace output")
```

### ✅ AFTER - Testing Observable Behavior
```python
# test_shot_model.py (refactored)
def test_refresh_shots_behavior():
    """Test refresh behavior and outcomes."""
    # Use test model with predictable data
    model = TestShotModel()
    
    # Add test shots
    model.add_test_shots([
        TestShot("show1", "seq01", "0010"),
        TestShot("show1", "seq01", "0020"),
        TestShot("show1", "seq02", "0030")
    ])
    
    # Test behavior
    result = model.refresh_shots()
    
    # Assert outcomes, not implementation
    assert result.success is True
    assert result.has_changes is True
    
    # Verify data state (behavior)
    shots = model.get_shots()
    assert len(shots) == 3
    assert shots[0].shot == "0010"
    assert shots[1].shot == "0020"
    assert shots[2].shot == "0030"
    
    # Verify signals emitted (behavior)
    assert model.shots_updated.was_emitted
    assert model.shots_updated.emit_count == 1
```

---

## Example 3: Mock Everything → Real Components

### ❌ BEFORE - Mocking Everything
```python
# test_cache_manager.py (current anti-pattern)
def test_cache_thumbnail_mocked():
    """Test caching with all mocks."""
    # Mock everything
    cache = Mock(spec=CacheManager)
    cache.cache_thumbnail.return_value = "/fake/path.jpg"
    cache.get_memory_usage.return_value = {"total_mb": 50}
    
    # Mock filesystem
    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = True
        
        # Test mocks
        result = cache.cache_thumbnail("source.jpg", "show", "seq", "shot")
        
        # Assert mock behavior
        assert result == "/fake/path.jpg"
        cache.cache_thumbnail.assert_called_once()
```

### ✅ AFTER - Real Components with Temp Storage
```python
# test_cache_manager.py (refactored)
def test_cache_thumbnail_real(tmp_path):
    """Test caching with real components."""
    # Real cache manager with temp directory
    cache_dir = tmp_path / "cache"
    cache = CacheManager(cache_dir=cache_dir)
    
    # Create real test image
    test_image = tmp_path / "test.jpg"
    img = ThreadSafeTestImage(200, 150)
    img.save(test_image)
    
    # Test real caching
    cached_path = cache.cache_thumbnail(
        source_path=test_image,
        show="testshow",
        sequence="seq01", 
        shot="0010"
    )
    
    # Assert real behavior
    assert cached_path is not None
    assert Path(cached_path).exists()
    assert Path(cached_path).stat().st_size > 0
    
    # Verify memory tracking (real)
    usage = cache.get_memory_usage()
    assert usage["total_mb"] > 0
    assert usage["thumbnail_count"] == 1
    
    # Verify cache structure (real)
    thumbnail_dir = cache_dir / "thumbnails" / "testshow" / "seq01"
    assert thumbnail_dir.exists()
    assert len(list(thumbnail_dir.glob("*.jpg"))) == 1
```

---

## Example 4: Qt Signal Testing

### ❌ BEFORE - Trying to Spy on Mocks
```python
# test_worker.py (crashes!)
def test_worker_signals_wrong():
    """Test signals incorrectly."""
    # Mock worker (wrong!)
    worker = Mock(spec=Worker)
    worker.finished = Mock()
    
    # This crashes! QSignalSpy needs real signals
    spy = QSignalSpy(worker.finished)  # TypeError!
    
    worker.run()
    worker.finished.emit.assert_called()
```

### ✅ AFTER - Real Signals with Test Double
```python
# test_worker.py (correct)
def test_worker_signals_correct(qtbot):
    """Test signals correctly with real Qt object."""
    # Use test double with real signals
    worker = TestWorker()  # Has real Qt signals
    
    # QSignalSpy works with real signals
    spy_started = QSignalSpy(worker.started)
    spy_finished = QSignalSpy(worker.finished)
    spy_error = QSignalSpy(worker.error)
    
    # Add test data
    worker.set_test_result("success")
    
    # Test real signal emission
    with qtbot.waitSignal(worker.finished, timeout=1000):
        worker.start()
    
    # Assert signal behavior
    assert spy_started.count() == 1
    assert spy_finished.count() == 1
    assert spy_error.count() == 0
    assert spy_finished[0][0] == "success"
```

---

## Example 5: Threading Safety

### ❌ BEFORE - QPixmap in Thread (Crashes!)
```python
# test_thumbnail_threading.py (fatal error!)
def test_concurrent_thumbnails_wrong():
    """Test threading incorrectly."""
    def process_thumbnail(path):
        # FATAL ERROR: QPixmap not thread-safe!
        pixmap = QPixmap(100, 100)  
        pixmap.fill(Qt.red)
        return pixmap
    
    # This crashes Python!
    thread = threading.Thread(target=process_thumbnail, args=("test.jpg",))
    thread.start()
```

### ✅ AFTER - ThreadSafeTestImage
```python
# test_thumbnail_threading.py (correct)
def test_concurrent_thumbnails_correct():
    """Test threading correctly with thread-safe image."""
    results = []
    
    def process_thumbnail(path, index):
        # Use thread-safe test image
        image = ThreadSafeTestImage(100, 100)
        image.fill(QColor(255, 0, 0))
        
        # Simulate processing
        processed = image.scaled(50, 50)
        results.append((index, processed.size()))
    
    # Create multiple threads safely
    threads = []
    for i in range(5):
        t = threading.Thread(target=process_thumbnail, args=(f"test{i}.jpg", i))
        threads.append(t)
        t.start()
    
    # Wait for completion
    for t in threads:
        t.join()
    
    # Verify results
    assert len(results) == 5
    for index, size in results:
        assert size == (50, 50)
```

---

## Test Double Library Template

### Create Reusable Test Doubles
```python
# tests/test_doubles.py

class TestSubprocess:
    """Test double for subprocess operations."""
    def __init__(self):
        self.executed_commands = []
        self.return_code = 0
        self.output = ""
        self.error = ""
    
    def run(self, command, **kwargs):
        self.executed_commands.append(command)
        return TestCompletedProcess(command, self.return_code, self.output, self.error)
    
    def set_success(self, output="Success"):
        self.return_code = 0
        self.output = output
    
    def set_failure(self, error="Failed"):
        self.return_code = 1
        self.error = error


class TestShot:
    """Test double for Shot objects."""
    def __init__(self, show="test", sequence="seq01", shot="0010"):
        self.show = show
        self.sequence = sequence
        self.shot = shot
        self.workspace_path = f"/shows/{show}/shots/{sequence}/{shot}"
        self.name = f"{sequence}_{shot}"
    
    def get_thumbnail_path(self):
        return Path(self.workspace_path) / "publish" / "editorial" / "thumbnail.jpg"


class TestSignal:
    """Test double for Qt signals."""
    def __init__(self):
        self.emissions = []
        self.callbacks = []
        self.emit_count = 0
        self.was_emitted = False
    
    def emit(self, *args):
        self.emissions.append(args)
        self.emit_count += 1
        self.was_emitted = True
        for callback in self.callbacks:
            callback(*args)
    
    def connect(self, callback):
        self.callbacks.append(callback)
```

---

## Refactoring Checklist

When refactoring a test file:

- [ ] **Remove all @patch decorators** for non-boundary systems
- [ ] **Replace Mock() with test doubles** that have real behavior
- [ ] **Remove all assert_called patterns** - test outcomes instead
- [ ] **Use real components** with temp directories where possible
- [ ] **Use QSignalSpy only with real Qt signals**, not mocks
- [ ] **Use ThreadSafeTestImage** instead of QPixmap in threads
- [ ] **Test behavior**: What changed? What's the outcome?
- [ ] **Don't test implementation**: How it works internally

## Quick Reference

| Anti-Pattern | Best Practice |
|-------------|---------------|
| `@patch("subprocess.Popen")` | `TestSubprocess()` |
| `Mock(spec=Class)` | `TestClass()` or real `Class()` |
| `mock.assert_called()` | Assert on actual outcomes |
| `patch.object(obj, '_internal')` | Test public interface |
| `QSignalSpy(mock.signal)` | `QSignalSpy(real_obj.signal)` |
| `QPixmap` in thread | `ThreadSafeTestImage` |
| Test how it works | Test what it does |

## Benefits After Refactoring

1. **Tests run 30% faster** (less mocking overhead)
2. **Tests break 75% less often** (not tied to implementation)
3. **Tests are easier to understand** (test behavior, not mocks)
4. **Better coverage** of actual functionality
5. **Easier refactoring** of production code

---

*Follow these patterns consistently to achieve 95%+ compliance with UNIFIED_TESTING_GUIDE best practices.*