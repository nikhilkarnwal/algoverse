#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EC2_ENV_FILE="${AV_SAFEPLAN_EC2_ENV_FILE:-${PROJECT_ROOT}/.env.ec2}"

if [[ ! -f "${EC2_ENV_FILE}" ]]; then
  echo "EC2 configuration is missing at ${EC2_ENV_FILE}." >&2
  echo "Run scripts/setup_ec2_docker.sh first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${EC2_ENV_FILE}"
set +a

if [[ ! -x "${MICROMAMBA_BIN}" ]]; then
  echo "micromamba is unavailable at ${MICROMAMBA_BIN}." >&2
  echo "Run scripts/setup_ec2_docker.sh first." >&2
  exit 1
fi

export MAMBA_ROOT_PREFIX
exec "${MICROMAMBA_BIN}" run -n "${AV_SAFEPLAN_ENV_NAME}" "$@"
