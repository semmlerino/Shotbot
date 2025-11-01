"""Common test data and fixtures for shotbot tests."""

from unittest.mock import Mock

import pytest

from shot_model import Shot

# Test shot data
TEST_SHOTS = [
    Shot("testshow", "101_ABC", "0010", "/shows/testshow/shots/101_ABC/101_ABC_0010"),
    Shot("testshow", "101_ABC", "0020", "/shows/testshow/shots/101_ABC/101_ABC_0020"),
    Shot("testshow", "102_XYZ", "0030", "/shows/testshow/shots/102_XYZ/102_XYZ_0030"),
    Shot("othershow", "201_FOO", "0040", "/shows/othershow/shots/201_FOO/201_FOO_0040"),
]


@pytest.fixture
def test_shots():
    """Return a list of test shots."""
    return TEST_SHOTS.copy()


@pytest.fixture
def mock_shot_model(test_shots):
    """Create a mock shot model with test data."""
    model = Mock()
    model.shots = test_shots
    model.get_shot_by_index = (
        lambda idx: test_shots[idx] if 0 <= idx < len(test_shots) else None
    )
    model.find_shot_by_name = lambda name: next(
        (s for s in test_shots if s.full_name == name), None
    )
    return model


@pytest.fixture
def mock_shot_model_empty():
    """Create a mock shot model with no shots."""
    model = Mock()
    model.shots = []
    model.get_shot_by_index = lambda idx: None
    model.find_shot_by_name = lambda name: None
    return model
