#!/usr/bin/env python3
"""Run Shotbot with monitoring."""

# Standard library imports
import signal
import sys
from pathlib import Path
from types import FrameType


# Add the shotbot directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Local application imports
# Import shotbot main after path setup
from shotbot import main


print("Starting Shotbot...")
print("Press Ctrl+C to stop")


# Set up a signal handler for clean shutdown
def signal_handler(_sig: int, _frame: FrameType | None) -> None:
    print("\nShutting down Shotbot...")
    sys.exit(0)


_ = signal.signal(signal.SIGINT, signal_handler)

# Run main
try:
    main()
except Exception as e:
    print(f"Error: {e}")
    # Standard library imports
    import traceback

    traceback.print_exc()
    sys.exit(1)
