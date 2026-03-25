"""Tests for StartupOrchestrator."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from controllers.startup_orchestrator import StartupOrchestrator


@pytest.fixture
def mock_target():
    target = MagicMock()
    target.shot_model.shots = [MagicMock()]  # simulate cached shots present
    target.threede_scene_model.scenes = []
    target.refresh_coordinator = MagicMock()
    return target


@pytest.fixture
def non_pool():
    """A process pool that is NOT a ProcessPoolManager (skips session warming)."""
    return MagicMock(spec=[])


def test_startup_uses_refresh_coordinator_not_private_methods(mock_target, non_pool):
    """StartupOrchestrator must call refresh_coordinator methods, not private ones."""
    orchestrator = StartupOrchestrator(mock_target, non_pool)
    orchestrator.execute()

    assert mock_target.refresh_coordinator.refresh_shot_display.called, (
        "Expected refresh_coordinator.refresh_shot_display() to be called"
    )
