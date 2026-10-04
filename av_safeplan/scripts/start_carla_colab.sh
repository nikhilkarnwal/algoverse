#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

CARLA_ROOT="${CARLA_ROOT:-/content/av_safeplan/external/carla-0.9.15}"
CARLA_PORT="${CARLA_PORT:-2000}"
CARLA_LOG="${CARLA_LOG:-/content/carla-server.log}"
CARLA_PID_FILE="${CARLA_PID_FILE:-/content/carla-server.pid}"

if [[ ! -x "${CARLA_ROOT}/CarlaUE4.sh" ]]; then
  echo "CARLA executable not found at ${CARLA_ROOT}/CarlaUE4.sh" >&2
  echo "Run scripts/setup_colab.sh with AV_SAFEPLAN_DOWNLOAD_CARLA=1." >&2
  exit 1
fi

if nc -z 127.0.0.1 "${CARLA_PORT}"; then
  echo "CARLA is already listening on port ${CARLA_PORT}."
  exit 0
fi

echo "Starting CARLA 0.9.15 in off-screen, low-quality mode..."
nohup "${CARLA_ROOT}/CarlaUE4.sh" \
  -RenderOffScreen \
  -nosound \
  -quality-level=Low \
  -ResX=640 \
  -ResY=480 \
  -carla-rpc-port="${CARLA_PORT}" \
  >"${CARLA_LOG}" 2>&1 &
echo $! > "${CARLA_PID_FILE}"

for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 "${CARLA_PORT}"; then
    echo "CARLA is ready on port ${CARLA_PORT}. Log: ${CARLA_LOG}"
    exit 0
  fi
  sleep 2
done

echo "CARLA did not become ready. Last log lines:" >&2
tail -n 40 "${CARLA_LOG}" >&2 || true
exit 1
