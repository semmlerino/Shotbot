#!/usr/bin/env python3
"""CLI test for ShotBot modules."""

from test_mock import MockShotModel


def test_shot_model():
    """Test the shot model functionality."""
    # Test mock model
    mock_model = MockShotModel()
    assert mock_model.refresh_shots()

    print(f"✓ Loaded {len(mock_model.shots)} mock shots")

    # Test shot properties
    for shot in mock_model.shots[:3]:
        print(f"\nShot: {shot.full_name}")
        print(f"  Show: {shot.show}")
        print(f"  Sequence: {shot.sequence}")
        print(f"  Shot: {shot.shot}")
        print(f"  Workspace: {shot.workspace_path}")
        print(f"  Thumbnail dir: {shot.thumbnail_dir}")

    # Test find by name
    shot = mock_model.find_shot_by_name("108_BQS_0010")
    assert shot is not None
    print(f"\n✓ Found shot by name: {shot.full_name}")

    # Test to_dict
    shot_dicts = mock_model.to_dict()
    assert len(shot_dicts) == 6
    print(f"✓ Converted {len(shot_dicts)} shots to dict format")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_shot_model()
