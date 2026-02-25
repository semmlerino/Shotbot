"""Determinism fixtures for reproducible test execution.

This module provides fixtures that ensure consistent, reproducible test behavior
by controlling random number generation. Use these fixtures when tests depend on
random values or when debugging flaky tests.

Test Ordering:
    pytest-randomly is installed and configured to shuffle test order to surface
    hidden test coupling. The seed is configured as --randomly-seed=last by default,
    which reproduces the previous run's order. To use a specific seed:

        pytest tests/ --randomly-seed=12345

    The seed used is printed at the start of each test run:
        "Using --randomly-seed=123456"

Random Values Within Tests:
    For controlling random values WITHIN a test (random.randint(), etc.),
    use the stable_random_seed fixture:

        @pytest.mark.usefixtures("stable_random_seed")
        def test_something_with_random():
            # Random values are now deterministic
            ...

        # Or request explicitly:
        def test_something(stable_random_seed):
            ...

NOTE: stable_random_seed is NOT autouse. Tests must explicitly request it
or use the marker to opt-in. This reduces overhead for tests that don't
need deterministic randomness.
"""

from __future__ import annotations

import random

import pytest


@pytest.fixture
def stable_random_seed() -> None:
    """Fix random seeds for reproducible tests.

    This fixture makes each test's random values deterministic while pytest-randomly
    still shuffles test ORDER to surface hidden test coupling.

    Use this when:
    - Tests use random.choice(), random.randint(), etc.
    - Tests use numpy random functions
    - You're debugging a flaky test that might have randomness issues

    Note: pytest-randomly handles test order randomization separately - this
    fixture only controls random values WITHIN tests, not test ordering.
    """
    random.seed(12345)

    try:
        import numpy as np

        np.random.seed(12345)
    except ImportError:
        pass  # numpy not installed
