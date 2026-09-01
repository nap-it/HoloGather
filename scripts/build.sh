#!/bin/bash
set -euo pipefail

# Run from the repository root even when invoked from another directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$SCRIPT_DIR/.."

# Set variables. Override these when publishing to a registry.
TAG="${TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-hololens_subscribers_examples}"

# Build the Docker image with a local tag.
echo "Building Docker image for '$CONTAINER_NAME:$TAG'"
docker build -f Dockerfile -t "$CONTAINER_NAME:$TAG" .

# Publishing is intentionally left to the caller; no registry credentials or
# organization-specific endpoints belong in this public example repository.
