#!/usr/bin/env bash
# Two upstream-only diagnostic episodes; never a training/evaluation split claim.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"
RUNTIME_ROOT="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
SCENARIO_RUNNER_ROOT="${RUNTIME_ROOT}/external/scenario_runner"
OUTPUT="${WEEK2_VALIDATION_OUTPUT:-${RUNTIME_ROOT}/outputs/trajectories/week2-upstream-validation-$(date -u +%Y%m%dT%H%M%SZ)}"
if docker_command ps --format '{{.Names}}' | grep -Fxq "${CARLA_DOCKER_NAME}"; then
  echo 'Refusing to interrupt an existing CARLA process'; exit 2
fi
FREE_KB="$(df -Pk "${RUNTIME_ROOT}" | awk 'NR==2 {print $4}')"
(( FREE_KB >= 8388608 )) || { echo 'Need at least 8 GiB free'; exit 2; }
mkdir "${OUTPUT}"
echo "Results: ${OUTPUT}"
cleanup() {
  result=$?
  trap - EXIT INT TERM
  docker_command logs "${CARLA_DOCKER_NAME}" > "${OUTPUT}/carla.log" 2>&1 || true
  bash "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true
  printf '%s\n' "${result}" > "${OUTPUT}/batch_exit_code.txt"
  exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export SCENARIO_RUNNER_ROOT
export PYTHONPATH="${PROJECT_ROOT}/src:${CARLA_ROOT}/PythonAPI/carla:${SCENARIO_RUNNER_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export AV_SAFEPLAN_SCENARIO_OUTPUT_ROOT="${OUTPUT}/telemetry"
export AV_SAFEPLAN_SOURCE_ROUTES="${OUTPUT}/routes.xml"
export AV_SAFEPLAN_SCENARIO_SEED=2026
cp "${PROJECT_ROOT}/config/week2_upstream_validation.yaml" "${OUTPUT}/selection-config.yaml"
git -C "${SCENARIO_RUNNER_ROOT}" rev-parse HEAD > "${OUTPUT}/scenario-runner-revision.txt"
git -C "${PROJECT_ROOT}" rev-parse HEAD > "${OUTPUT}/project-revision.txt"
timeout --signal=TERM --kill-after=10s 60 bash "${PROJECT_ROOT}/scripts/ec2_run.sh" python \
  "${PROJECT_ROOT}/scripts/prepare_week1_upstream_routes.py" \
  "${RUNTIME_ROOT}/external/leaderboard/data/routes_devtest.xml" \
  "${RUNTIME_ROOT}/external/leaderboard/data/routes_training.xml" \
  "${RUNTIME_ROOT}/external/leaderboard/data/routes_validation.xml" \
  --config "${OUTPUT}/selection-config.yaml" --output-routes "${OUTPUT}/full-routes.xml" \
  --output-report "${OUTPUT}/selection.json" > "${OUTPUT}/selection.log" 2>&1
timeout --signal=TERM --kill-after=20s 300 bash "${PROJECT_ROOT}/scripts/start_carla_ec2_docker.sh"
timeout --signal=TERM --kill-after=20s 300 bash "${PROJECT_ROOT}/scripts/ec2_run.sh" python \
  "${PROJECT_ROOT}/scripts/window_week1_upstream_routes.py" \
  --input-routes "${OUTPUT}/full-routes.xml" --selection-report "${OUTPUT}/selection.json" \
  --output-routes "${OUTPUT}/routes.xml" --output-report "${OUTPUT}/route-windows.json" \
  --before-m 50 --after-m 120 --host "${CARLA_HOST}" --port "${CARLA_PORT}" \
  > "${OUTPUT}/window.log" 2>&1
REPORT_ARGS=()
for ROUTE in 0 1; do
  FREE_KB="$(df -Pk "${RUNTIME_ROOT}" | awk 'NR==2 {print $4}')"
  (( FREE_KB >= 8388608 )) || { echo 'Disk safety floor reached'; exit 2; }
  mkdir -p "${OUTPUT}/criteria/route-${ROUTE}"
  export AV_SAFEPLAN_SCENARIO_ROUTE_ID="week2-upstream-${ROUTE}"
  export AV_SAFEPLAN_SCENARIO_RUN_NAME="week2-upstream-${ROUTE}"
  echo "Running upstream validation route ${ROUTE}"
  set +e
  timeout --signal=TERM --kill-after=20s 600 bash "${PROJECT_ROOT}/scripts/ec2_run.sh" python \
    "${PROJECT_ROOT}/scripts/run_seeded_scenario_runner.py" \
    --route "${OUTPUT}/routes.xml" --route-id "${ROUTE}" \
    --agent "${PROJECT_ROOT}/scripts/scenario_runner_behavior_agent.py" \
    --trafficManagerSeed 2026 --timeout 300 --output --json \
    --outputDir "${OUTPUT}/criteria/route-${ROUTE}" > "${OUTPUT}/route-${ROUTE}.log" 2>&1
  result=$?
  set -e
  printf '%s\n' "${result}" > "${OUTPUT}/route-${ROUTE}-exit_code.txt"
  REPORT_ARGS+=(--route "${ROUTE}")
  if (( result != 0 )); then
    python3 "${PROJECT_ROOT}/scripts/summarize_week2_collection.py" "${OUTPUT}" "${REPORT_ARGS[@]}" || true
    tail -n 45 "${OUTPUT}/route-${ROUTE}.log"
    exit "${result}"
  fi
  python3 "${PROJECT_ROOT}/scripts/summarize_week2_collection.py" "${OUTPUT}" "${REPORT_ARGS[@]}"
done
python3 "${PROJECT_ROOT}/scripts/summarize_week2_collection.py" "${OUTPUT}" --route 0 --route 1
