#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT_NAME="${1:-av-safeplan-simlingo}"

if command -v mamba >/dev/null 2>&1; then
  ENVIRONMENT_TOOL="mamba"
elif command -v conda >/dev/null 2>&1; then
  ENVIRONMENT_TOOL="conda"
else
  echo "Conda or Mamba is required." >&2
  exit 1
fi

"${ENVIRONMENT_TOOL}" env create \
  --name "${ENVIRONMENT_NAME}" \
  --file "${PROJECT_ROOT}/environments/simlingo.yml"

"${ENVIRONMENT_TOOL}" run --name "${ENVIRONMENT_NAME}" \
  python -m pip install flash-attn==2.7.0.post2 --no-build-isolation

"${ENVIRONMENT_TOOL}" run --name "${ENVIRONMENT_NAME}" \
  python -m pip install --no-deps -e "${PROJECT_ROOT}"

echo "Environment ${ENVIRONMENT_NAME} is ready."
echo "Copy .env.example to .env, set external paths, then run scripts/verify_stack.py."
