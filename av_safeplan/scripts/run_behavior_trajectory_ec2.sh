#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

OUTPUT_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT}"
KEEP_RUNNING="${AV_SAFEPLAN_KEEP_CARLA_RUNNING:-0}"
mkdir -p "${OUTPUT_ROOT}"

cleanup() {
  if [[ "${KEEP_RUNNING}" != "1" ]]; then
    "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true
  fi
}
trap cleanup EXIT INT TERM

"${PROJECT_ROOT}/scripts/start_carla_ec2_docker.sh"

if "${PROJECT_ROOT}/scripts/ec2_run.sh" \
  python "${PROJECT_ROOT}/scripts/smoke_behavior_agent.py" \
  --output-dir "${OUTPUT_ROOT}" \
  "$@"; then
  echo "Trajectory completed. Output root: ${OUTPUT_ROOT}"
  exit 0
else
  STATUS=$?
fi

echo "Trajectory run failed. Last CARLA container log lines:" >&2
docker_command logs --tail 100 "${CARLA_DOCKER_NAME}" >&2 || true
exit "${STATUS}"
