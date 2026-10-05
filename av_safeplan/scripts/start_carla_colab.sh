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
CARLA_RUN_USER="${CARLA_RUN_USER:-carla-runner}"
CARLA_USER_HOME="${CARLA_USER_HOME:-/tmp/av-safeplan-carla}"
CARLA_BINARY="${CARLA_ROOT}/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping"

if [[ ! -x "${CARLA_BINARY}" ]]; then
  echo "CARLA executable not found at ${CARLA_BINARY}" >&2
  echo "Run scripts/setup_colab.sh with AV_SAFEPLAN_DOWNLOAD_CARLA=1." >&2
  exit 1
fi

SERVER_ALREADY_LISTENING=0
if nc -z 127.0.0.1 "${CARLA_PORT}" >/dev/null 2>&1; then
  SERVER_ALREADY_LISTENING=1
  echo "CARLA is already listening on port ${CARLA_PORT}; checking RPC readiness..."
fi

LAUNCH_PREFIX=()
if [[ "${SERVER_ALREADY_LISTENING}" == "0" && "${EUID}" -eq 0 ]]; then
  if ! command -v runuser >/dev/null 2>&1; then
    echo "runuser is unavailable. Rerun scripts/setup_colab.sh to install util-linux." >&2
    exit 1
  fi
  if ! id "${CARLA_RUN_USER}" >/dev/null 2>&1; then
    if ! command -v useradd >/dev/null 2>&1; then
      echo "useradd is unavailable. Rerun scripts/setup_colab.sh to install passwd." >&2
      exit 1
    fi
    echo "Creating unprivileged CARLA runtime user ${CARLA_RUN_USER}..."
    useradd --system --create-home --home-dir "${CARLA_USER_HOME}" --shell /bin/bash \
      "${CARLA_RUN_USER}"
  fi

  CARLA_RUN_GROUP="$(id -gn "${CARLA_RUN_USER}")"
  install -d -m 0755 -o "${CARLA_RUN_USER}" -g "${CARLA_RUN_GROUP}" "${CARLA_USER_HOME}"
  install -d -m 0700 -o "${CARLA_RUN_USER}" -g "${CARLA_RUN_GROUP}" \
    "${CARLA_USER_HOME}/runtime"
  mkdir -p "${CARLA_ROOT}/CarlaUE4/Saved"
  chown -R "${CARLA_RUN_USER}:${CARLA_RUN_GROUP}" "${CARLA_ROOT}/CarlaUE4/Saved"

  for device_group in video render; do
    if getent group "${device_group}" >/dev/null 2>&1; then
      usermod -a -G "${device_group}" "${CARLA_RUN_USER}"
    fi
  done

  LAUNCH_PREFIX=(
    runuser -u "${CARLA_RUN_USER}" --
    env
    "HOME=${CARLA_USER_HOME}"
    "USER=${CARLA_RUN_USER}"
    "LOGNAME=${CARLA_RUN_USER}"
    "XDG_RUNTIME_DIR=${CARLA_USER_HOME}/runtime"
  )
fi

if [[ "${SERVER_ALREADY_LISTENING}" == "0" ]]; then
  echo "Starting CARLA 0.9.15 in off-screen, low-quality mode..."
  (
    cd "${CARLA_ROOT}"
    nohup "${LAUNCH_PREFIX[@]}" "${CARLA_BINARY}" CarlaUE4 \
      -RenderOffScreen \
      -nosound \
      -quality-level=Low \
      -ResX=640 \
      -ResY=480 \
      -carla-rpc-port="${CARLA_PORT}" \
      >"${CARLA_LOG}" 2>&1 &
    echo $! > "${CARLA_PID_FILE}"
  )
fi

if "${PROJECT_ROOT}/scripts/colab_run.sh" \
  python "${PROJECT_ROOT}/scripts/wait_for_carla.py"; then
  echo "CARLA is ready on port ${CARLA_PORT}. Log: ${CARLA_LOG}"
  exit 0
fi

echo "CARLA did not become RPC-ready. Last log lines:" >&2
tail -n 40 "${CARLA_LOG}" >&2 || true
exit 1
