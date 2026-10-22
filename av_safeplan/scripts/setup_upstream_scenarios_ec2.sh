#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
EXTERNAL_ROOT="${AV_SAFEPLAN_EXTERNAL_ROOT:-${RUNTIME_ROOT}/external}"
SCENARIO_RUNNER_ROOT="${EXTERNAL_ROOT}/scenario_runner"
LEADERBOARD_ROOT="${EXTERNAL_ROOT}/leaderboard"

sync_repository() {
  local repository="$1"
  local revision="$2"
  local destination="$3"

  if [[ ! -d "${destination}/.git" ]]; then
    git clone --filter=blob:none --no-checkout "${repository}" "${destination}"
  fi
  git -C "${destination}" fetch --depth 1 origin "${revision}"
  git -C "${destination}" checkout --detach FETCH_HEAD
}

mkdir -p "${EXTERNAL_ROOT}"

echo "Fetching ScenarioRunner v0.9.15 (small source checkout; no dataset download)..."
sync_repository \
  "https://github.com/carla-simulator/scenario_runner.git" \
  "v0.9.15" \
  "${SCENARIO_RUNNER_ROOT}"

echo "Fetching Leaderboard 2.0 route definitions (source only; no sensor dataset)..."
sync_repository \
  "https://github.com/carla-simulator/leaderboard.git" \
  "leaderboard-2.0" \
  "${LEADERBOARD_ROOT}"

"${PROJECT_ROOT}/scripts/ec2_run.sh" \
  pip install --disable-pip-version-check \
  -r "${SCENARIO_RUNNER_ROOT}/requirements.txt"

SCENARIO_RUNNER_SHA="$(git -C "${SCENARIO_RUNNER_ROOT}" rev-parse HEAD)"
LEADERBOARD_SHA="$(git -C "${LEADERBOARD_ROOT}" rev-parse HEAD)"

echo
echo "Public scenario sources are ready."
echo "ScenarioRunner: ${SCENARIO_RUNNER_ROOT} @ ${SCENARIO_RUNNER_SHA}"
echo "Leaderboard:    ${LEADERBOARD_ROOT} @ ${LEADERBOARD_SHA}"
echo
echo "Next:"
echo "  ./scripts/prepare_week1_upstream_routes_ec2.sh"
