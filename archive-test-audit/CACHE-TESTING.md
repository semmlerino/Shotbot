# Cache Architecture Testing Guide

## Component Testing Matrix

| Component | Test in Isolation | Integration Points | Key Test Scenarios |
|-----------|------------------|-------------------|-------------------|
| StorageBackend | ✅ Yes | None | Atomic writes, fallback handling, thread safety |
| FailureTracker | ✅ Yes | None | Exponential backoff, cleanup, timestamp tracking |
| MemoryManager | ✅ Yes | None | LRU eviction, size tracking, limit enforcement |
| ThumbnailProcessor | ⚠️ Partial | Storage, Memory | Format support, thread safety (ThreadSafeTestImage) |
| ShotCache | ✅ Yes | Storage | TTL expiration, refresh, serialization |
| ThreeDECache | ✅ Yes | Storage | Metadata, deduplication, TTL |
| CacheValidator | ❌ No | All components | Consistency, repair, statistics |
| ThumbnailLoader | ❌ No | Processor, Failure | Async loading, signal emission |

## Component Isolation Testing
```python
def test_storage_backend_isolation(tmp_path):
    """Test StorageBackend without other components."""
    storage = StorageBackend(tmp_path)
    
    # Test atomic write
    storage.write_json("key", {"data": "value"})
    assert storage.read_json("key") == {"data": "value"}
    
    # Test thread safety
    import threading
    results = []
    
    def write_data(i):
        storage.write_json(f"key_{i}", {"id": i})
        results.append(i)
    
    threads = [threading.Thread(target=write_data, args=(i,)) 
               for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(results) == 10
```

## Component Integration Testing
```python
def test_thumbnail_pipeline_integration(tmp_path):
    """Test full thumbnail processing pipeline."""
    # Create integrated components
    storage = StorageBackend(tmp_path)
    memory = MemoryManager(max_size_mb=10)
    failure = FailureTracker(storage)
    processor = ThumbnailProcessor(storage, memory, failure)
    
    # Test successful processing
    image = ThreadSafeTestImage(100, 100)
    result = processor.process("shot_001", image)
    
    assert result.success
    assert memory.get_usage() > 0
    assert not failure.should_retry("shot_001")
    
    # Test failure handling
    processor.process("bad_shot", None)  # Will fail
    assert failure.should_retry("bad_shot") is False  # In backoff
```

## Cache Manager Facade Testing
```python
def test_cache_manager_facade(tmp_path):
    """Test the main CacheManager facade."""
    cache = CacheManager(cache_dir=tmp_path)
    
    # The facade should coordinate all components
    shot = Shot("TEST", "seq01", "0010", "/test/path")
    
    # Test thumbnail caching (involves multiple components)
    image_path = tmp_path / "test.jpg"
    image_path.write_bytes(b"fake_image_data")
    
    pixmap = cache.cache_thumbnail(
        source_path=str(image_path),
        show=shot.show,
        sequence=shot.sequence,
        shot=shot.shot
    )
    
    # Verify coordination
    assert cache.get_memory_usage() > 0
    assert cache.get_cached_thumbnail(shot.show, shot.sequence, shot.shot)
```