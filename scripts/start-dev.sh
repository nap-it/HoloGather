#!/bin/bash

# Go to project directory
# DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# cd "$DIR/.."

TAG="latest"
CONTAINER_NAME="hololens_pubsub"
HOST_RECORDINGS_DIR="$(pwd)/recordings"

mkdir -p "$HOST_RECORDINGS_DIR"

# Run the container
set -x
docker run -it --rm \
  --network host \
  --ipc=host \
  --shm-size=512m \
  --ulimit memlock=268435456:268435456 \
  --cap-add IPC_LOCK \
  --name "${CONTAINER_NAME}"-dev \
  --mount type=bind,source="$(pwd)/src",target=/root/app/src \
  --mount type=bind,source="$(pwd)/libs",target=/root/app/libs \
  --mount type=bind,source="$(pwd)/configs",target=/root/app/configs \
  --mount type=bind,source="$HOST_RECORDINGS_DIR",target=/root/app/recordings \
  $CONTAINER_NAME:$TAG
set +x
