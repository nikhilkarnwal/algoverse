#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

CONTAINER_ID="$(
  docker_command ps --all \
    --filter "name=^/${CARLA_DOCKER_NAME}$" \
    --format '{{.ID}}'
)"
if [[ -z "${CONTAINER_ID}" ]]; then
  echo "CARLA container is not running."
  exit 0
fi

echo "Stopping CARLA container ${CARLA_DOCKER_NAME}..."
if ! docker_command stop --time 20 "${CARLA_DOCKER_NAME}" >/dev/null; then
  docker_command rm --force "${CARLA_DOCKER_NAME}" >/dev/null
else
  docker_command rm "${CARLA_DOCKER_NAME}" >/dev/null
fi
echo "CARLA container stopped and removed."
