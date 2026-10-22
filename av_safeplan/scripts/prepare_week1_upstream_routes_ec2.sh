#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
LEADERBOARD_ROOT="${AV_SAFEPLAN_EXTERNAL_ROOT:-${RUNTIME_ROOT}/external}/leaderboard"
OUTPUT_ROOT="${RUNTIME_ROOT}/outputs/upstream"

if [[ ! -d "${LEADERBOARD_ROOT}/.git" ]]; then
  echo "Leaderboard route definitions are missing at ${LEADERBOARD_ROOT}." >&2
  echo "Run ./scripts/setup_upstream_scenarios_ec2.sh first." >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

"${PROJECT_ROOT}/scripts/ec2_run.sh" python \
  "${PROJECT_ROOT}/scripts/prepare_week1_upstream_routes.py" \
  "${LEADERBOARD_ROOT}" \
  --config "${PROJECT_ROOT}/config/upstream_scenarios.yaml" \
  --output-routes "${OUTPUT_ROOT}/week1_town12_routes.xml" \
  --output-report "${OUTPUT_ROOT}/week1_town12_selection.json"

echo "Reduced routes: ${OUTPUT_ROOT}/week1_town12_routes.xml"
echo "Selection report: ${OUTPUT_ROOT}/week1_town12_selection.json"
