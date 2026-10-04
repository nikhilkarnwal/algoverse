#!/usr/bin/env bash
set -euo pipefail

# Reproducible Colab Pro setup for CARLA 0.9.15 + SimLingo inference.
# The managed Colab Python is left untouched; all project commands run inside
# an isolated Python 3.8 micromamba environment.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLAB_ROOT="${AV_SAFEPLAN_COLAB_ROOT:-/content/av_safeplan}"
EXTERNAL_ROOT="${AV_SAFEPLAN_EXTERNAL_ROOT:-${COLAB_ROOT}/external}"
CACHE_ROOT="${AV_SAFEPLAN_CACHE_ROOT:-${COLAB_ROOT}/cache}"
MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${COLAB_ROOT}/micromamba}"
MICROMAMBA_BIN="${MICROMAMBA_BIN:-${COLAB_ROOT}/bin/micromamba}"
ENVIRONMENT_NAME="${AV_SAFEPLAN_ENV_NAME:-av-safeplan-simlingo}"

CARLA_ROOT="${CARLA_ROOT:-${EXTERNAL_ROOT}/carla-0.9.15}"
SIMLINGO_ROOT="${SIMLINGO_ROOT:-${EXTERNAL_ROOT}/simlingo}"
MODEL_ROOT="${AV_SAFEPLAN_MODEL_ROOT:-${EXTERNAL_ROOT}/models/simlingo-official}"
SIMLINGO_CHECKPOINT="${SIMLINGO_CHECKPOINT:-${MODEL_ROOT}/simlingo/checkpoints/epoch=013.ckpt/pytorch_model.pt}"
HF_HOME="${HF_HOME:-${CACHE_ROOT}/huggingface}"
OUTPUT_ROOT="${AV_SAFEPLAN_OUTPUT_ROOT:-${COLAB_ROOT}/outputs/trajectories}"

DOWNLOAD_CARLA="${AV_SAFEPLAN_DOWNLOAD_CARLA:-1}"
DOWNLOAD_ADDITIONAL_MAPS="${AV_SAFEPLAN_DOWNLOAD_ADDITIONAL_MAPS:-1}"
DOWNLOAD_MODELS="${AV_SAFEPLAN_DOWNLOAD_MODELS:-1}"
INSTALL_FLASH_ATTN="${AV_SAFEPLAN_INSTALL_FLASH_ATTN:-1}"
KEEP_DOWNLOAD_ARCHIVES="${AV_SAFEPLAN_KEEP_DOWNLOAD_ARCHIVES:-0}"
CARLA_MIN_FREE_GB="${AV_SAFEPLAN_CARLA_MIN_FREE_GB:-30}"
MAX_JOBS="${MAX_JOBS:-2}"

SIMLINGO_REVISION="743b243afd6cf5ff51b9fa1f8cac86f22d569684"
MODEL_REVISION="26c7c89e797d4e25bbf640013317af8da26a5454"
CARLA_ARCHIVE_URL="https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.15.tar.gz"

export MAMBA_ROOT_PREFIX HF_HOME MAX_JOBS

available_kib() {
  df -Pk "$1" | awk 'NR == 2 {print $4}'
}

require_free_space() {
  local target="$1"
  local required_gb="$2"
  local required_kib=$((required_gb * 1024 * 1024))
  local free_kib
  free_kib="$(available_kib "${target}")"
  if [[ "${free_kib}" -lt "${required_kib}" ]]; then
    echo "Insufficient free disk space for CARLA extraction." >&2
    echo "Required: at least ${required_gb} GiB; available: $((free_kib / 1024 / 1024)) GiB." >&2
    df -h "${target}" >&2
    echo "Keep extracted CARLA files under /content and restart the Colab runtime if old downloads filled the disk." >&2
    exit 1
  fi
}

archive_is_valid() {
  tar -tzf "$1" >/dev/null 2>&1
}

download_tar_archive() {
  local url="$1"
  local archive="$2"

  if [[ -f "${archive}" ]] && archive_is_valid "${archive}"; then
    echo "Using validated archive ${archive}"
    return
  fi

  if [[ -f "${archive}" ]]; then
    echo "Resuming incomplete archive ${archive}"
    if ! curl -L --fail --retry 3 --continue-at - -o "${archive}" "${url}"; then
      echo "Resume failed. Remove ${archive} and rerun setup." >&2
      exit 1
    fi
  else
    curl -L --fail --retry 3 -o "${archive}" "${url}"
  fi

  if ! archive_is_valid "${archive}"; then
    echo "Archive validation failed: ${archive}" >&2
    echo "Remove that file, ensure enough free disk space, and rerun setup." >&2
    exit 1
  fi
}

