#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

OUTPUT_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT:-/content/av_safeplan/outputs/trajectories}"
CARLA_LOG="${CARLA_LOG:-/content/carla-server.log}"
mkdir -p "${OUTPUT_ROOT}"

"${PROJECT_ROOT}/scripts/start_carla_colab.sh"
if "${PROJECT_ROOT}/scripts/colab_run.sh" \
  python "${PROJECT_ROOT}/scripts/smoke_behavior_agent.py" \
  --output-dir "${OUTPUT_ROOT}" \
  "$@"; then
  exit 0
else
  STATUS=$?
fi

echo "Trajectory run failed. Last CARLA log lines:" >&2
tail -n 60 "${CARLA_LOG}" >&2 || true
exit "${STATUS}"
