#!/usr/bin/env bash
# Small evidence pilot, not a full training-set collection campaign.
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"
RUNTIME_ROOT="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
SCENARIO_RUNNER_ROOT="${RUNTIME_ROOT}/external/scenario_runner"
ROUTES="${WEEK2_ROUTES:-${RUNTIME_ROOT}/outputs/upstream/week1_town12_windowed_routes.xml}"
OUTPUT="${WEEK2_OUTPUT:-${RUNTIME_ROOT}/outputs/trajectories/week2-pilot-$(date -u +%Y%m%dT%H%M%SZ)}"
LIMIT="${WEEK2_ROUTE_WALL_SECONDS:-600}"
ROUTE_IDS="${WEEK2_ROUTE_IDS:-0 1 2}"
for ROUTE in ${ROUTE_IDS}; do
  case "${ROUTE}" in 0|1|2) ;; *) echo 'Route IDs must be a subset of 0 1 2'; exit 2 ;; esac
done
[[ -n "${ROUTE_IDS// /}" ]] || { echo 'No route IDs selected'; exit 2; }
[[ "${LIMIT}" =~ ^[0-9]+$ ]] && (( LIMIT >= 30 && LIMIT <= 600 )) || { echo 'Route limit must be 30–600 seconds'; exit 2; }
[[ -f "${ROUTES}" && -f "${SCENARIO_RUNNER_ROOT}/scenario_runner.py" ]] || { echo 'Existing route XML/ScenarioRunner required'; exit 2; }
FREE_KB="$(df -Pk "${RUNTIME_ROOT}" | awk 'NR==2 {print $4}')"
(( FREE_KB >= 8388608 )) || { echo 'Need at least 8 GiB free; no data deleted'; exit 2; }
if docker_command ps --format '{{.Names}}' | grep -Fxq "${CARLA_DOCKER_NAME}"; then
  echo 'CARLA is already running; refusing to interrupt another job'; exit 2
fi
mkdir "${OUTPUT}"
cp "${ROUTES}" "${OUTPUT}/routes.xml"
cp "${PROJECT_ROOT}/scripts/av_safeplan_signalized_junction.py" "${SCENARIO_RUNNER_ROOT}/srunner/scenarios/av_safeplan_signalized_junction.py"
cleanup() {
  result=$?
  trap - EXIT INT TERM
  docker_command logs "${CARLA_DOCKER_NAME}" > "${OUTPUT}/carla.log" 2>&1 || true
  bash "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true
  printf '%s\n' "${result}" > "${OUTPUT}/batch_exit_code.txt"
  echo "Results: ${OUTPUT}"
  exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export SCENARIO_RUNNER_ROOT
export PYTHONPATH="${PROJECT_ROOT}/src:${CARLA_ROOT}/PythonAPI/carla:${SCENARIO_RUNNER_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export AV_SAFEPLAN_SCENARIO_OUTPUT_ROOT="${OUTPUT}/telemetry"
export AV_SAFEPLAN_SOURCE_ROUTES="${OUTPUT}/routes.xml"
export AV_SAFEPLAN_SCENARIO_SEED="2026"
timeout --signal=TERM --kill-after=20s 300 bash "${PROJECT_ROOT}/scripts/start_carla_ec2_docker.sh"
FAILED=0
for ROUTE in ${ROUTE_IDS}; do
  FREE_KB="$(df -Pk "${RUNTIME_ROOT}" | awk 'NR==2 {print $4}')"
  (( FREE_KB >= 8388608 )) || { echo 'Disk safety floor reached'; exit 2; }
  mkdir -p "${OUTPUT}/criteria/route-${ROUTE}"
  export AV_SAFEPLAN_SCENARIO_ROUTE_ID="week2-upstream-${ROUTE}"
  export AV_SAFEPLAN_SCENARIO_RUN_NAME="week2-upstream-${ROUTE}"
  set +e
  timeout --signal=TERM --kill-after=20s "${LIMIT}s" \
    bash "${PROJECT_ROOT}/scripts/ec2_run.sh" python "${PROJECT_ROOT}/scripts/run_seeded_scenario_runner.py" \
    --route "${OUTPUT}/routes.xml" --route-id "${ROUTE}" \
    --agent "${PROJECT_ROOT}/scripts/scenario_runner_behavior_agent.py" \
    --trafficManagerSeed "${AV_SAFEPLAN_SCENARIO_SEED}" \
    --timeout 300 --output --json --outputDir "${OUTPUT}/criteria/route-${ROUTE}" \
    2>&1 | tee "${OUTPUT}/route-${ROUTE}.log"
  result=${PIPESTATUS[0]}
  set -e
  printf '%s\n' "${result}" > "${OUTPUT}/route-${ROUTE}-exit_code.txt"
  if (( result != 0 )); then
    FAILED=1
    # A killed evaluator may leave actors behind. Stop rather than contaminate
    # the next route or automatically spend more on a broken batch.
    break
  fi
  if ! python3 "${PROJECT_ROOT}/scripts/summarize_week2_collection.py" "${OUTPUT}" --route "${ROUTE}"; then
    FAILED=1
    break
  fi
done
REPORT_ARGS=()
for ROUTE in ${ROUTE_IDS}; do REPORT_ARGS+=(--route "${ROUTE}"); done
python3 "${PROJECT_ROOT}/scripts/summarize_week2_collection.py" "${OUTPUT}" "${REPORT_ARGS[@]}" || FAILED=1
exit "${FAILED}"
