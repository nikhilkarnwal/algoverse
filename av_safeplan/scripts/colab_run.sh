#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

MICROMAMBA_BIN="${MICROMAMBA_BIN:-/content/av_safeplan/bin/micromamba}"
MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-/content/av_safeplan/micromamba}"
ENVIRONMENT_NAME="${AV_SAFEPLAN_ENV_NAME:-av-safeplan-simlingo}"
export MAMBA_ROOT_PREFIX

if [[ ! -x "${MICROMAMBA_BIN}" ]]; then
  echo "micromamba is unavailable. Run scripts/setup_colab.sh first." >&2
  exit 1
fi

exec "${MICROMAMBA_BIN}" run -n "${ENVIRONMENT_NAME}" "$@"
