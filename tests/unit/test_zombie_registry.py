

def test_zombie_terminate_age_respects_test_mode(monkeypatch):
    """In SHOTBOT_TEST_MODE, zombies should be reaped faster than 300s."""
    monkeypatch.setenv("SHOTBOT_TEST_MODE", "1")
    # Import after setting env so module-level constant re-reads env
    import importlib

    import workers.zombie_registry as zr
    importlib.reload(zr)
    assert zr._effective_terminate_age() <= 30
