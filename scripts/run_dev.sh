#!/usr/bin/env bash
set -e

echo "Starting PRISM Agentic Code Intelligence development server..."

# Check Python environment
if ! command -v python &> /dev/null; then
    echo "Python could not be found"
    exit 1
fi

# Run backend tests first
python -m pytest backend/tests -v

# Start FastAPI backend server
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
