#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

RUNTIME_ROOT="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
EXTERNAL_ROOT="${AV_SAFEPLAN_EXTERNAL_ROOT:-${RUNTIME_ROOT}/external}"
SCENARIO_RUNNER_ROOT="${EXTERNAL_ROOT}/scenario_runner"
ROUTES_FILE="${RUNTIME_ROOT}/outputs/upstream/week1_town12_routes.xml"
OUTPUT_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT}/week1-upstream"
KEEP_RUNNING="${AV_SAFEPLAN_KEEP_CARLA_RUNNING:-0}"

if [[ ! -f "${SCENARIO_RUNNER_ROOT}/scenario_runner.py" ]]; then
  echo "ScenarioRunner is missing at ${SCENARIO_RUNNER_ROOT}." >&2
  echo "Run ./scripts/setup_upstream_scenarios_ec2.sh first." >&2
  exit 1
fi
if [[ ! -f "${ROUTES_FILE}" ]]; then
  "${PROJECT_ROOT}/scripts/prepare_week1_upstream_routes_ec2.sh"
fi

cleanup() {
  if [[ "${KEEP_RUNNING}" != "1" ]]; then
    "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true
  fi
}
trap cleanup EXIT INT TERM

mkdir -p "${OUTPUT_ROOT}/criteria"
export PYTHONPATH="${PROJECT_ROOT}/src:${CARLA_ROOT}/PythonAPI/carla:${SCENARIO_RUNNER_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export SCENARIO_RUNNER_ROOT
export AV_SAFEPLAN_SCENARIO_OUTPUT_ROOT="${OUTPUT_ROOT}/telemetry"

"${PROJECT_ROOT}/scripts/start_carla_ec2_docker.sh"

ROUTE_IDS="$("${PROJECT_ROOT}/scripts/ec2_run.sh" python -c \
  'import sys, xml.etree.ElementTree as E; print(" ".join(r.attrib["id"] for r in E.parse(sys.argv[1]).getroot().findall("route")))' \
  "${ROUTES_FILE}")"

if [[ -z "${ROUTE_IDS}" ]]; then
  echo "No routes were written to ${ROUTES_FILE}." >&2
  exit 1
fi

for ROUTE_ID in ${ROUTE_IDS}; do
  echo "Running official Town12 route ${ROUTE_ID} through the AV SafePlan Behavior Agent adapter..."
  mkdir -p "${OUTPUT_ROOT}/criteria/route-${ROUTE_ID}"
  export AV_SAFEPLAN_SCENARIO_ROUTE_ID="week1-upstream-${ROUTE_ID}"
  export AV_SAFEPLAN_SCENARIO_RUN_NAME="week1-upstream-${ROUTE_ID}"
  "${PROJECT_ROOT}/scripts/ec2_run.sh" python \
    "${SCENARIO_RUNNER_ROOT}/scenario_runner.py" \
    --route "${ROUTES_FILE}" \
    --route-id "${ROUTE_ID}" \
    --agent "${PROJECT_ROOT}/scripts/scenario_runner_behavior_agent.py" \
    --timeout 300 \
    --output \
    --json \
    --outputDir "${OUTPUT_ROOT}/criteria/route-${ROUTE_ID}"
done

echo "Official criteria: ${OUTPUT_ROOT}/criteria"
echo "AV SafePlan telemetry and images: ${OUTPUT_ROOT}/telemetry"
echo "These runs remain pending until the criteria JSON and images are reviewed."
