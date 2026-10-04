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
MAPS_URL="https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/AdditionalMaps_0.9.15.tar.gz"
MAPS_ARCHIVE="${CARLA_ROOT}/Import/AdditionalMaps_0.9.15.tar.gz"
MAPS_MARKER="${CARLA_ROOT}/.av-safeplan-additional-maps-complete"
MAPS_MIN_FREE_GB="${AV_SAFEPLAN_MAPS_MIN_FREE_GB:-20}"
KEEP_ARCHIVE="${AV_SAFEPLAN_KEEP_DOWNLOAD_ARCHIVES:-0}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "CARLA map installation requires Linux/Colab." >&2
  exit 1
fi
if [[ ! -x "${CARLA_ROOT}/ImportAssets.sh" ]]; then
  echo "CARLA base installation is missing at ${CARLA_ROOT}." >&2
  exit 1
fi
if [[ -f "${MAPS_MARKER}" ]]; then
  echo "CARLA additional maps are already marked as installed."
  exit 0
fi

if nc -z 127.0.0.1 "${CARLA_PORT}" >/dev/null 2>&1; then
  echo "Stopping CARLA before importing map assets..."
  "${PROJECT_ROOT}/scripts/stop_carla_colab.sh"
fi

FREE_KIB="$(df -Pk "${CARLA_ROOT}" | awk 'NR == 2 {print $4}')"
REQUIRED_KIB=$((MAPS_MIN_FREE_GB * 1024 * 1024))
if [[ "${FREE_KIB}" -lt "${REQUIRED_KIB}" ]]; then
  echo "Insufficient disk space for CARLA additional maps." >&2
  echo "Required: ${MAPS_MIN_FREE_GB} GiB; available: $((FREE_KIB / 1024 / 1024)) GiB." >&2
  df -h "${CARLA_ROOT}" >&2
  exit 1
fi

mkdir -p "${CARLA_ROOT}/Import"
if [[ -f "${MAPS_ARCHIVE}" ]] && tar -tzf "${MAPS_ARCHIVE}" >/dev/null 2>&1; then
  echo "Using validated map archive ${MAPS_ARCHIVE}"
else
  echo "Downloading CARLA 0.9.15 additional maps..."
  if [[ -f "${MAPS_ARCHIVE}" ]]; then
    curl -L --fail --retry 3 --continue-at - -o "${MAPS_ARCHIVE}" "${MAPS_URL}"
  else
    curl -L --fail --retry 3 -o "${MAPS_ARCHIVE}" "${MAPS_URL}"
  fi
  if ! tar -tzf "${MAPS_ARCHIVE}" >/dev/null 2>&1; then
    echo "Additional Maps archive validation failed: ${MAPS_ARCHIVE}" >&2
    echo "Remove that file and rerun this script to download a clean copy." >&2
    exit 1
  fi
fi

echo "Importing CARLA additional maps. This can take several minutes..."
# CARLA 0.9.15's ImportAssets.sh uses --keep-newer-files. The official
# Additional Maps archive overlaps files from the base package, so GNU tar
# reports those harmless overlaps as errors. --skip-old-files preserves the
# installed base files without turning duplicates into a failed import.
tar --skip-old-files --no-same-owner -xzf "${MAPS_ARCHIVE}" -C "${CARLA_ROOT}"

if ! find "${CARLA_ROOT}/CarlaUE4/Content" -iname '*Town12*' -print -quit | grep -q .; then
  echo "Map import completed but Town12 assets were not found." >&2
  exit 1
fi

touch "${MAPS_MARKER}"
if [[ "${KEEP_ARCHIVE}" != "1" ]]; then
  rm -f -- "${MAPS_ARCHIVE}"
fi
echo "Town12 assets installed successfully."