extract_carla_base() {
  local archive="$1"
  local staging_root="${CARLA_ROOT}.extracting"

  if [[ -e "${CARLA_ROOT}" ]]; then
    echo "An incomplete or unverified CARLA directory already exists:" >&2
    echo "  ${CARLA_ROOT}" >&2
    echo "Inspect it, then remove or rename it before rerunning setup." >&2
    exit 1
  fi
  if [[ -e "${staging_root}" ]]; then
    echo "A previous CARLA staging directory already exists:" >&2
    echo "  ${staging_root}" >&2
    echo "Inspect it, then remove or rename it before rerunning setup." >&2
    exit 1
  fi

  mkdir -p "${staging_root}"
  echo "Extracting CARLA into ${staging_root}..."
  if ! tar -xzf "${archive}" -C "${staging_root}"; then
    echo "CARLA extraction failed. The partial files remain at:" >&2
    echo "  ${staging_root}" >&2
    df -h "${staging_root}" >&2
    echo "Free disk space, remove or rename that staging directory, and rerun setup." >&2
    exit 1
  fi
  mv "${staging_root}" "${CARLA_ROOT}"

  if [[ ! -x "${CARLA_ROOT}/CarlaUE4.sh" ]]; then
    echo "CARLA archive extracted but CarlaUE4.sh is missing." >&2
    exit 1
  fi
}

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Colab setup requires a Linux runtime." >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "No NVIDIA runtime detected. In Colab select Runtime > Change runtime type > GPU." >&2
  exit 1
fi

echo "GPU runtime:"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
GPU_MEMORY_MIB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sed -n '1p')"
if [[ "${GPU_MEMORY_MIB}" -lt 20000 ]]; then
  echo "Warning: ${GPU_MEMORY_MIB} MiB of GPU memory may be tight for CARLA and SimLingo together." >&2
  echo "Use low-quality CARLA rendering, short routes, and prefer an L4/A100 runtime when available." >&2
fi

if [[ "${DOWNLOAD_CARLA}" == "1" && ! -f "${CARLA_ROOT}/.av-safeplan-install-complete" ]]; then
  mkdir -p "$(dirname "${CARLA_ROOT}")"
  require_free_space "$(dirname "${CARLA_ROOT}")" "${CARLA_MIN_FREE_GB}"
  if [[ -e "${CARLA_ROOT}" || -e "${CARLA_ROOT}.extracting" ]]; then
    echo "A previous CARLA installation or staging directory is incomplete:" >&2
    echo "  ${CARLA_ROOT}" >&2
    echo "  ${CARLA_ROOT}.extracting" >&2
    echo "Inspect those paths, then remove or rename the incomplete one and rerun setup." >&2
    exit 1
  fi
fi

mkdir -p "${COLAB_ROOT}/bin" "${EXTERNAL_ROOT}" "${CACHE_ROOT}" "${HF_HOME}" "${OUTPUT_ROOT}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  bzip2 \
  curl \
  git \
  libglib2.0-0 \
  libjpeg-turbo8 \
  libomp5 \
  libpng16-16 \
  libsdl2-2.0-0 \
  libtiff5 \
  libvulkan1 \
  mesa-vulkan-drivers \
  netcat-openbsd \
  passwd \
  util-linux \
  vulkan-tools \
  xdg-user-dirs

if [[ ! -x "${MICROMAMBA_BIN}" ]]; then
  echo "Installing micromamba..."
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xj -C "${COLAB_ROOT}/bin" --strip-components=1 bin/micromamba
fi

if ! "${MICROMAMBA_BIN}" env list | awk '{print $1}' | grep -qx "${ENVIRONMENT_NAME}"; then
  echo "Creating isolated Python 3.8 environment..."
  "${MICROMAMBA_BIN}" create -y -n "${ENVIRONMENT_NAME}" \
    -c conda-forge \
    python=3.8.18 pip=23.3.1 setuptools=68.2.2 wheel=0.41.2
fi

run_in_env() {
  "${MICROMAMBA_BIN}" run -n "${ENVIRONMENT_NAME}" "$@"
}

echo "Installing the pinned CUDA 12.1 PyTorch stack..."
run_in_env python -m pip install --no-cache-dir \
  torch==2.2.0 torchvision==0.17.0 torchaudio==2.2.0 \
  --index-url https://download.pytorch.org/whl/cu121

