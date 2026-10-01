#!/usr/bin/env bash
# Run the HoloLens dataset validation dashboard.
#
# Usage:
#   ./run-dashboard.sh                 # serve on http://localhost:8080
#   ./run-dashboard.sh -p 9000         # serve on a different port
#   ./run-dashboard.sh -e              # (re)build data/ from the recordings, then serve
#   ./run-dashboard.sh -h              # this help
#
# Recordings location is read from config.json (recordings_path).
# Serving needs only Python 3; -e (extract) additionally needs `msgpack`.

set -euo pipefail
cd "$(dirname "$0")"

PORT=8080
EXTRACT=false
PY="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port)    PORT="$2"; shift 2 ;;
    -e|--extract) EXTRACT=true; shift ;;
    -h|--help)    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1  (try -h)" >&2; exit 1 ;;
  esac
done

if [[ "$EXTRACT" == true ]]; then
  echo "Rebuilding data/ from recordings..."
  "$PY" scripts/extract_dashboard_data.py
elif [[ ! -f data/index.json ]]; then
  echo "No data/index.json yet — building it from recordings..."
  "$PY" scripts/extract_dashboard_data.py
fi

exec "$PY" scripts/serve_dashboard.py --port "$PORT"
