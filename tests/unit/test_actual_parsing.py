#!/usr/bin/env python3
"""Test script to verify parsing with the actual ws -sg output from VFX environment."""

# Standard library imports
import sys
from pathlib import Path


# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Third-party imports
import pytest

# Local application imports
from config import Config
from optimized_shot_parser import OptimizedShotParser
from shot_model import Shot


# Mark Qt tests for serial execution in same worker (prevents Qt crashes)
pytestmark = [
    pytest.mark.unit,
    pytest.mark.qt,  # CRITICAL for parallel safety
]


@pytest.fixture
def actual_output() -> str:
    """The actual ws -sg output from the VFX environment."""
    shows_root = Config.SHOWS_ROOT
    return f"""workspace {shows_root}/gator/shots/012_DC/012_DC_1000
workspace {shows_root}/gator/shots/012_DC/012_DC_1070
workspace {shows_root}/gator/shots/012_DC/012_DC_1050
workspace {shows_root}/jack_ryan/shots/DB_271/DB_271_1760
workspace {shows_root}/jack_ryan/shots/FF_278/FF_278_4380
workspace {shows_root}/jack_ryan/shots/DA_280/DA_280_0280
workspace {shows_root}/jack_ryan/shots/DC_278/DC_278_0050
workspace {shows_root}/broken_eggs/shots/BRX_166/BRX_166_0010
workspace {shows_root}/broken_eggs/shots/BRX_166/BRX_166_0020
workspace {shows_root}/broken_eggs/shots/BRX_170/BRX_170_0100
workspace {shows_root}/broken_eggs/shots/BRX_070/BRX_070_0010
workspace {shows_root}/jack_ryan/shots/999_xx/999_xx_999"""


def test_parsing(actual_output: str) -> None:
    """Test the parsing with actual VFX output."""
    print("Testing shot parsing with actual VFX environment output")
    print("=" * 60)

    print(f"Config.SHOWS_ROOT: {Config.SHOWS_ROOT}")

    # Initialize parser
    parser = OptimizedShotParser()
    print(f"Parser regex pattern: {parser._ws_pattern.pattern}")
    print()

    lines = actual_output.strip().split("\n")
    successful_shots = []
    failed_lines = []

    for i, line in enumerate(lines, 1):
        print(f"Line {i}: {line}")

        # Test regex match
        match = parser._ws_pattern.search(line)
        if match:
            print(f"  ✅ Regex groups: {match.groups()}")

            # Test full parsing
            result = parser.parse_workspace_line(line)
            if result:
                print(
                    f"  ✅ Parse result: show={result.show}, sequence={result.sequence}, shot={result.shot}"
                )

                # Create Shot object
                shot = Shot(
                    show=result.show,
                    sequence=result.sequence,
                    shot=result.shot,
                    workspace_path=result.workspace_path,
                )

                print(f"  ✅ Shot object: full_name={shot.full_name}")
                successful_shots.append(shot)
                print()
            else:
                print("  ❌ Parse failed despite regex match")
                failed_lines.append(line)
                print()
        else:
            print("  ❌ No regex match")
            failed_lines.append(line)
            print()

    print("SUMMARY")
    print("=" * 30)
    print(f"Successful parses: {len(successful_shots)}")
    print(f"Failed parses: {len(failed_lines)}")

    if successful_shots:
        print("\nSuccessful shot objects:")
        for shot in successful_shots:
            print(
                f"  - {shot.full_name} (show={shot.show}, seq={shot.sequence}, shot={shot.shot})"
            )

    if failed_lines:
        print("\nFailed lines:")
        for line in failed_lines:
            print(f"  - {line}")

    # Assert instead of return
    assert len(successful_shots) == len(lines), (
        f"Only {len(successful_shots)}/{len(lines)} lines parsed successfully"
    )


def test_shot_item_model(qapp, actual_output: str) -> None:
    """Test ShotItemModel with parsed shots."""
    # Third-party imports
    from PySide6.QtCore import (
        Qt,
    )

    # Local application imports
    from shot_item_model import (
        ShotItemModel,
    )

    print("\nTesting ShotItemModel...")
    print("=" * 40)

    # Parse shots
    parser = OptimizedShotParser()
    lines = actual_output.strip().split("\n")
    shots = []

    for line in lines:
        result = parser.parse_workspace_line(line)
        if result:
            shot = Shot(
                show=result.show,
                sequence=result.sequence,
                shot=result.shot,
                workspace_path=result.workspace_path,
            )
            shots.append(shot)

    # Test model - QAbstractItemModel doesn't need qtbot (no widget cleanup needed)
    model = ShotItemModel()
    try:
        model.set_shots(shots)

        print(f"Model row count: {model.rowCount()}")
        print("\nDisplayRole data from model:")

        for i in range(model.rowCount()):
            index = model.index(i, 0)
            display_text = model.data(index, Qt.ItemDataRole.DisplayRole)
            print(f"  Row {i}: {display_text}")

        # Assert instead of return
        assert model.rowCount() > 0
    finally:
        # Explicit cleanup for QAbstractItemModel
        model.deleteLater()
        # Force event processing to ensure cleanup happens
        if qapp:
            qapp.processEvents()
            qapp.sendPostedEvents()


if __name__ == "__main__":
    print("VFX Environment Shot Parsing Test")
    print("=" * 50)

    # Test parsing
    parsing_success = test_parsing()

    # Test model
    model_success = test_shot_item_model()

    print(
        f"\nOVERALL RESULT: {'✅ SUCCESS' if parsing_success and model_success else '❌ FAILURE'}"
    )

    if not parsing_success:
        print("❌ Parsing failed - this explains why shot names don't appear!")
    elif not model_success:
        print("❌ Model failed - this explains why shot names don't appear!")
    else:
        print("✅ Both parsing and model work correctly")
        print("✅ The issue must be elsewhere in the UI pipeline")
