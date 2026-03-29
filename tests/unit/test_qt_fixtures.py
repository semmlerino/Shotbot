"""Tests for qt_cleanup zombie detection behavior."""


def test_qt_cleanup_detects_new_zombies_in_test():
    """qt_cleanup should capture that get_zombie_metrics['created'] increased during a test."""
    from tests.fixtures.qt_fixtures import (
        _zombies_created_during,
    )

    fake_metrics_before = {"created": 5, "recovered": 1, "terminated": 0, "current": 2}
    fake_metrics_after  = {"created": 7, "recovered": 1, "terminated": 0, "current": 4}

    assert _zombies_created_during(fake_metrics_before, fake_metrics_after) == 2
