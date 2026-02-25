# Reliable Test Patterns

## 1. Signal Testing Pattern

### ❌ Unreliable
```python
def test_signal_emission():
    obj.some_signal.emit("data")
    assert spy.count() == 1  # Race condition!
```

### ✅ Reliable
```python
def test_signal_emission(qtbot):
    spy = QSignalSpy(obj.some_signal)
    
    with qtbot.waitSignal(obj.some_signal, timeout=1000):
        obj.trigger_action()  # Triggers signal
    
    assert spy.count() == 1
    assert spy.at(0)[0] == "expected_data"
```

## 2. Thread Testing Pattern

### ❌ Unreliable
```python
def test_thread_operation():
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    thread.start()
    # Thread might not be finished!
```

### ✅ Reliable
```python
def test_thread_operation(qtbot, managed_threads):
    thread = managed_threads()  # Auto-cleanup
    worker = Worker()
    worker.moveToThread(thread)
    
    with qtbot.waitSignal(worker.finished, timeout=2000):
        thread.start()
        QTimer.singleShot(0, worker.process)
    
    thread.quit()
    thread.wait(1000)
```

## 3. Filesystem Testing Pattern

### ❌ Unreliable
```python
def test_file_operations(tmp_path):
    file = tmp_path / "test.txt"
    file.write_text("content")
    assert file.exists()  # Might fail on slow filesystems
```

### ✅ Reliable
```python
def test_file_operations(stable_filesystem, tmp_path):
    file = tmp_path / "test.txt"
    stable_filesystem.write_file(file, "content")
    # write_file ensures the file exists and has correct content
```

## 4. Resource Cleanup Pattern

### ❌ Unreliable
```python
def test_resource():
    timer = QTimer()
    timer.start(100)
    # Timer keeps running after test!
```

### ✅ Reliable
```python
def test_resource(qtbot):
    timer = QTimer()
    qtbot.addWidget(timer)  # Auto cleanup
    timer.start(100)
    
    # Or use context manager
    with closing(resource) as r:
        r.do_something()
```

## 5. Process Testing Pattern

### ❌ Unreliable
```python
def test_process():
    proc = subprocess.Popen(["cmd"])
    # Process might still be running
```

### ✅ Reliable
```python
def test_process():
    proc = subprocess.Popen(["cmd"])
    try:
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(1)
```
