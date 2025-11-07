"""Integration tests for single source of truth refactoring.

This test suite verifies that LauncherController is the sole owner of
scene/shot context state, with proper mutual exclusivity and delegation.
"""

from __future__ import annotations

from typing import Any

import pytest

from controllers.launcher_controller import LauncherController
from controllers.threede_controller import ThreeDEController
from shot_model import Shot
from threede_scene_model import ThreeDEScene

pytestmark = [
    pytest.mark.integration,  # CRITICAL: Qt state must be serialized
]


@pytest.fixture
def sample_shot() -> Shot:
    """Create a sample shot for testing."""
    return Shot(
        show="test_show",
        sequence="seq001",
        shot="shot001",
        workspace_path="/fake/workspace/test_show/seq001/shot001",
    )


@pytest.fixture
def sample_scene() -> ThreeDEScene:
    """Create a sample 3DE scene for testing."""
    return ThreeDEScene(
        show="test_show",
        sequence="seq001",
        shot="shot001",
        user="artist1",
        plate="main",
        scene_path="/fake/workspace/test_show/seq001/shot001/3de/artist1/scene_v001.3de",
        workspace_path="/fake/workspace/test_show/seq001/shot001",
    )


@pytest.fixture
def another_scene() -> ThreeDEScene:
    """Create another sample 3DE scene for testing."""
    return ThreeDEScene(
        show="test_show",
        sequence="seq002",
        shot="shot002",
        user="artist2",
        plate="alt",
        scene_path="/fake/workspace/test_show/seq002/shot002/3de/artist2/scene_v002.3de",
        workspace_path="/fake/workspace/test_show/seq002/shot002",
    )


