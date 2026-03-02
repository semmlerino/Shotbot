"""Tests for StartupCoordinator and SessionWarmer."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from startup_coordinator import SessionWarmer, StartupCoordinator


pytestmark = [
    pytest.mark.unit,
]



# ============================================================================
# Helpers
# ============================================================================


def _make_coordinator(
    *,
    shot_model: Mock | None = None,
    threede_scene_model: Mock | None = None,
    threede_item_model: Mock | None = None,
    previous_shots_model: Mock | None = None,
    cache_manager: Mock | None = None,
    refresh_orchestrator: Mock | None = None,
    process_pool: Mock | None = None,
    threede_controller: Mock | None = None,
    shot_grid: Mock | None = None,
    threede_shot_grid: Mock | None = None,
    update_status: MagicMock | None = None,
    last_selected_shot_name: str | None = None,
    refresh_shots: MagicMock | None = None,
    refresh_shot_display: MagicMock | None = None,
) -> StartupCoordinator:
    """Build a StartupCoordinator with sensible mock defaults.

    When a mock is provided, it is used as-is (caller's setup is preserved).
    Default mocks are only created when a dependency is omitted.
    """
    if shot_model is None:
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

    if threede_scene_model is None:
        threede_scene_model = Mock()
        threede_scene_model.scenes = []

    if cache_manager is None:
        cache_manager = Mock()
        cache_manager.has_valid_threede_cache = Mock(return_value=True)

    return StartupCoordinator(
        shot_model=shot_model,
        threede_scene_model=threede_scene_model,
        threede_item_model=threede_item_model or Mock(),
        previous_shots_model=previous_shots_model or Mock(),
        cache_manager=cache_manager,
        refresh_orchestrator=refresh_orchestrator or Mock(),
        process_pool=process_pool or Mock(),
        threede_controller=threede_controller or Mock(),
        shot_grid=shot_grid or Mock(),
        threede_shot_grid=threede_shot_grid or Mock(),
        update_status=update_status or MagicMock(),
        last_selected_shot_name=last_selected_shot_name,
        refresh_shots=refresh_shots or MagicMock(),
        refresh_shot_display=refresh_shot_display or MagicMock(),
    )


# ============================================================================
# SessionWarmer Tests
# ============================================================================


class TestSessionWarmer:
    """Tests for the SessionWarmer background thread."""

    def test_do_work_executes_warming_command(self) -> None:
        """SessionWarmer calls execute_workspace_command to warm the session."""
        mock_pool = Mock()
        mock_pool.execute_workspace_command = Mock(return_value="warming")

        warmer = SessionWarmer(mock_pool)
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_called_once()
        call_args = mock_pool.execute_workspace_command.call_args
        assert call_args[0][0] == "echo warming"

    def test_do_work_stops_early_if_should_stop(self) -> None:
        """SessionWarmer skips the command when should_stop() returns True."""
        mock_pool = Mock()

        warmer = SessionWarmer(mock_pool)
        warmer.request_stop()  # Signal stop before work starts
        warmer.do_work()

        mock_pool.execute_workspace_command.assert_not_called()

    def test_do_work_swallows_exception_without_raising(self) -> None:
        """SessionWarmer does not propagate exceptions from the warming command."""
        mock_pool = Mock()
        mock_pool.execute_workspace_command = Mock(
            side_effect=RuntimeError("subprocess failed")
        )

        warmer = SessionWarmer(mock_pool)
        # Should not raise
        warmer.do_work()


# ============================================================================
# StartupCoordinator — Session Warming
# ============================================================================


class TestStartupCoordinatorSessionWarming:
    """Tests for session warming behavior in StartupCoordinator."""

    def test_session_warmer_started_for_process_pool_manager(self) -> None:
        """SessionWarmer is started when process_pool is a ProcessPoolManager."""
        from process_pool_manager import ProcessPoolManager

        mock_pool = Mock(spec=ProcessPoolManager)

        with patch("startup_coordinator.SessionWarmer") as mock_warmer_cls:
            mock_warmer_instance = Mock()
            mock_warmer_cls.return_value = mock_warmer_instance

            coordinator = _make_coordinator(process_pool=mock_pool)
            result = coordinator.perform_initial_load()

        mock_warmer_cls.assert_called_once_with(mock_pool)
        mock_warmer_instance.start.assert_called_once()
        assert result is mock_warmer_instance

    def test_session_warmer_not_started_for_test_double(self) -> None:
        """SessionWarmer is NOT started for a plain Mock process pool."""
        mock_pool = Mock()  # Not a ProcessPoolManager instance

        with patch("startup_coordinator.SessionWarmer") as mock_warmer_cls:
            coordinator = _make_coordinator(process_pool=mock_pool)
            result = coordinator.perform_initial_load()

        mock_warmer_cls.assert_not_called()
        assert result is None


# ============================================================================
# StartupCoordinator — 4-Case Decision Table
# ============================================================================


class TestStartupCoordinatorDecisionTable:
    """Tests for the 4-case decision table in perform_initial_load."""

    def test_case_cached_shots_and_scenes(self) -> None:
        """Case: cached shots + cached scenes → display both, schedule refresh."""
        shot1 = Mock()
        shot2 = Mock()
        scene1 = Mock()

        shot_model = Mock()
        shot_model.shots = [shot1, shot2]
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        threede_scene_model = Mock()
        threede_scene_model.scenes = [scene1]

        threede_item_model = Mock()
        threede_shot_grid = Mock()
        update_status = MagicMock()
        refresh_shots = MagicMock()
        refresh_shot_display = MagicMock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            threede_scene_model=threede_scene_model,
            threede_item_model=threede_item_model,
            threede_shot_grid=threede_shot_grid,
            update_status=update_status,
            refresh_shots=refresh_shots,
            refresh_shot_display=refresh_shot_display,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        # Should display shots and scenes
        refresh_shot_display.assert_called_once()
        threede_item_model.set_scenes.assert_called_once_with(threede_scene_model.scenes)
        threede_shot_grid.populate_show_filter.assert_called_once_with(threede_scene_model)

        # Status should mention both
        update_status.assert_called()
        status_msg = update_status.call_args[0][0]
        assert "shots" in status_msg
        assert "3DE scenes" in status_msg

        # Should schedule a background refresh
        mock_timer_cls.singleShot.assert_any_call(500, refresh_shots)

    def test_case_cached_shots_only(self) -> None:
        """Case: cached shots only → display shots, schedule background refresh."""
        shot1 = Mock()

        shot_model = Mock()
        shot_model.shots = [shot1]
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        threede_scene_model = Mock()
        threede_scene_model.scenes = []  # No cached scenes

        threede_item_model = Mock()
        update_status = MagicMock()
        refresh_shots = MagicMock()
        refresh_shot_display = MagicMock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            threede_scene_model=threede_scene_model,
            threede_item_model=threede_item_model,
            update_status=update_status,
            refresh_shots=refresh_shots,
            refresh_shot_display=refresh_shot_display,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        # Should display shots but not 3DE scenes
        refresh_shot_display.assert_called_once()
        threede_item_model.set_scenes.assert_not_called()

        # Status should mention shots only
        update_status.assert_called()
        status_msg = update_status.call_args[0][0]
        assert "shots" in status_msg
        assert "3DE scenes" not in status_msg

        # Should schedule a background refresh
        mock_timer_cls.singleShot.assert_any_call(500, refresh_shots)

    def test_case_cached_scenes_only(self) -> None:
        """Case: cached scenes only → display scenes, no shot refresh scheduled."""
        scene1 = Mock()

        shot_model = Mock()
        shot_model.shots = []  # No cached shots
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        threede_scene_model = Mock()
        threede_scene_model.scenes = [scene1]

        threede_item_model = Mock()
        threede_shot_grid = Mock()
        update_status = MagicMock()
        refresh_shots = MagicMock()
        refresh_shot_display = MagicMock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            threede_scene_model=threede_scene_model,
            threede_item_model=threede_item_model,
            threede_shot_grid=threede_shot_grid,
            update_status=update_status,
            refresh_shots=refresh_shots,
            refresh_shot_display=refresh_shot_display,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        # Should NOT display shots (no cached shots)
        refresh_shot_display.assert_not_called()

        # Should display 3DE scenes
        threede_item_model.set_scenes.assert_called_once_with(threede_scene_model.scenes)
        threede_shot_grid.populate_show_filter.assert_called_once_with(threede_scene_model)

        # Status should mention scenes only
        update_status.assert_called()
        status_msg = update_status.call_args[0][0]
        assert "3DE scenes" in status_msg

        # Should NOT schedule a shot background refresh
        for call in mock_timer_cls.singleShot.call_args_list:
            assert call[0][1] is not refresh_shots, (
                "refresh_shots should not be scheduled when only scenes cached"
            )

    def test_case_no_cache(self) -> None:
        """Case: no cache → show loading status, no refresh scheduled."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        threede_scene_model = Mock()
        threede_scene_model.scenes = []

        threede_item_model = Mock()
        update_status = MagicMock()
        refresh_shots = MagicMock()
        refresh_shot_display = MagicMock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            threede_scene_model=threede_scene_model,
            threede_item_model=threede_item_model,
            update_status=update_status,
            refresh_shots=refresh_shots,
            refresh_shot_display=refresh_shot_display,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        # No display calls
        refresh_shot_display.assert_not_called()
        threede_item_model.set_scenes.assert_not_called()

        # Status should show loading message
        update_status.assert_called()
        status_msg = update_status.call_args[0][0]
        assert "Loading" in status_msg

        # Should NOT schedule a shot background refresh
        for call in mock_timer_cls.singleShot.call_args_list:
            assert call[0][1] is not refresh_shots, (
                "refresh_shots should not be scheduled when no cache"
            )


# ============================================================================
# StartupCoordinator — Cache Fallback Path
# ============================================================================


class TestStartupCoordinatorCacheFallback:
    """Tests for the explicit cache-load fallback when initial shots are empty."""

    def test_try_load_from_cache_called_when_no_initial_shots(self) -> None:
        """try_load_from_cache is called when shot_model.shots is empty."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        coordinator = _make_coordinator(shot_model=shot_model)

        with patch("startup_coordinator.QTimer"):
            coordinator.perform_initial_load()

        shot_model.try_load_from_cache.assert_called_once()

    def test_display_shown_when_cache_fallback_succeeds(self) -> None:
        """refresh_shot_display is called when try_load_from_cache returns True."""
        shot1 = Mock()

        shot_model = Mock()
        shot_model.shots = []

        def _load_side_effect() -> bool:
            shot_model.shots = [shot1]  # Simulate loading
            return True

        shot_model.try_load_from_cache = Mock(side_effect=_load_side_effect)
        shot_model.find_shot_by_name = Mock(return_value=None)

        refresh_shot_display = MagicMock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            refresh_shot_display=refresh_shot_display,
        )

        with patch("startup_coordinator.QTimer"):
            coordinator.perform_initial_load()

        refresh_shot_display.assert_called_once()


# ============================================================================
# StartupCoordinator — Last Selected Shot Restoration
# ============================================================================


class TestStartupCoordinatorShotRestoration:
    """Tests for last-selected-shot restoration."""

    def test_restores_last_selected_shot_when_found(self) -> None:
        """select_shot_by_name is called when the last shot is found in the model."""
        mock_shot = Mock()
        mock_shot.full_name = "SHOW/SEQ/SH010"

        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=True)
        shot_model.find_shot_by_name = Mock(return_value=mock_shot)

        shot_grid = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            shot_grid=shot_grid,
            last_selected_shot_name="SHOW/SEQ/SH010",
        )

        with patch("startup_coordinator.QTimer"):
            coordinator.perform_initial_load()

        shot_model.find_shot_by_name.assert_called_once_with("SHOW/SEQ/SH010")
        shot_grid.select_shot_by_name.assert_called_once_with("SHOW/SEQ/SH010")

    def test_no_restore_when_shot_not_found(self) -> None:
        """select_shot_by_name is not called when the shot can't be found."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=True)
        shot_model.find_shot_by_name = Mock(return_value=None)  # Not found

        shot_grid = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            shot_grid=shot_grid,
            last_selected_shot_name="MISSING/SH010",
        )

        with patch("startup_coordinator.QTimer"):
            coordinator.perform_initial_load()

        shot_grid.select_shot_by_name.assert_not_called()

    def test_no_restore_when_last_selected_is_none(self) -> None:
        """select_shot_by_name is not called when last_selected_shot_name is None."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=True)
        shot_model.find_shot_by_name = Mock(return_value=None)

        shot_grid = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            shot_grid=shot_grid,
            last_selected_shot_name=None,
        )

        with patch("startup_coordinator.QTimer"):
            coordinator.perform_initial_load()

        shot_model.find_shot_by_name.assert_not_called()
        shot_grid.select_shot_by_name.assert_not_called()


# ============================================================================
# StartupCoordinator — Previous Shots Refresh
# ============================================================================


class TestStartupCoordinatorPreviousShotsRefresh:
    """Tests for previous shots refresh scheduling."""

    def test_previous_shots_refresh_scheduled_when_shots_loaded(self) -> None:
        """previous_shots_model.refresh_shots is scheduled when shots are present."""
        shot1 = Mock()

        shot_model = Mock()
        shot_model.shots = [shot1]
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        previous_shots_model = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            previous_shots_model=previous_shots_model,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        mock_timer_cls.singleShot.assert_any_call(
            100, previous_shots_model.refresh_shots
        )

    def test_previous_shots_refresh_not_scheduled_when_no_shots(self) -> None:
        """previous_shots_model.refresh_shots is NOT scheduled when no shots."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        previous_shots_model = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            previous_shots_model=previous_shots_model,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        # Verify refresh_shots from previous_shots_model was not scheduled
        for call in mock_timer_cls.singleShot.call_args_list:
            assert call[0][1] is not previous_shots_model.refresh_shots, (
                "previous_shots refresh should not be scheduled when no shots"
            )


