#!/usr/bin/env bash
set -euo pipefail

# Install SimLingo separately from the lightweight Behavior Agent environment.
# Run --source first; --runtime and --models are deliberately opt-in.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EC2_ENV_FILE="${AV_SAFEPLAN_EC2_ENV_FILE:-${PROJECT_ROOT}/.env.ec2}"
if [[ ! -f "${EC2_ENV_FILE}" ]]; then
  echo "Missing ${EC2_ENV_FILE}; run setup_ec2_docker.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "${EC2_ENV_FILE}"

STAGE="${1:---source}"
case "${STAGE}" in
  --source|--runtime|--models) ;;
  *) echo "Usage: $0 [--source|--runtime|--models]" >&2; exit 2 ;;
esac

RUNTIME_ROOT="${AV_SAFEPLAN_EC2_ROOT:-${HOME}/av-safeplan-runtime}"
SIMLINGO_ROOT="${SIMLINGO_ROOT:-${RUNTIME_ROOT}/external/simlingo}"
MODEL_ROOT="${AV_SAFEPLAN_MODEL_ROOT:-${RUNTIME_ROOT}/external/models/simlingo-official}"
SIMLINGO_CHECKPOINT="${MODEL_ROOT}/simlingo/checkpoints/epoch=013.ckpt/pytorch_model.pt"
SIMLINGO_ENV_NAME="${AV_SAFEPLAN_SIMLINGO_ENV_NAME:-av-safeplan-simlingo}"
HF_HOME="${HF_HOME:-${RUNTIME_ROOT}/cache/huggingface}"
SIMLINGO_REVISION="743b243afd6cf5ff51b9fa1f8cac86f22d569684"
MODEL_REVISION="26c7c89e797d4e25bbf640013317af8da26a5454"
export MAMBA_ROOT_PREFIX HF_HOME

require_free_gib() {
  local required_gib="$1"
  local free_kib
  free_kib="$(df -Pk "${RUNTIME_ROOT}" | awk 'NR == 2 {print $4}')"
  if (( free_kib < required_gib * 1024 * 1024 )); then
    echo "Need at least ${required_gib} GiB free on persistent EC2 storage." >&2
    df -h "${RUNTIME_ROOT}" >&2
    exit 1
  fi
}

write_environment_file() {
  # This contains paths only. Keep the Behavior Agent's .env.ec2 unchanged.
  cat > "${PROJECT_ROOT}/.env.simlingo.ec2" <<EOF
SIMLINGO_ROOT=${SIMLINGO_ROOT}
SIMLINGO_CHECKPOINT=${SIMLINGO_CHECKPOINT}
HF_HOME=${HF_HOME}
AV_SAFEPLAN_SIMLINGO_ENV_NAME=${SIMLINGO_ENV_NAME}
EOF
}

mkdir -p "${RUNTIME_ROOT}/external" "${HF_HOME}"

if [[ "${STAGE}" == "--source" ]]; then
  if [[ ! -d "${SIMLINGO_ROOT}/.git" ]]; then
    if [[ -e "${SIMLINGO_ROOT}" ]]; then
      echo "Existing non-Git path at ${SIMLINGO_ROOT}; inspect it first." >&2
      exit 1
    fi
    git clone --filter=blob:none --no-checkout \
      https://github.com/RenzKa/simlingo.git "${SIMLINGO_ROOT}"
  fi
  git -C "${SIMLINGO_ROOT}" fetch --depth 1 origin "${SIMLINGO_REVISION}"
  git -C "${SIMLINGO_ROOT}" checkout --detach "${SIMLINGO_REVISION}"
  echo "Pinned SimLingo source: $(git -C "${SIMLINGO_ROOT}" rev-parse HEAD)"
  write_environment_file
  exit 0
fi

if [[ ! -f "${SIMLINGO_ROOT}/team_code/agent_simlingo.py" ]]; then
  echo "Run $0 --source before ${STAGE}." >&2
  exit 1
fi

if [[ "${STAGE}" == "--runtime" ]]; then
  require_free_gib 20
  if [[ ! -x "${MICROMAMBA_BIN}" ]]; then
    echo "micromamba is missing at ${MICROMAMBA_BIN}." >&2
    exit 1
  fi
  if ! "${MICROMAMBA_BIN}" env list | awk '{print $1}' | grep -qx "${SIMLINGO_ENV_NAME}"; then
    "${MICROMAMBA_BIN}" create -y -n "${SIMLINGO_ENV_NAME}" \
      -c conda-forge python=3.8.18 pip=23.3.1 setuptools=68.2.2 wheel=0.41.2
  fi
  run_in_env() { "${MICROMAMBA_BIN}" run -n "${SIMLINGO_ENV_NAME}" "$@"; }
  # DeepSpeed probes CUDA_HOME while preparing package metadata, before Flash
  # Attention is built. Keep nvcc and its environment scope isolated here.
  "${MICROMAMBA_BIN}" install -y -n "${SIMLINGO_ENV_NAME}" \
    -c nvidia/label/cuda-12.1.1 -c conda-forge cuda-nvcc=12.1
  CUDA_HOME="${MAMBA_ROOT_PREFIX}/envs/${SIMLINGO_ENV_NAME}"
  export CUDA_HOME MAX_JOBS="${MAX_JOBS:-2}"
  if [[ ! -x "${CUDA_HOME}/bin/nvcc" ]]; then
    echo "CUDA compiler is unavailable in ${CUDA_HOME}." >&2
    exit 1
  fi
  run_in_env python -m pip install --no-cache-dir \
    torch==2.2.0 torchvision==0.17.0 torchaudio==2.2.0 \
    --index-url https://download.pytorch.org/whl/cu121
  run_in_env python -m pip install --no-cache-dir \
    -r "${PROJECT_ROOT}/environments/requirements-colab.txt"
  run_in_env python -m pip install --no-cache-dir \
    flash-attn==2.7.0.post2 --no-build-isolation
  run_in_env python -m pip install --no-deps -e "${PROJECT_ROOT}"
  write_environment_file
  echo "SimLingo runtime installed without starting CARLA."
  exit 0
fi

require_free_gib 8
if ! "${MICROMAMBA_BIN}" env list | awk '{print $1}' | grep -qx "${SIMLINGO_ENV_NAME}"; then
  echo "Run $0 --runtime before --models." >&2
  exit 1
fi
mkdir -p "${MODEL_ROOT}"
"${MICROMAMBA_BIN}" run -n "${SIMLINGO_ENV_NAME}" \
  huggingface-cli download RenzKa/simlingo \
  --revision "${MODEL_REVISION}" \
  --include "simlingo/.hydra/*" "simlingo/checkpoints/epoch=013.ckpt/pytorch_model.pt" \
  --local-dir "${MODEL_ROOT}"
"${MICROMAMBA_BIN}" run -n "${SIMLINGO_ENV_NAME}" \
  huggingface-cli download OpenGVLab/InternVL2-1B
if [[ ! -s "${SIMLINGO_CHECKPOINT}" ]]; then
  echo "Checkpoint download did not create ${SIMLINGO_CHECKPOINT}." >&2
  exit 1
fi
write_environment_file
echo "SimLingo inference models are cached; CARLA was not started."
