"""Meta-tests for the test fixture infrastructure itself.

Tests classes that are non-trivial but have zero test coverage:
- SingletonRegistry: registration, ordering, error collection, caching
- DialogRecorder: assertion helpers, return-value overrides
- Qt marker structural validation: every file importing PySide6 at runtime
  must use qtbot or @pytest.mark.qt.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.fixtures.qt_fixtures import DialogRecorder
from tests.fixtures.singleton_fixtures import SingletonEntry, SingletonRegistry


if TYPE_CHECKING:
    from collections.abc import Generator


# ---------------------------------------------------------------------------
# Helpers shared by Group 1 tests
# ---------------------------------------------------------------------------

_call_order: list[str] = []


class _FakeSingletonA:
    @classmethod
    def reset(cls) -> None:
        _call_order.append("A")


class _FakeSingletonB:
    @classmethod
    def reset(cls) -> None:
        _call_order.append("B")


class _FakeSingletonC:
    @classmethod
    def reset(cls) -> None:
        _call_order.append("C")


class _BrokenSingleton:
    @classmethod
    def reset(cls) -> None:
        raise RuntimeError("intentional reset failure")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_REAL_PATH = "tests.fixtures.singleton_fixtures.SingletonRegistry"


@pytest.fixture
def clean_registry() -> Generator[None, None, None]:
    """Isolate SingletonRegistry for testing."""
    original_entries = SingletonRegistry._entries.copy()
    original_cache = SingletonRegistry._class_cache.copy()
    SingletonRegistry.clear()
    _call_order.clear()
    yield
    SingletonRegistry._entries.clear()
    SingletonRegistry._entries.extend(original_entries)
    SingletonRegistry._class_cache.clear()
    SingletonRegistry._class_cache.update(original_cache)
    _call_order.clear()


# ---------------------------------------------------------------------------
# Group 1: SingletonRegistry tests
# ---------------------------------------------------------------------------


def test_register_duplicate_order_raises(clean_registry: None) -> None:
    """Registering two entries with the same cleanup_order raises ValueError."""
    SingletonRegistry.register(_REAL_PATH, cleanup_order=1)
    with pytest.raises(ValueError, match="Duplicate cleanup order 1"):
        SingletonRegistry.register(_REAL_PATH, cleanup_order=1)


def test_register_invalid_import_raises(clean_registry: None) -> None:
    """Registering an unresolvable import path raises ValueError."""
    bad_path = "nonexistent.module.Fake"
    with pytest.raises(ValueError, match=bad_path):
        SingletonRegistry.register(bad_path, cleanup_order=99)


def test_reset_all_calls_reset_in_order(
    clean_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reset_all() invokes reset() on each entry sorted by cleanup_order."""
    path_a = "fake.module.A"
    path_b = "fake.module.B"
    path_c = "fake.module.C"

    class_map = {
        path_a: _FakeSingletonA,
        path_b: _FakeSingletonB,
        path_c: _FakeSingletonC,
    }

    original_get_class = SingletonRegistry._get_class.__func__  # type: ignore[attr-defined]

    def patched_get_class(cls: type, import_path: str) -> type | None:
        if import_path in class_map:
            return class_map[import_path]
        return original_get_class(cls, import_path)

    monkeypatch.setattr(SingletonRegistry, "_get_class", classmethod(patched_get_class))

    # Register in non-sorted order: A=3, B=1, C=2
    SingletonRegistry._entries.append(SingletonEntry(import_path=path_a, cleanup_order=3))
    SingletonRegistry._entries.append(SingletonEntry(import_path=path_b, cleanup_order=1))
    SingletonRegistry._entries.append(SingletonEntry(import_path=path_c, cleanup_order=2))
    SingletonRegistry._entries.sort(key=lambda e: e.cleanup_order)

    SingletonRegistry.reset_all()

    assert _call_order == ["B", "C", "A"]