# ============================================================================
# StartupCoordinator — 3DE Discovery
# ============================================================================


class TestStartupCoordinator3DEDiscovery:
    """Tests for 3DE scene discovery scheduling."""

    def test_threede_discovery_started_when_shots_cached_and_cache_invalid(
        self,
    ) -> None:
        """3DE discovery is triggered when shots are cached and 3DE cache is invalid."""
        shot1 = Mock()

        shot_model = Mock()
        shot_model.shots = [shot1]
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        cache_manager = Mock()
        cache_manager.has_valid_threede_cache = Mock(return_value=False)

        threede_controller = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            cache_manager=cache_manager,
            threede_controller=threede_controller,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        mock_timer_cls.singleShot.assert_any_call(
            100, threede_controller.refresh_threede_scenes
        )

    def test_threede_discovery_skipped_when_cache_valid(self) -> None:
        """3DE discovery is NOT triggered when 3DE cache is valid."""
        shot1 = Mock()

        shot_model = Mock()
        shot_model.shots = [shot1]
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        cache_manager = Mock()
        cache_manager.has_valid_threede_cache = Mock(return_value=True)

        threede_controller = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            cache_manager=cache_manager,
            threede_controller=threede_controller,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        for call in mock_timer_cls.singleShot.call_args_list:
            assert call[0][1] is not threede_controller.refresh_threede_scenes, (
                "3DE discovery should not be scheduled when cache is valid"
            )

    def test_threede_discovery_skipped_when_no_shots(self) -> None:
        """3DE discovery is NOT triggered when no shots are cached."""
        shot_model = Mock()
        shot_model.shots = []
        shot_model.try_load_from_cache = Mock(return_value=False)
        shot_model.find_shot_by_name = Mock(return_value=None)

        cache_manager = Mock()
        cache_manager.has_valid_threede_cache = Mock(return_value=False)

        threede_controller = Mock()

        coordinator = _make_coordinator(
            shot_model=shot_model,
            cache_manager=cache_manager,
            threede_controller=threede_controller,
        )

        with patch("startup_coordinator.QTimer") as mock_timer_cls:
            coordinator.perform_initial_load()

        for call in mock_timer_cls.singleShot.call_args_list:
            assert call[0][1] is not threede_controller.refresh_threede_scenes, (
                "3DE discovery should not be scheduled when no shots cached"
            )
