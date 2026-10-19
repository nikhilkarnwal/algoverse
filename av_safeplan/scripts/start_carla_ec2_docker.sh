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
    --name "${CARLA_DOCKER_NAME}" \
    --user "${AV_SAFEPLAN_CARLA_RUNTIME_USER:-carla}" \
    --entrypoint /bin/bash \
    --privileged \
    --gpus all \
    --network host \
    --volume /tmp/.X11-unix:/tmp/.X11-unix:rw \
    "${CARLA_DOCKER_IMAGE}" \
    ./CarlaUE4.sh \
    -RenderOffScreen \
    -nosound \
    -quality-level=Low \
    -ResX=640 \
    -ResY=360 \
    -carla-rpc-port="${CARLA_PORT}" \
    >/dev/null

  # Catch configuration and GPU startup failures immediately. Keep the stopped
  # container so its real error remains available through `docker logs`.
  sleep 3
  if [[ "$(docker_command inspect --format '{{.State.Running}}' "${CARLA_DOCKER_NAME}")" != "true" ]]; then
    echo "CARLA exited during startup. Container logs:" >&2
    docker_command logs --tail 120 "${CARLA_DOCKER_NAME}" >&2 || true
    echo "Container state:" >&2
    docker_command inspect \
      --format 'status={{.State.Status}} exit_code={{.State.ExitCode}} error={{.State.Error}}' \
      "${CARLA_DOCKER_NAME}" >&2 || true
    exit 1
  fi
fi

if "${PROJECT_ROOT}/scripts/ec2_run.sh" \
  python "${PROJECT_ROOT}/scripts/wait_for_carla.py"; then
  echo "CARLA is RPC-ready on ${CARLA_HOST}:${CARLA_PORT}."
  exit 0
fi

echo "CARLA did not become RPC-ready. Last container log lines:" >&2
docker_command logs --tail 80 "${CARLA_DOCKER_NAME}" >&2 || true
exit 1
