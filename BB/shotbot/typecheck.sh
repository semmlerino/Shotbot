#!/bin/bash
# Type checking script for shotbot

# Activate virtual environment
source venv/bin/activate

# Run basedpyright with stats
echo "Running basedpyright type checking..."
python -m basedpyright --stats

# Exit with the same code as basedpyright
exit $?