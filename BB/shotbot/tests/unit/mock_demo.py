#!/usr/bin/env python3
"""Mock test script for ShotBot development.

This creates mock shot data for testing without needing access
to the actual VFX environment.
"""

import sys

from shot_model import Shot, ShotModel


class MockShotModel(ShotModel):
    """Mock shot model for testing."""

    def refresh_shots(self) -> tuple[bool, bool]:
        """Create mock shots instead of running ws -sg."""
        # Create some mock shots
        self.shots = [
            Shot(
                show="ygsk",
                sequence="108_BQS",
                shot="0005",
                workspace_path="/shows/ygsk/shots/108_BQS/108_BQS_0005",
            ),
            Shot(
                show="ygsk",
                sequence="108_BQS",
                shot="0010",
                workspace_path="/shows/ygsk/shots/108_BQS/108_BQS_0010",
            ),
            Shot(
                show="ygsk",
                sequence="108_BQS",
                shot="0015",
                workspace_path="/shows/ygsk/shots/108_BQS/108_BQS_0015",
            ),
            Shot(
                show="ygsk",
                sequence="109_ABC",
                shot="0020",
                workspace_path="/shows/ygsk/shots/109_ABC/109_ABC_0020",
            ),
            Shot(
                show="ygsk",
                sequence="109_ABC",
                shot="0025",
                workspace_path="/shows/ygsk/shots/109_ABC/109_ABC_0025",
            ),
            Shot(
                show="proj2",
                sequence="201_XYZ",
                shot="0100",
                workspace_path="/shows/proj2/shots/201_XYZ/201_XYZ_0100",
            ),
        ]
        return True, True  # success=True, has_changes=True


def test_mock_shots():
    """Test the mock shot model."""
    from PySide6.QtWidgets import QApplication

    from main_window import MainWindow

    app = QApplication(sys.argv)

    # Create main window but override shot model
    window = MainWindow()

    # Replace with mock model
    window.shot_model = MockShotModel()
    window.shot_grid.shot_model = window.shot_model

    # Refresh with mock data
    window._refresh_shots()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    print("Running ShotBot with mock data...")
    print("This allows testing without access to the VFX environment.")
    test_mock_shots()
