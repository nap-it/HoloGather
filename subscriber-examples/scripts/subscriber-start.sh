#!/bin/bash
set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
	echo "[subscriber-start] ERROR: ffmpeg is not available in PATH inside container" >&2
	echo "[subscriber-start] Rebuild image with: docker compose build hololens_subscriber" >&2
	exit 1
fi

python3 -u -m src.main --config configs/app_config.ini
