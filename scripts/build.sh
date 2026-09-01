#!/bin/bash

# Go to the root directory of the project
# DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# cd "$DIR/.."

# Set variables
TAG="${TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-hololens_publisher}"
BASE_IMAGE="${BASE_IMAGE:-ubuntu:22.04@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc}"

# Build the Docker image with the architecture-specific tag
echo "Building Docker image for '${CONTAINER_NAME}:${TAG}'"
docker build --build-arg "BASE_IMAGE=${BASE_IMAGE}" -f Dockerfile -t "${CONTAINER_NAME}:${TAG}" .

# tag the image also as latest locally
#docker tag $GITLAB_REGISTRY$CONTAINER_NAME:$TAG $CONTAINER_NAME:$TAG
