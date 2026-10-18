#!/usr/bin/env bash

# Shared EC2 Docker helpers. Source this file from another script.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EC2_ENV_FILE="${AV_SAFEPLAN_EC2_ENV_FILE:-${PROJECT_ROOT}/.env.ec2}"

if [[ ! -f "${EC2_ENV_FILE}" ]]; then
  echo "EC2 configuration is missing at ${EC2_ENV_FILE}." >&2
  echo "Run scripts/setup_ec2_docker.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${EC2_ENV_FILE}"
set +a

CARLA_DOCKER_IMAGE="${CARLA_DOCKER_IMAGE:-carlasim/carla:0.9.15}"
CARLA_DOCKER_NAME="${CARLA_DOCKER_NAME:-av-safeplan-carla}"

if docker info >/dev/null 2>&1; then
  AV_SAFEPLAN_DOCKER_COMMAND=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  AV_SAFEPLAN_DOCKER_COMMAND=(sudo docker)
else
  echo "Docker is unavailable to the current user." >&2
  echo "Confirm Docker is running and that passwordless sudo is available." >&2
  exit 1
fi

docker_command() {
  "${AV_SAFEPLAN_DOCKER_COMMAND[@]}" "$@"
}
