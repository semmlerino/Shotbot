# Type Safety Quick Reference

## Current Status
- **Type Errors**: 0
- **Type Warnings**: 57 (mostly Qt/external library limitations)
- **Type Notes**: 30 (Qt signal handlers - acceptable)
- **Mode**: Strict (basedpyright 1.32.1)

---

## Common Patterns to Follow

### 1. Function Type Annotations

```python
# ❌ WRONG - Missing parameter types
def process_shot(shot):
    return shot.workspace_path

# ✅ CORRECT - Full signature
def process_shot(shot: Shot) -> str:
    return shot.workspace_path

# ✅ CORRECT - Optional parameters
def find_shot(show: str, sequence: str, shot: str | None = None) -> Shot | None:
    ...

# ✅ CORRECT - Variable number of args
def launch(*args: str, **kwargs: str) -> ProcessInfoDict:
    ...
```

### 2. Type Definitions for Data

```python
# ❌ WRONG - Untyped dictionary
def load_config():
    return {
        "show": "VFX_001",
        "cache_ttl": 30,
        "users": ["artist1", "artist2"]
    }

# ✅ CORRECT - TypedDict
class ConfigDict(TypedDict):
    show: str
    cache_ttl: int
    users: list[str]

def load_config() -> ConfigDict:
    ...

# ✅ CORRECT - For complex returns, use NamedTuple
class RefreshResult(NamedTuple):
    shots: list[Shot]
    duration: float
    success: bool

def refresh_shots() -> RefreshResult:
    ...
```

### 3. Modern Type Syntax

```python
# ❌ OLD SYNTAX (still works, but outdated)
from typing import List, Dict, Optional, Union

def process(items: List[str]) -> Optional[Dict[str, int]]:
    ...

# ✅ NEW SYNTAX (Python 3.9+, preferred)
def process(items: list[str]) -> dict[str, int] | None:
    ...

# ✅ PATTERN - Use | instead of Union
x: str | int = "value"  # Instead of Union[str, int]
y: str | None = None     # Instead of Optional[str]
```

### 4. Class Attributes

```python
# ❌ WRONG - No type annotation
class ShotModel:
    def __init__(self, shots):
        self.shots = shots

# ✅ CORRECT - Class-level type hints
class ShotModel:
    shots: list[Shot]

    def __init__(self, shots: list[Shot]) -> None:
        self.shots = shots

# ✅ CORRECT - With ClassVar for class attributes
class ShotModel:
    _instance: ClassVar[ShotModel | None] = None
    shots: list[Shot]

    def __init__(self, shots: list[Shot]) -> None:
        self.shots = shots
```

### 5. Qt Signal Handling

```python
# ✅ CORRECT - Signal with type hint
from PySide6.QtCore import Signal

class ShotModel(QAbstractItemModel):
    shots_updated = Signal(list)  # Emits list[Shot]
    error_occurred = Signal(str)   # Emits error message

    def emit_update(self, shots: list[Shot]) -> None:
        self.shots_updated.emit(shots)

# ✅ CORRECT - Handle Qt's receivers() limitation
if self.shots_updated.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
    self.shots_updated.disconnect()
```

### 6. Circular Import Prevention

```python
# ✅ CORRECT - TYPE_CHECKING blocks
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cache_manager import CacheManager
    from other_module import ComplexType

class MyClass:
    def __init__(self, cache: CacheManager) -> None:
        # At runtime, CacheManager is not imported here
        # Type checker sees the annotation
        pass

# Use string annotation at runtime if needed:
def process(item: "ComplexType") -> None:
    ...
```

### 7. Protocol/Interface Design

```python
# ✅ CORRECT - Define protocol for duck typing
from typing import Protocol

@runtime_checkable
class Cacheable(Protocol):
    """Anything with to_dict() can be cached."""
    def to_dict(self) -> dict[str, str]: ...

def cache_item(item: Cacheable) -> None:
    data = item.to_dict()
    # ...

# ✅ Usage - Any object with to_dict() works
class Shot:
    def to_dict(self) -> dict[str, str]:
        ...

cache_item(Shot(...))  # Type checks correctly
```

### 8. Specific Type Ignores (Not Blanket Ignores)

```python
# ❌ WRONG - Blanket ignore (hides all errors)
value = untyped_function()  # type: ignore

# ✅ CORRECT - Specific error code
value = untyped_function()  # type: ignore[no-untyped-call]

# ✅ CORRECT - For Qt API limitations
if signal.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
    signal.disconnect()
```

### 9. List/Dict Annotations

```python
# ❌ WRONG - Type inference failure
items = []
for shot in shots:
    items.append(shot.name)  # ⚠️ Type of append is partially unknown

# ✅ CORRECT - Explicit type
items: list[str] = []
for shot in shots:
    items.append(shot.name)

# ✅ CORRECT - List comprehension (inferred automatically)
items = [shot.name for shot in shots]  # Type: list[str]
```

### 10. Optional Handling

```python
# ❌ WRONG - Unchecked optional access
thumbnail = shot.get_thumbnail_path()
size = len(thumbnail)  # 💥 Error if thumbnail is None

# ✅ CORRECT - Check before access
thumbnail = shot.get_thumbnail_path()
if thumbnail is not None:
    size = len(thumbnail)

# ✅ CORRECT - Using guard clause
if not (thumbnail := shot.get_thumbnail_path()):
    return None
size = len(thumbnail)  # Type checker knows it's not None
```

---

## Type Checking Commands