echo "Installing SimLingo runtime dependencies..."
run_in_env python -m pip install --no-cache-dir \
  -r "${PROJECT_ROOT}/environments/requirements-colab.txt"

if [[ "${INSTALL_FLASH_ATTN}" == "1" ]]; then
  if ! command -v nvcc >/dev/null 2>&1; then
    echo "CUDA compiler nvcc is unavailable; Flash Attention cannot be built." >&2
    echo "Select a Colab GPU runtime that exposes the CUDA toolkit, or set AV_SAFEPLAN_INSTALL_FLASH_ATTN=0." >&2
    exit 1
  fi
  echo "Building Flash Attention against the pinned PyTorch/CUDA stack..."
  run_in_env python -m pip install --no-cache-dir \
    flash-attn==2.7.0.post2 --no-build-isolation
fi

run_in_env python -m pip install --no-deps -e "${PROJECT_ROOT}"

if [[ ! -d "${SIMLINGO_ROOT}/.git" ]]; then
  echo "Cloning SimLingo..."
  git clone https://github.com/RenzKa/simlingo.git "${SIMLINGO_ROOT}"
fi
git -C "${SIMLINGO_ROOT}" fetch --depth 1 origin "${SIMLINGO_REVISION}"
git -C "${SIMLINGO_ROOT}" checkout --detach "${SIMLINGO_REVISION}"

if [[ "${DOWNLOAD_CARLA}" == "1" && ! -f "${CARLA_ROOT}/.av-safeplan-install-complete" ]]; then
  echo "Installing CARLA 0.9.15..."
  mkdir -p "${CACHE_ROOT}/carla"

  CARLA_ARCHIVE="${CACHE_ROOT}/carla/CARLA_0.9.15.tar.gz"
  download_tar_archive "${CARLA_ARCHIVE_URL}" "${CARLA_ARCHIVE}"
  extract_carla_base "${CARLA_ARCHIVE}"

  if [[ "${KEEP_DOWNLOAD_ARCHIVES}" != "1" ]]; then
    rm -f -- "${CARLA_ARCHIVE}"
  fi

  touch "${CARLA_ROOT}/.av-safeplan-install-complete"
fi

if [[ "${DOWNLOAD_ADDITIONAL_MAPS}" == "1" ]]; then
  CARLA_ROOT="${CARLA_ROOT}" \
  CARLA_PORT="${CARLA_PORT:-2000}" \
  AV_SAFEPLAN_KEEP_DOWNLOAD_ARCHIVES="${KEEP_DOWNLOAD_ARCHIVES}" \
    "${PROJECT_ROOT}/scripts/install_carla_maps_colab.sh"
fi

if [[ "${DOWNLOAD_MODELS}" == "1" ]]; then
  echo "Downloading the pinned SimLingo inference checkpoint..."
  mkdir -p "${MODEL_ROOT}"
  run_in_env huggingface-cli download RenzKa/simlingo \
    --revision "${MODEL_REVISION}" \
    --include "simlingo/.hydra/*" "simlingo/checkpoints/epoch=013.ckpt/pytorch_model.pt" \
    --local-dir "${MODEL_ROOT}"

  echo "Caching InternVL2-1B..."
  run_in_env huggingface-cli download OpenGVLab/InternVL2-1B
fi

cat > "${PROJECT_ROOT}/.env" <<EOF
CARLA_ROOT=${CARLA_ROOT}
SIMLINGO_ROOT=${SIMLINGO_ROOT}
SIMLINGO_CHECKPOINT=${SIMLINGO_CHECKPOINT}
HF_HOME=${HF_HOME}
MAMBA_ROOT_PREFIX=${MAMBA_ROOT_PREFIX}
MICROMAMBA_BIN=${MICROMAMBA_BIN}
AV_SAFEPLAN_ENV_NAME=${ENVIRONMENT_NAME}
AV_SAFEPLAN_OUTPUT_ROOT=${OUTPUT_ROOT}
CARLA_HOST=127.0.0.1
CARLA_PORT=2000
CARLA_TRAFFIC_MANAGER_PORT=8000
EOF

echo
echo "Colab setup completed."
echo "Run project commands with:"
echo "  ${PROJECT_ROOT}/scripts/colab_run.sh python ${PROJECT_ROOT}/scripts/verify_stack.py"
echo "Start CARLA with:"
echo "  ${PROJECT_ROOT}/scripts/start_carla_colab.sh"
echo "Record a Behavior Agent trajectory with:"
echo "  ${PROJECT_ROOT}/scripts/run_behavior_trajectory_colab.sh"
