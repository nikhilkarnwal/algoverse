#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${AV_SAFEPLAN_LOCAL_PYTHON:-python3}"
VENV_DIR="${AV_SAFEPLAN_LOCAL_VENV:-${PROJECT_ROOT}/.venv-local}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup script is intended for macOS." >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install it with Homebrew: brew install python" >&2
  exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)'; then
  echo "Python 3.8 or newer is required for local validation." >&2
  exit 1
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating local CPU environment at ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check \
  -r "${PROJECT_ROOT}/environments/requirements-local-macos.txt"

echo "Local CPU environment is ready."
echo "Run: ${PROJECT_ROOT}/scripts/run_local_cpu.sh"
