#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"
RUNTIME="${AV_SAFEPLAN_RUNTIME_ROOT:-${HOME}/av-safeplan-runtime}"
OUTPUT="${RUNTIME}/outputs/trajectories/week2-simlingo-$(date -u +%Y%m%dT%H%M%SZ)"
if docker_command ps --format '{{.Names}}' | grep -Fxq "${CARLA_DOCKER_NAME}"; then
  echo 'CARLA already running; refusing to interrupt it'; exit 2
fi
FREE_KB="$(df -Pk "${RUNTIME}" | awk 'NR==2 {print $4}')"
(( FREE_KB >= 8388608 )) || { echo 'Need at least 8 GiB free'; exit 2; }
mkdir "${OUTPUT}"
cp "${RUNTIME}/outputs/upstream/week1_town12_windowed_routes.xml" "${OUTPUT}/routes.xml"
export PROJECT_ROOT OUTPUT
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
export CUDA_HOME="${RUNTIME}/micromamba/envs/av-safeplan-simlingo"
cleanup() {
  result=$?
  trap - EXIT INT TERM
  docker_command logs "${CARLA_DOCKER_NAME}" > "${OUTPUT}/carla.log" 2>&1 || true
  bash "${PROJECT_ROOT}/scripts/stop_carla_ec2_docker.sh" || true
  printf '%s\n' "${result}" > "${OUTPUT}/exit_code.txt"
  for episode in "${OUTPUT}"/telemetry/episode-*; do
    [[ -f "${episode}/episode.jsonl" && -f "${episode}/trajectory.jsonl" ]] || continue
    timeout --signal=TERM --kill-after=10s 120 \
      bash "${PROJECT_ROOT}/scripts/simlingo_ec2_run.sh" python \
      "${PROJECT_ROOT}/scripts/finalize_recorded_episode.py" "${episode}" \
      --process-exit "${result}" --recover-video || true
  done
  echo "Results: ${OUTPUT}"
  exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
timeout --signal=TERM --kill-after=30s 900 bash -c '
  set -euo pipefail
  cd "$PROJECT_ROOT"
  bash scripts/start_carla_ec2_docker.sh
  bash scripts/simlingo_ec2_run.sh python scripts/run_simlingo_leaderboard.py \
    --routes "$OUTPUT/routes.xml" --routes-subset 1 --repetitions 1 --output-dir "$OUTPUT"
' 2>&1 | tee "${OUTPUT}/run.log"
