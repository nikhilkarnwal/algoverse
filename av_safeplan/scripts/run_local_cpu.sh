#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${AV_SAFEPLAN_LOCAL_VENV:-${PROJECT_ROOT}/.venv-local}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Local CPU validation is intended for macOS." >&2
  exit 1
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PROJECT_ROOT}/scripts/setup_local_macos.sh"
fi

export AV_SAFEPLAN_DEVICE=cpu
export CUDA_VISIBLE_DEVICES=""

exec "${VENV_DIR}/bin/python" \
  "${PROJECT_ROOT}/scripts/validate_local_pipeline.py" \
  "$@"
