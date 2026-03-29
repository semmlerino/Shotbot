"""Tests for StartupOrchestrator."""

from __future__ import annotations

import pytest

from controllers.startup_orchestrator import StartupOrchestrator


@pytest.fixture
def mock_target(mocker):
    target = mocker.MagicMock()
    target.shot_model.shots = [mocker.MagicMock()]  # simulate cached shots present
    target.threede_scene_model.scenes = []
    target.refresh_coordinator = mocker.MagicMock()
    return target


@pytest.fixture
def non_pool(mocker):
    """A process pool that is NOT a ProcessPoolManager (skips session warming)."""
    return mocker.MagicMock(spec=[])


def test_startup_orchestrator_starts_background_refresh(mock_target, non_pool):
    """StartupOrchestrator.execute() must call shot_model.start_background_refresh()."""
    orchestrator = StartupOrchestrator(mock_target, non_pool)
    orchestrator.execute()

    mock_target.shot_model.start_background_refresh.assert_called_once()


def test_startup_uses_refresh_coordinator_not_private_methods(mock_target, non_pool):
    """StartupOrchestrator must call refresh_coordinator methods, not private ones."""
    orchestrator = StartupOrchestrator(mock_target, non_pool)
    orchestrator.execute()

    assert mock_target.refresh_coordinator.refresh_shot_display.called, (
        "Expected refresh_coordinator.refresh_shot_display() to be called"
    )
