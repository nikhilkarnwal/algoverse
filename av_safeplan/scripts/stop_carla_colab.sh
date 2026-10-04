#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

CARLA_PORT="${CARLA_PORT:-2000}"
CARLA_PID_FILE="${CARLA_PID_FILE:-/content/carla-server.pid}"
CARLA_RUN_USER="${CARLA_RUN_USER:-carla-runner}"

if [[ -f "${CARLA_PID_FILE}" ]]; then
  CARLA_PID="$(tr -cd '0-9' < "${CARLA_PID_FILE}")"
  if [[ -n "${CARLA_PID}" ]] && kill -0 "${CARLA_PID}" >/dev/null 2>&1; then
    kill "${CARLA_PID}" >/dev/null 2>&1 || true
  fi
fi

if [[ "${EUID}" -eq 0 ]] && id "${CARLA_RUN_USER}" >/dev/null 2>&1; then
  mapfile -t CARLA_PIDS < <(
    pgrep -u "${CARLA_RUN_USER}" -f 'CarlaUE4-Linux-Shipping' 2>/dev/null || true
  )
  if [[ "${#CARLA_PIDS[@]}" -gt 0 ]]; then
    kill "${CARLA_PIDS[@]}" >/dev/null 2>&1 || true
  fi
fi

for _ in $(seq 1 20); do
  if ! nc -z 127.0.0.1 "${CARLA_PORT}" >/dev/null 2>&1; then
    rm -f -- "${CARLA_PID_FILE}"
    echo "CARLA stopped."
    exit 0
  fi
  sleep 1
done

echo "CARLA is still listening on port ${CARLA_PORT}. Restart the Colab runtime before importing maps." >&2
exit 1
