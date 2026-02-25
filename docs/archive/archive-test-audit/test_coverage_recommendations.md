# Critical Test Coverage Recommendations

## High Priority Test Cases (URGENT)

### 1. Shot Item Model Async Callback Tests

```python
def test_async_callback_race_condition_protection():
    """Test that async callbacks handle shot removal gracefully."""
    # Create model with shots
    # Start async thumbnail loading
    # Remove shot from model during callback
    # Verify callback handles missing shot without crash
    
def test_qmetaobject_invoke_method_thread_safety():
    """Test QMetaObject.invokeMethod for cross-thread safety."""
    # Simulate callback from worker thread
    # Verify method gets invoked on main thread safely
    # Test with various Qt argument types

def test_immutable_shot_identifier_capture():
    """Test that shot_full_name is captured correctly for callbacks."""
    # Test that shot identity is preserved across async operations
    # Verify callbacks work even if shot object changes
```

### 2. Shot Info Panel QRunnable Tests

```python
def test_info_panel_pixmap_loader_success():
    """Test InfoPanelPixmapLoader successful image loading."""
    
def test_info_panel_loader_error_handling():
    """Test error handling in async pixmap loading."""
    
def test_dimension_validation_integration():
    """Test integration with ImageUtils dimension validation."""
```

### 3. Thread Safety Regression Tests

```python
def test_concurrent_model_operations():
    """Test multiple models updating simultaneously."""
    
def test_async_callback_during_model_reset():
    """Test callbacks during beginResetModel/endResetModel."""
```

## Integration Test Scenarios

### Async Workflow Tests

```python
def test_thumbnail_loading_workflow_end_to_end():
    """Test complete thumbnail loading from cache miss to display."""
    
def test_shot_selection_with_concurrent_loading():
    """Test shot selection while thumbnails load asynchronously."""
    
def test_model_refresh_during_async_operations():
    """Test shot list refresh while async operations are in progress."""
```

## Thread Safety Test Requirements

### Key Race Conditions to Test

1. **Shot removal during async callback**
2. **Model reset during thumbnail loading** 
3. **Multiple concurrent thumbnail requests for same shot**
4. **QMetaObject.invokeMethod call safety**
5. **Cache state consistency during concurrent access**

### Testing Strategy

Use real Qt components with careful thread synchronization:
- QSignalSpy for async signal verification
- QTimer for controlled timing
- Real QRunnable and QThreadPool
- Proper qtbot.wait() for async operations

## Coverage Metrics Goals

- **shot_item_model.py**: 0% → 85%+ coverage
- **shot_info_panel.py**: 0% → 80%+ coverage  
- **Thread safety tests**: Add 15+ concurrent operation tests
- **Integration tests**: Add 8+ async workflow tests

## Implementation Priority

1. **CRITICAL**: Shot item model async callback tests
2. **CRITICAL**: Shot info panel QRunnable tests
3. **HIGH**: Thread safety regression tests
4. **MEDIUM**: Integration workflow tests
5. **LOW**: Performance benchmarks for async operations