class TestLauncherControllerSingleSourceOfTruth:
    """Test that LauncherController is the single source of truth."""

    def test_initial_state_is_none(self, launcher_controller_target: Any) -> None:
        """Test that initial state has no scene or shot selected."""
        controller = LauncherController(launcher_controller_target)

        assert controller.current_scene is None
        assert controller.current_shot is None

    def test_set_scene_stores_in_controller(
        self, launcher_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that setting scene stores it in launcher controller."""
        controller = LauncherController(launcher_controller_target)

        controller.set_current_scene(sample_scene)

        assert controller.current_scene == sample_scene
        assert controller.current_scene.full_name == "seq001_shot001"

    def test_set_shot_stores_in_controller(
        self, launcher_controller_target: Any, sample_shot: Shot
    ) -> None:
        """Test that setting shot stores it in launcher controller."""
        controller = LauncherController(launcher_controller_target)

        controller.set_current_shot(sample_shot)

        assert controller.current_shot == sample_shot
        assert controller.current_shot.full_name == "seq001_shot001"

    def test_properties_are_read_only(
        self, launcher_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that current_scene and current_shot properties are read-only."""
        controller = LauncherController(launcher_controller_target)

        # Properties should not be settable
        with pytest.raises(AttributeError):
            controller.current_scene = sample_scene  # type: ignore[misc]

        with pytest.raises(AttributeError):
            controller.current_shot = None  # type: ignore[misc]


class TestMutualExclusivity:
    """Test mutual exclusivity between scene and shot context."""

    def test_setting_scene_clears_shot(
        self,
        launcher_controller_target: Any,
        sample_shot: Shot,
        sample_scene: ThreeDEScene,
    ) -> None:
        """Test that setting a scene automatically clears the shot."""
        controller = LauncherController(launcher_controller_target)

        # Set shot first
        controller.set_current_shot(sample_shot)
        assert controller.current_shot == sample_shot
        assert controller.current_scene is None

        # Set scene - should clear shot
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene
        assert controller.current_shot is None, (
            "Shot should be cleared when scene is set"
        )

    def test_setting_shot_clears_scene(
        self,
        launcher_controller_target: Any,
        sample_shot: Shot,
        sample_scene: ThreeDEScene,
    ) -> None:
        """Test that setting a shot automatically clears the scene."""
        controller = LauncherController(launcher_controller_target)

        # Set scene first
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene
        assert controller.current_shot is None

        # Set shot - should clear scene
        controller.set_current_shot(sample_shot)
        assert controller.current_shot == sample_shot
        assert controller.current_scene is None, (
            "Scene should be cleared when shot is set"
        )

    def test_clearing_shot_does_not_set_scene(
        self, launcher_controller_target: Any
    ) -> None:
        """Test that clearing shot (None) doesn't affect scene."""
        controller = LauncherController(launcher_controller_target)

        # Both are None initially
        assert controller.current_shot is None
        assert controller.current_scene is None

        # Clear shot (set to None)
        controller.set_current_shot(None)

        # Scene should still be None
        assert controller.current_scene is None
        assert controller.current_shot is None

    def test_clearing_scene_does_not_set_shot(
        self, launcher_controller_target: Any
    ) -> None:
        """Test that clearing scene (None) doesn't affect shot."""
        controller = LauncherController(launcher_controller_target)

        # Both are None initially
        assert controller.current_shot is None
        assert controller.current_scene is None

        # Clear scene (set to None)
        controller.set_current_scene(None)

        # Shot should still be None
        assert controller.current_shot is None
        assert controller.current_scene is None

    def test_alternating_scene_and_shot_maintains_exclusivity(
        self,
        launcher_controller_target: Any,
        sample_shot: Shot,
        sample_scene: ThreeDEScene,
        another_scene: ThreeDEScene,
    ) -> None:
        """Test that alternating between scenes and shots maintains exclusivity."""
        controller = LauncherController(launcher_controller_target)

        # Set scene 1
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene
        assert controller.current_shot is None

        # Set shot - clears scene
        controller.set_current_shot(sample_shot)
        assert controller.current_shot == sample_shot
        assert controller.current_scene is None

        # Set scene 2 - clears shot
        controller.set_current_scene(another_scene)
        assert controller.current_scene == another_scene
        assert controller.current_shot is None

        # Clear scene
        controller.set_current_scene(None)
        assert controller.current_scene is None
        assert controller.current_shot is None


class TestThreeDEControllerDelegation:
    """Test that ThreeDEController properly delegates to LauncherController."""

    def test_threede_controller_delegates_to_launcher(
        self, threede_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that ThreeDEController.current_scene delegates to launcher_controller."""
        # ThreeDEController reads from launcher_controller.current_scene
        threede_controller_target.launcher_controller.set_current_scene(sample_scene)

        threede_controller = ThreeDEController(threede_controller_target)

        # ThreeDEController.current_scene should return the same value
        assert threede_controller.current_scene == sample_scene
        assert (
            threede_controller.current_scene
            == threede_controller_target.launcher_controller.current_scene
        )

    def test_on_scene_selected_updates_launcher_controller(
        self, threede_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that on_scene_selected updates launcher_controller state."""
        threede_controller = ThreeDEController(threede_controller_target)

        # Initially no scene
        assert threede_controller_target.launcher_controller.current_scene is None

        # Select scene
        threede_controller.on_scene_selected(sample_scene)

        # LauncherController should have the scene
        assert (
            threede_controller_target.launcher_controller.current_scene == sample_scene
        )
        assert threede_controller.current_scene == sample_scene

    def test_on_scene_selected_clears_shot_via_mutual_exclusivity(
        self,
        threede_controller_target: Any,
        sample_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that selecting scene clears shot through mutual exclusivity."""
        threede_controller = ThreeDEController(threede_controller_target)

        # Set shot first
        threede_controller_target.launcher_controller.set_current_shot(sample_shot)
        assert threede_controller_target.launcher_controller.current_shot == sample_shot

        # Select scene
        threede_controller.on_scene_selected(sample_scene)

        # Shot should be cleared automatically
        assert threede_controller_target.launcher_controller.current_shot is None
        assert (
            threede_controller_target.launcher_controller.current_scene == sample_scene
        )


class TestFixedBugScenario:
    """Test the specific bug that was fixed: scene selection → button click."""

    def test_scene_selection_then_button_click_works(
        self, launcher_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that selecting a scene then clicking button has proper context.

        This is the exact bug that was fixed:
        1. User selects scene in "Other 3DE Scenes" tab
        2. User clicks "Launch 3de" button in launcher panel
        3. Before fix: "No shot selected" error
        4. After fix: Scene context is available
        """
        controller = LauncherController(launcher_controller_target)

        # Step 1: User selects scene (signal handler is called)
        controller.set_current_scene(sample_scene)

        # Step 2: Verify context is set
        assert controller.current_scene == sample_scene, "Scene context should be set"
        assert controller.current_scene.full_name == "seq001_shot001"

        # Step 3: User clicks button - launch_app() will check _current_scene
        # The check `if self._current_scene:` should pass
        assert controller._current_scene is not None, (
            "Private _current_scene should not be None"
        )
        assert controller._current_scene == sample_scene

    def test_multiple_scene_selections_update_context(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        another_scene: ThreeDEScene,
    ) -> None:
        """Test that selecting different scenes updates context correctly."""
        controller = LauncherController(launcher_controller_target)

        # Select first scene
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene

        # Select second scene - should replace first
        controller.set_current_scene(another_scene)
        assert controller.current_scene == another_scene
        assert controller.current_scene != sample_scene

    def test_scene_context_available_in_launch_app(
        self, launcher_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that scene context is available when launch_app() is called."""
        controller = LauncherController(launcher_controller_target)

        # Set scene context
        controller.set_current_scene(sample_scene)

        # Simulate what launch_app() does
        if controller._current_scene:
            # This branch should be taken
            scene_from_context = controller._current_scene
            assert scene_from_context == sample_scene
            assert scene_from_context.full_name == "seq001_shot001"
        else:
            # This should NOT happen
            pytest.fail("Scene context was not available - bug still exists!")


class TestTabSwitchingBehavior:
    """Test context behavior when switching between tabs."""

    def test_switching_from_scene_tab_to_shot_tab_clears_scene(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that switching from scene tab to shot tab updates context."""
        controller = LauncherController(launcher_controller_target)

        # User is on "Other 3DE Scenes" tab and selects a scene
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene

        # User switches to "My Shots" tab and selects a shot
        controller.set_current_shot(sample_shot)

        # Scene should be cleared (mutual exclusivity)
        assert controller.current_scene is None
        assert controller.current_shot == sample_shot

    def test_switching_from_shot_tab_to_scene_tab_clears_shot(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that switching from shot tab to scene tab updates context."""
        controller = LauncherController(launcher_controller_target)

        # User is on "My Shots" tab and selects a shot
        controller.set_current_shot(sample_shot)
        assert controller.current_shot == sample_shot

        # User switches to "Other 3DE Scenes" tab and selects a scene
        controller.set_current_scene(sample_scene)

        # Shot should be cleared (mutual exclusivity)
        assert controller.current_shot is None
        assert controller.current_scene == sample_scene

    def test_deselecting_in_one_tab_clears_context(
        self, launcher_controller_target: Any, sample_scene: ThreeDEScene
    ) -> None:
        """Test that deselecting (setting to None) clears context."""
        controller = LauncherController(launcher_controller_target)

        # Select scene
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene

        # Deselect (user clicks empty area or switches tabs)
        controller.set_current_scene(None)
        assert controller.current_scene is None
        assert controller.current_shot is None


class TestArchitectureInvariants:
    """Test architectural invariants of the single source of truth design."""

    def test_only_one_context_active_at_a_time(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that only one context (scene OR shot, never both) is active."""
        controller = LauncherController(launcher_controller_target)

        # Set scene
        controller.set_current_scene(sample_scene)
        assert controller.current_scene is not None
        assert controller.current_shot is None

        # Set shot
        controller.set_current_shot(sample_shot)
        assert controller.current_shot is not None
        assert controller.current_scene is None

        # Clear shot
        controller.set_current_shot(None)
        assert controller.current_shot is None
        assert controller.current_scene is None

    def test_context_state_is_queryable(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that any code can query current context state."""
        controller = LauncherController(launcher_controller_target)

        # Initially no context
        assert controller.current_scene is None
        assert controller.current_shot is None

        # Set scene - everyone can see it
        controller.set_current_scene(sample_scene)
        assert controller.current_scene == sample_scene

        # Set shot - everyone can see the change
        controller.set_current_shot(sample_shot)
        assert controller.current_shot == sample_shot
        assert controller.current_scene is None

    def test_no_stale_state_possible(
        self,
        launcher_controller_target: Any,
        sample_scene: ThreeDEScene,
        another_scene: ThreeDEScene,
        sample_shot: Shot,
    ) -> None:
        """Test that stale state cannot exist (single source of truth guarantee)."""
        controller = LauncherController(launcher_controller_target)

        # Rapidly change context
        controller.set_current_scene(sample_scene)
        controller.set_current_shot(sample_shot)
        controller.set_current_scene(another_scene)
        controller.set_current_scene(None)
        controller.set_current_shot(sample_shot)

        # Final state should be deterministic
        assert controller.current_shot == sample_shot
        assert controller.current_scene is None

        # No other code can have stale references
        # (they all query the same controller)
