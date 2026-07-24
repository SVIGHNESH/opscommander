#!/usr/bin/env bash
# Convenience launcher for OpsCommander.
#
#   ./run.sh demo        run the seeded demo incidents (no deps)
#   ./run.sh test        run the test suite
#   ./run.sh api         start the FastAPI server on :8000
#   ./run.sh dashboard   start the Streamlit console on :8501
set -euo pipefail

cd "$(dirname "$0")"
CMD="${1:-demo}"

case "$CMD" in
  demo)
    python scripts/seed_incident.py
    ;;
  test)
    python -m pytest -q
    ;;
  api)
    export PYTHONPATH="src:${PYTHONPATH:-}"
    uvicorn opscommander.api.app:app --reload --port 8000
    ;;
  dashboard)
    streamlit run dashboard/app.py
    ;;
  *)
    echo "Usage: $0 {demo|test|api|dashboard}" >&2
    exit 1
    ;;
esac
