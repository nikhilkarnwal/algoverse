#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

RUNNING_ID="$(
  docker_command ps \
    --filter "name=^/${CARLA_DOCKER_NAME}$" \
    --format '{{.ID}}'
)"
if [[ -n "${RUNNING_ID}" ]]; then
  echo "CARLA container ${CARLA_DOCKER_NAME} is already running."
else
  OLD_ID="$(
    docker_command ps --all \
      --filter "name=^/${CARLA_DOCKER_NAME}$" \
      --format '{{.ID}}'
  )"
  if [[ -n "${OLD_ID}" ]]; then
    docker_command rm --force "${CARLA_DOCKER_NAME}" >/dev/null
  fi

  mkdir -p /tmp/.X11-unix
  echo "Starting CARLA 0.9.15 in a GPU-enabled off-screen container..."
  docker_command run \
    --detach \
    --rm \
    --name "${CARLA_DOCKER_NAME}" \
    --privileged \
    --gpus all \
    --network host \
    --volume /tmp/.X11-unix:/tmp/.X11-unix:rw \
    "${CARLA_DOCKER_IMAGE}" \
    /bin/bash ./CarlaUE4.sh \
    -RenderOffScreen \
    -nosound \
    -quality-level=Low \
    -ResX=640 \
    -ResY=360 \
    -carla-rpc-port="${CARLA_PORT}" \
    >/dev/null
fi

if "${PROJECT_ROOT}/scripts/ec2_run.sh" \
  python "${PROJECT_ROOT}/scripts/wait_for_carla.py"; then
  echo "CARLA is RPC-ready on ${CARLA_HOST}:${CARLA_PORT}."
  exit 0
fi

echo "CARLA did not become RPC-ready. Last container log lines:" >&2
docker_command logs --tail 80 "${CARLA_DOCKER_NAME}" >&2 || true
exit 1
