#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EC2_ENV_FILE="${AV_SAFEPLAN_EC2_ENV_FILE:-${PROJECT_ROOT}/.env.ec2}"
SIMLINGO_ENV_FILE="${AV_SAFEPLAN_SIMLINGO_ENV_FILE:-${PROJECT_ROOT}/.env.simlingo.ec2}"
for required in "${EC2_ENV_FILE}" "${SIMLINGO_ENV_FILE}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing ${required}; finish setup_simlingo_ec2.sh first." >&2
    exit 1
  fi
done
set -a
# shellcheck disable=SC1090
source "${EC2_ENV_FILE}"
# shellcheck disable=SC1090
source "${SIMLINGO_ENV_FILE}"
set +a
export MAMBA_ROOT_PREFIX
exec "${MICROMAMBA_BIN}" run -n "${AV_SAFEPLAN_SIMLINGO_ENV_NAME}" "$@"
