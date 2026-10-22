#!/usr/bin/env bash
set -euo pipefail

# Execute the Behavior Agent portion of the Week 1 completion gates on Town12.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

SEED="${WEEK1_SEED:-2026}"
SMOKE_STEPS="${WEEK1_SMOKE_STEPS:-20}"
REPLAY_STEPS="${WEEK1_REPLAY_STEPS:-200}"
SCENARIO_STEPS="${WEEK1_SCENARIO_STEPS:-150}"
SESSION_NAME="week1-validation-$(date -u +%Y%m%dT%H%M%SZ)"
SESSION_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT}/${SESSION_NAME}"
PIPELINE_STATUS=0
SCENARIOS=(
  lead_brake_default
  cross_traffic_default
  red_light_straight_default
  red_light_transition_default
)

if ! docker_command image inspect "${CARLA_DOCKER_IMAGE}" >/dev/null 2>&1; then
  echo "Configured CARLA image is unavailable: ${CARLA_DOCKER_IMAGE}" >&2
  echo "Run ./scripts/install_town12_ec2_docker.sh first." >&2
  exit 1
fi
if [[ "${CARLA_DOCKER_IMAGE}" != *town12* ]]; then
  echo "Configured image does not appear to contain Town12: ${CARLA_DOCKER_IMAGE}" >&2
  echo "Run ./scripts/install_town12_ec2_docker.sh first." >&2
  exit 1
fi

mkdir -p "${SESSION_ROOT}"
export AV_SAFEPLAN_KEEP_CARLA_RUNNING=1

finalize() {
  local command_status=$?
  local final_status="${command_status}"
  trap - EXIT
  set +e

  echo "[4/4] Building the manual-audit queue and completion report..."
  "${PROJECT_ROOT}/scripts/ec2_run.sh" \
    python "${PROJECT_ROOT}/scripts/audit_episodes.py" \
    "${SESSION_ROOT}" \
    --output "${SESSION_ROOT}/audit_queue.jsonl" \
    --seed "${SEED}" || final_status=1
  "${PROJECT_ROOT}/scripts/ec2_run.sh" \
    python "${PROJECT_ROOT}/scripts/check_week1_completion.py" \
    "${SESSION_ROOT}" \
    --allow-pending || final_status=1
  "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true

  echo
  echo "Results: ${SESSION_ROOT}"
  if [[ "${final_status}" -eq 0 ]]; then
    echo "Behavior Agent validation commands finished."
  else
    echo "Behavior Agent validation stopped with an error; week1_status.json records the completed gates." >&2
  fi
  echo "The Week 1 checkpoint remains pending until human audit and SimLingo validation pass."
  exit "${final_status}"
}
trap finalize EXIT

run_behavior() {
  "${PROJECT_ROOT}/scripts/run_behavior_trajectory_ec2.sh" \
    --map Town12 \
    --seed "${SEED}" \
    --output-dir "${SESSION_ROOT}" \
    "$@"
}

echo "[1/4] Verifying synchronous Town12 execution..."
run_behavior \
  --reload-world \
  --steps "${SMOKE_STEPS}" \
  --no-images \
  --run-name town12-smoke

echo "[2/4] Recording two matched deterministic replays..."
run_behavior --reload-world --steps "${REPLAY_STEPS}" --run-name replay-a
run_behavior --reload-world --steps "${REPLAY_STEPS}" --run-name replay-b
if ! "${PROJECT_ROOT}/scripts/ec2_run.sh" \
  python "${PROJECT_ROOT}/scripts/compare_replays.py" \
  "${SESSION_ROOT}/replay-a" \
  "${SESSION_ROOT}/replay-b" \
  | tee "${SESSION_ROOT}/replay_comparison.json"; then
  PIPELINE_STATUS=1
  echo "Replay comparison failed; continuing controlled scenarios for diagnostics." >&2
fi

echo "[3/4] Running the reduced collision and red-light scenario matrix..."
for scenario in "${SCENARIOS[@]}"; do
  if ! run_behavior \
    --reload-world \
    --steps "${SCENARIO_STEPS}" \
    --scenario "${scenario}" \
    --run-name "scenario-${scenario}"; then
    PIPELINE_STATUS=1
    echo "Scenario ${scenario} failed; continuing the remaining matrix." >&2
  fi
done

exit "${PIPELINE_STATUS}"