```bash
# Full type check (strict mode)
~/.local/bin/uv run basedpyright .

# Check specific file
~/.local/bin/uv run basedpyright controllers/launcher_controller.py

# Output JSON for tooling
~/.local/bin/uv run basedpyright . --outputjson

# Check for missing annotations
~/.local/bin/uv run ruff check --select ANN .

# Check for type-checking block issues
~/.local/bin/uv run ruff check --select TCH .

# Combined check (fast)
~/.local/bin/uv run basedpyright . && ~/.local/bin/uv run ruff check .
```

---

## Common Mistakes and Fixes

### Mistake 1: Function Returns None

```python
# ❌ WRONG - Return type unclear
def process_file(path: str):
    if not os.path.exists(path):
        return
    return open(path).read()  # ⚠️ None or str?

# ✅ CORRECT - Explicit return type
def process_file(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    return open(path).read()
```

### Mistake 2: Mutable Default Arguments

```python
# ❌ WRONG - Mutable default (also runtime bug)
def add_shot(shot: Shot, cache: list[Shot] = []) -> list[Shot]:
    cache.append(shot)
    return cache

# ✅ CORRECT - Use None as default
def add_shot(shot: Shot, cache: list[Shot] | None = None) -> list[Shot]:
    if cache is None:
        cache = []
    cache.append(shot)
    return cache
```

### Mistake 3: Overly Broad Types

```python
# ❌ WRONG - object is too broad
def process(data: object) -> None:
    # Can't use any methods without casting
    pass

# ✅ CORRECT - Use Protocol or Union
def process(data: Shot | ThreeDEScene) -> None:
    # Use common properties from both types
    print(data.shot)

# ✅ CORRECT - Use Protocol
class SceneData(Protocol):
    show: str
    shot: str

def process(data: SceneData) -> None:
    print(data.shot)
```

### Mistake 4: String Annotations When Not Needed

```python
# ❌ WRONG - Unnecessary string annotation
def get_shot(shot_id: int) -> "Shot":
    ...

# ✅ CORRECT - Direct type (if imported)
from type_definitions import Shot

def get_shot(shot_id: int) -> Shot:
    ...

# ⚠️ String annotation only needed for:
# 1. Circular imports (use TYPE_CHECKING instead)
# 2. Forward references (define after current class)
```

---

## Warning Categories and How to Fix

### Unknown Member Type

```
⚠️ Type of "receivers" is unknown (reportUnknownMemberType)
```

**Fix**:
```python
# Use specific ignore for Qt limitations
if signal.receivers(None) > 0:  # pyright: ignore[reportAttributeAccessIssue]
    signal.disconnect()
```

### Unknown Argument Type

```
⚠️ Argument type is unknown (reportUnknownArgumentType)
```

**Fix**:
```python
# Annotate the variable
items: list[str] = []
items.extend(results)  # Type checker now knows items contains strings
```

### Unknown Variable Type

```
⚠️ Type of "shows_list" is partially unknown (reportUnknownVariableType)
```

**Fix**:
```python
# Assign explicit type annotation
shows_list: list[str] = get_shows()  # Type checker knows the type
```

### Any Type (Information Level)

```
ℹ️ Type of "run" is Any (reportAny)
```

**Assessment**: This is usually OK - information-level notices don't require fixes. Common with:
- Qt signal decorators (@Slot())
- External library decorators
- Unavoidable framework limitations

---

## Type Safety in Testing

```python
# ✅ CORRECT - Typed test fixtures
from typing import Generator
import pytest

@pytest.fixture
def shot_model() -> Generator[ShotModel, None, None]:
    model = ShotModel(cache_manager)
    yield model
    model.cleanup()

# ✅ CORRECT - Typed assertions
def test_shot_loading(shot_model: ShotModel) -> None:
    shots: list[Shot] = shot_model.get_shots()
    assert len(shots) > 0
    assert all(isinstance(s, Shot) for s in shots)
```

---

## Type Annotations for Singletons

```python
# ✅ CORRECT - Thread-safe singleton with types
class ProgressManager:
    _instance: ClassVar[ProgressManager | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self.operations: list[str] = []

    @classmethod
    def get_instance(cls) -> ProgressManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing."""
        with cls._lock:
            cls._instance = None
```

---

## Final Checklist

Before committing, ensure:

- [ ] All public functions have return type annotations
- [ ] All function parameters have type annotations
- [ ] No blanket `# type: ignore` comments (use specific error codes)
- [ ] No unnecessary `Any` types (use Protocol or Union instead)
- [ ] TypedDict for data classes (not plain dict)
- [ ] NamedTuple for multi-value returns
- [ ] TYPE_CHECKING blocks for circular imports
- [ ] Type aliases for complex types
- [ ] Run `basedpyright` before pushing
- [ ] Run `ruff check --select ANN` to catch missing annotations

---

## Resources

- **Type Definitions**: `/home/gabrielh/projects/shotbot/type_definitions.py`
- **Protocols**: `/home/gabrielh/projects/shotbot/protocols.py`
- **Configuration**: `/home/gabrielh/projects/shotbot/pyproject.toml`
- **Full Analysis**: `/home/gabrielh/projects/shotbot/TYPE_SAFETY_ANALYSIS.md`

---

## Questions?

When in doubt:
1. Check existing patterns in `type_definitions.py` and `protocols.py`
2. Run `basedpyright` to see specific error
3. Check the Quick Reference above
4. Refer to full analysis in `TYPE_SAFETY_ANALYSIS.md`

Remember: Types are for developers, not runtime. They help catch bugs and document intent.
