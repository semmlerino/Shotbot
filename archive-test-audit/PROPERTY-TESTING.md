# Property-Based Testing with Hypothesis

## When to Use Property-Based Testing
- Path operations and validation
- Cache key generation
- Parsing functions
- Data transformations
- Invariants that must hold for all inputs

## ShotBot Property Test Templates

### Path Operations Template
```python
from hypothesis import given, strategies as st

# Shot path invariant testing
@given(st.from_regex(r"/shows/[a-z0-9_]+/[a-z0-9_]+/\d{4}", fullmatch=True))
def test_shot_path_roundtrip(path):
    """Any valid shot path should parse and reconstruct identically."""
    shot = Shot.from_path(path)
    assert shot.to_path() == path
    assert shot.show and shot.sequence and shot.shot

# Cache key invariants
@given(
    show=st.text(min_size=1, max_size=20, alphabet=st.characters(blacklist_characters="/")),
    seq=st.text(min_size=1, max_size=20, alphabet=st.characters(blacklist_characters="/")),
    shot=st.from_regex(r"\d{4}")
)
def test_cache_key_uniqueness(show, seq, shot):
    """Cache keys must be unique and reversible."""
    key1 = CacheManager.generate_key(show, seq, shot)
    key2 = CacheManager.generate_key(show, seq, shot)
    assert key1 == key2  # Deterministic
    assert "/" not in key1  # Safe for filesystem
```

### Workspace Command Parsing Template
```python
@given(st.lists(
    st.tuples(
        st.from_regex(r"[A-Z]{2}", fullmatch=True),  # Show code
        st.from_regex(r"seq\d{3}", fullmatch=True),  # Sequence
        st.from_regex(r"\d{4}", fullmatch=True)      # Shot number
    ),
    min_size=0,
    max_size=100
))
def test_workspace_parsing_consistency(shot_data):
    """Workspace output parsing should handle any valid format."""
    # Generate mock workspace output
    ws_output = "\n".join(f"workspace /shows/{s}/{sq}/{sh}" 
                          for s, sq, sh in shot_data)
    
    shots = ShotModel._parse_workspace_output(ws_output)
    assert len(shots) == len(shot_data)
    for shot, (show, seq, shot_num) in zip(shots, shot_data):
        assert shot.show == show
        assert shot.sequence == seq
        assert shot.shot == shot_num
```