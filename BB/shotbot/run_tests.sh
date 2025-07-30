#!/bin/bash
# Run tests properly in WSL environment

# Activate virtual environment
source venv/bin/activate

# Run pytest with correct settings
python -m pytest tests/ "$@"