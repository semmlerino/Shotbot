# BasedPyright Type Checking Guide for Claude Code

## Key Installation Issue: Use --no-deps

BasedPyright installation often fails due to `nodejs-wheel-binaries` dependency timeouts:

```bash
# Always use --no-deps to avoid timeout issues
pip install --no-deps basedpyright
```

## Troubleshooting "Command Not Found"

If `basedpyright: command not found` after installation:

```bash
# Alternative execution method
python -m basedpyright --help

# Find executable location
find $(python -m site --user-base) -name "basedpyright" 2>/dev/null
```

## Critical Configuration Notes

- **Always use `"basic"` mode initially** to avoid overwhelming error counts
- **`pythonPath` is deprecated** - use `venv` and `venvPath` instead

## High-Impact Type Safety Strategy

### Priority 1: Modernize Optional Syntax (25-35% warning reduction)
```python
# Replace deprecated Optional with modern | None syntax
# Remove Optional imports, use targeted replacements like:
# Optional[str] → str | None
```

### Priority 2: Fix Unused Call Results  
```python
# Explicitly assign unused returns to avoid warnings:
_ = self.button.clicked.connect(self.handler)
_ = QMessageBox.warning(parent, "Title", "Message")
```

### Priority 3: Add Class Attribute Annotations
```python
# Add explicit type annotations for class attributes:
def __init__(self, main_window: 'MainWindow') -> None:
    self.main_window: 'MainWindow' = main_window  # Not just = main_window
```

## Critical Pitfall: Large Error Counts

**Always start with "basic" mode** instead of "strict" to avoid thousands of overwhelming errors.

## Key Performance Insight

**Optional syntax modernization typically yields 25-35% warning reduction** - highest impact for effort invested.