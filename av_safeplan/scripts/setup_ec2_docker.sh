#!/usr/bin/env bash
set -euo pipefail

# Lightweight, persistent EC2 setup for CARLA-in-Docker plus the host-side
# Behavior Agent client. Town12 and SimLingo are deliberately separate phases.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${AV_SAFEPLAN_EC2_ROOT:-${HOME}/av-safeplan-runtime}"
EXTERNAL_ROOT="${AV_SAFEPLAN_EXTERNAL_ROOT:-${RUNTIME_ROOT}/external}"
OUTPUT_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT:-${RUNTIME_ROOT}/outputs/trajectories}"
MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${RUNTIME_ROOT}/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-${RUNTIME_ROOT}/bin/micromamba}"
ENVIRONMENT_NAME="${AV_SAFEPLAN_ENV_NAME:-av-safeplan-behavior}"
CARLA_PYTHON_ROOT="${CARLA_ROOT:-${EXTERNAL_ROOT}/carla-0.9.15-pythonapi}"
CARLA_DOCKER_IMAGE="${CARLA_DOCKER_IMAGE:-carlasim/carla:0.9.15}"
CARLA_DOCKER_NAME="${CARLA_DOCKER_NAME:-av-safeplan-carla}"
EC2_ENV_FILE="${AV_SAFEPLAN_EC2_ENV_FILE:-${PROJECT_ROOT}/.env.ec2}"

export MAMBA_ROOT_PREFIX

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "The EC2 Docker setup requires Linux." >&2
  exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi is unavailable; use an EC2 GPU instance with an NVIDIA DLAMI." >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is unavailable. Install Docker before running this setup." >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
  echo "curl and git are required." >&2
  exit 1
fi

if docker info >/dev/null 2>&1; then
  DOCKER_COMMAND=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER_COMMAND=(sudo docker)
else
  echo "Docker is installed but cannot be accessed by this user." >&2
  echo "Confirm Docker is running and passwordless sudo is available." >&2
  exit 1
fi

echo "GPU runtime:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

mkdir -p \
  "${RUNTIME_ROOT}/bin" \
  "${EXTERNAL_ROOT}" \
  "${OUTPUT_ROOT}"

if [[ ! -x "${MICROMAMBA_BIN}" ]]; then
  echo "Installing micromamba under the persistent EBS-backed home directory..."
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xj -C "${RUNTIME_ROOT}/bin" --strip-components=1 bin/micromamba
fi

if ! "${MICROMAMBA_BIN}" env list | awk '{print $1}' | grep -qx "${ENVIRONMENT_NAME}"; then
  echo "Creating the lightweight Python 3.8 Behavior Agent environment..."
  "${MICROMAMBA_BIN}" create -y -n "${ENVIRONMENT_NAME}" \
    -c conda-forge \
    python=3.8.18 pip=23.3.1 setuptools=68.2.2 wheel=0.41.2
fi

run_in_env() {
  "${MICROMAMBA_BIN}" run -n "${ENVIRONMENT_NAME}" "$@"
}

echo "Installing the Behavior Agent client dependencies..."
run_in_env python -m pip install --no-cache-dir \
  -r "${PROJECT_ROOT}/environments/requirements-ec2-behavior.txt"
run_in_env python -m pip install --no-deps -e "${PROJECT_ROOT}"

if [[ ! -d "${CARLA_PYTHON_ROOT}/.git" ]]; then
  echo "Fetching CARLA 0.9.15 Behavior Agent sources..."
  git clone \
    --depth 1 \
    --branch 0.9.15 \
    --filter=blob:none \
    --sparse \
    https://github.com/carla-simulator/carla.git \
    "${CARLA_PYTHON_ROOT}"
  git -C "${CARLA_PYTHON_ROOT}" sparse-checkout set PythonAPI/carla/agents
fi

if [[ ! -f "${CARLA_PYTHON_ROOT}/PythonAPI/carla/agents/navigation/behavior_agent.py" ]]; then
  echo "CARLA Behavior Agent sources are incomplete at ${CARLA_PYTHON_ROOT}." >&2
  exit 1
fi

echo "Ensuring the official CARLA image is available..."
"${DOCKER_COMMAND[@]}" pull "${CARLA_DOCKER_IMAGE}"

cat > "${EC2_ENV_FILE}" <<EOF
CARLA_ROOT=${CARLA_PYTHON_ROOT}
MAMBA_ROOT_PREFIX=${MAMBA_ROOT_PREFIX}
MICROMAMBA_BIN=${MICROMAMBA_BIN}
AV_SAFEPLAN_ENV_NAME=${ENVIRONMENT_NAME}
AV_SAFEPLAN_OUTPUT_ROOT=${OUTPUT_ROOT}
CARLA_DOCKER_IMAGE=${CARLA_DOCKER_IMAGE}
CARLA_DOCKER_NAME=${CARLA_DOCKER_NAME}
CARLA_HOST=127.0.0.1
CARLA_PORT=2000
CARLA_TRAFFIC_MANAGER_PORT=8000
CARLA_STARTUP_TIMEOUT_SECONDS=180
CARLA_MAP_LOAD_TIMEOUT_SECONDS=300
EOF

echo
echo "EC2 Behavior Agent setup completed."
echo "Persistent runtime: ${RUNTIME_ROOT}"
echo "Trajectory output:  ${OUTPUT_ROOT}"
echo "Next command:"
echo "  ./scripts/run_small_trajectory_ec2.sh --no-images --steps 20"