def test_reset_all_collects_errors(
    clean_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reset_all() does not raise when a singleton's reset() fails; it returns errors."""
    bad_path = "fake.broken.Singleton"

    def patched_get_class(cls: type, import_path: str) -> type | None:
        if import_path == bad_path:
            return _BrokenSingleton
        return None

    monkeypatch.setattr(SingletonRegistry, "_get_class", classmethod(patched_get_class))

    SingletonRegistry._entries.append(
        SingletonEntry(import_path=bad_path, cleanup_order=99)
    )

    # Must not raise
    errors = SingletonRegistry.reset_all()

    assert len(errors) == 1
    path, exc = errors[0]
    assert path == bad_path
    assert isinstance(exc, RuntimeError)


def test_class_cache_populated_after_get_class(clean_registry: None) -> None:
    """_get_class() populates _class_cache; second call is a cache hit."""
    assert _REAL_PATH not in SingletonRegistry._class_cache

    result1 = SingletonRegistry._get_class(_REAL_PATH)
    assert _REAL_PATH in SingletonRegistry._class_cache
    assert result1 is SingletonRegistry

    result2 = SingletonRegistry._get_class(_REAL_PATH)
    assert result2 is result1


def test_clear_removes_entries_and_cache(clean_registry: None) -> None:
    """clear() empties both _entries and _class_cache."""
    SingletonRegistry.register(_REAL_PATH, cleanup_order=77)
    SingletonRegistry._get_class(_REAL_PATH)

    assert len(SingletonRegistry._entries) > 0
    assert len(SingletonRegistry._class_cache) > 0

    SingletonRegistry.clear()

    assert SingletonRegistry._entries == []
    assert SingletonRegistry._class_cache == {}


# ---------------------------------------------------------------------------
# Group 2: DialogRecorder tests
# ---------------------------------------------------------------------------


def test_assert_shown_with_method_filter() -> None:
    """assert_shown filters by method name correctly."""
    recorder = DialogRecorder()
    recorder.calls.append({"method": "critical", "args": ("title", "message")})

    recorder.assert_shown("critical")  # should pass

    with pytest.raises(AssertionError):
        recorder.assert_shown("information")


def test_assert_shown_with_text_filter() -> None:
    """assert_shown filters by text_contains substring."""
    recorder = DialogRecorder()
    recorder.calls.append({"method": "warning", "args": ("title", "disk full error")})

    recorder.assert_shown(text_contains="disk full")  # should pass

    with pytest.raises(AssertionError):
        recorder.assert_shown(text_contains="network")


def test_assert_not_shown_passes_when_empty() -> None:
    """assert_not_shown passes when no calls were recorded."""
    recorder = DialogRecorder()
    recorder.assert_not_shown()  # should not raise


def test_assert_not_shown_fails_with_calls() -> None:
    """assert_not_shown raises AssertionError when calls exist."""
    recorder = DialogRecorder()
    recorder.calls.append({"method": "information", "args": ("t", "m")})

    with pytest.raises(AssertionError):
        recorder.assert_not_shown()


def test_set_return_value_overrides_default() -> None:
    """set_return_value overrides get_return_value for the configured method only."""
    recorder = DialogRecorder()
    recorder.set_return_value("question", 42)

    assert recorder.get_return_value("question", default=99) == 42
    assert recorder.get_return_value("information", default=99) == 99


# ---------------------------------------------------------------------------
# Group 3: Qt marker validation
# ---------------------------------------------------------------------------


def _file_has_runtime_pyside6_import(tree: ast.Module) -> bool:
    """Return True if the module imports PySide6 outside TYPE_CHECKING guards."""
    # Walk top-level body only, skipping TYPE_CHECKING blocks
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Direct module-level import
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("PySide6"):
                return True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("PySide6"):
                        return True
        elif isinstance(node, ast.If):
            # Skip `if TYPE_CHECKING:` blocks — these are not runtime imports
            test = node.test
            is_type_checking = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            )
            if not is_type_checking:
                # A non-TYPE_CHECKING `if` block at module level:
                # check if it contains PySide6 imports
                for child in ast.walk(node):
                    if isinstance(child, ast.ImportFrom) and child.module and child.module.startswith("PySide6"):
                        return True
                    if isinstance(child, ast.Import):
                        for alias in child.names:
                            if alias.name.startswith("PySide6"):
                                return True

    return False


def _file_has_qt_marker_or_qtbot(tree: ast.Module) -> bool:
    """Return True if the file uses @pytest.mark.qt or has qtbot parameter."""
    for node in ast.walk(tree):
        # Check for qtbot parameter in function signatures
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.args:
                if arg.arg == "qtbot":
                    return True

        # Check for pytestmark = [...pytest.mark.qt...]
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    return True

        # Check for @pytest.mark.qt decorator
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                decorator_str = ast.unparse(decorator)
                if "pytest.mark.qt" in decorator_str:
                    return True

    return False


def _file_has_test_items(tree: ast.Module) -> bool:
    """Return True if the file contains any test functions or test classes."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            return True
    return False


def test_all_pyside6_importing_tests_have_qt_marker_or_qtbot() -> None:
    """Test files with runtime PySide6 imports must use qtbot or @pytest.mark.qt."""
    tests_root = Path(__file__).parent.parent  # tests/
    offending: list[str] = []

    for test_file in sorted(tests_root.rglob("test_*.py")):
        # Skip this file itself
        if test_file.name == "test_fixture_infrastructure.py":
            continue

        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(test_file))
        except SyntaxError:
            continue

        # Skip helper modules that match test_*.py naming but contain no test items
        if not _file_has_test_items(tree):
            continue

        if not _file_has_runtime_pyside6_import(tree):
            continue

        if not _file_has_qt_marker_or_qtbot(tree):
            offending.append(str(test_file.relative_to(tests_root.parent)))

    assert not offending, (
        "The following test files import PySide6 at module level (outside TYPE_CHECKING) "
        "but have no qtbot parameter or @pytest.mark.qt decorator.\n"
        "Add `pytestmark = pytest.mark.qt` at the top, or use qtbot, "
        "or guard the import with `if TYPE_CHECKING:`:\n"
        + "\n".join(f"  {p}" for p in offending)
    )
