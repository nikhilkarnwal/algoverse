#!/usr/bin/env bash
set -euo pipefail

# Add CARLA 0.9.15's Additional Maps to a reusable local Docker image. The
# derived image remains on the persistent EBS volume between EC2 sessions.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/ec2_docker_common.sh"

BASE_IMAGE="${AV_SAFEPLAN_CARLA_BASE_IMAGE:-carlasim/carla:0.9.15}"
TOWN12_IMAGE="${AV_SAFEPLAN_TOWN12_IMAGE:-av-safeplan/carla:0.9.15-town12}"
MAPS_URL="${AV_SAFEPLAN_MAPS_URL:-https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/AdditionalMaps_0.9.15.tar.gz}"
RUNTIME_ROOT="${AV_SAFEPLAN_EC2_ROOT:-$(dirname "${MAMBA_ROOT_PREFIX}")}"
CACHE_ROOT="${AV_SAFEPLAN_CACHE_ROOT:-${RUNTIME_ROOT}/cache/carla}"
MAPS_ARCHIVE="${CACHE_ROOT}/AdditionalMaps_0.9.15.tar.gz"
MIN_FREE_GB="${AV_SAFEPLAN_TOWN12_MIN_FREE_GB:-35}"
KEEP_ARCHIVE="${AV_SAFEPLAN_KEEP_DOWNLOAD_ARCHIVES:-0}"
BUILDER_NAME="av-safeplan-town12-builder"

cleanup() {
  docker_command rm --force "${BUILDER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

set_ec2_image() {
  local temporary_file
  temporary_file="$(mktemp "${EC2_ENV_FILE}.XXXXXX")"
  awk -v image="${TOWN12_IMAGE}" '
    BEGIN { replaced = 0 }
    /^CARLA_DOCKER_IMAGE=/ {
      if (!replaced) {
        print "CARLA_DOCKER_IMAGE=" image
        replaced = 1
      }
      next
    }
    { print }
    END {
      if (!replaced) {
        print "CARLA_DOCKER_IMAGE=" image
      }
    }
  ' "${EC2_ENV_FILE}" > "${temporary_file}"
  mv "${temporary_file}" "${EC2_ENV_FILE}"
}

if docker_command image inspect "${TOWN12_IMAGE}" >/dev/null 2>&1 \
  && [[ "$(docker_command image inspect --format '{{ index .Config.Labels "org.av-safeplan.maps" }}' "${TOWN12_IMAGE}")" == "Town12" ]]; then
  echo "Town12 Docker image already exists: ${TOWN12_IMAGE}"
  set_ec2_image
  echo "Configured ${EC2_ENV_FILE} to use it."
  exit 0
fi

mkdir -p "${CACHE_ROOT}"
FREE_KIB="$(df -Pk "${CACHE_ROOT}" | awk 'NR == 2 {print $4}')"
REQUIRED_KIB=$((MIN_FREE_GB * 1024 * 1024))
if [[ "${FREE_KIB}" -lt "${REQUIRED_KIB}" ]]; then
  echo "Insufficient disk space to build the Town12 image." >&2
  echo "Required: ${MIN_FREE_GB} GiB; available: $((FREE_KIB / 1024 / 1024)) GiB." >&2
  df -h "${CACHE_ROOT}" >&2
  exit 1
fi

if [[ -f "${MAPS_ARCHIVE}" ]] && tar -tzf "${MAPS_ARCHIVE}" >/dev/null 2>&1; then
  echo "Using validated map archive ${MAPS_ARCHIVE}"
else
  echo "Downloading CARLA 0.9.15 Additional Maps. Interrupted downloads resume."
  curl -L --fail --retry 3 --continue-at - \
    --output "${MAPS_ARCHIVE}" \
    "${MAPS_URL}"
  if ! tar -tzf "${MAPS_ARCHIVE}" >/dev/null 2>&1; then
    echo "Additional Maps archive validation failed: ${MAPS_ARCHIVE}" >&2
    echo "Remove that file and rerun this script to download a clean copy." >&2
    exit 1
  fi
fi

echo "Creating reusable Town12 image ${TOWN12_IMAGE}..."
docker_command pull "${BASE_IMAGE}"
cleanup
docker_command run \
  --detach \
  --name "${BUILDER_NAME}" \
  --volume "${MAPS_ARCHIVE}:/tmp/AdditionalMaps_0.9.15.tar.gz:ro" \
  "${BASE_IMAGE}" \
  /bin/bash -lc 'sleep infinity' \
  >/dev/null

# Additional Maps overlaps a few base-package files. Preserve the base copies
# while extracting only the missing assets, matching the working Colab path.
docker_command exec --user 0 "${BUILDER_NAME}" \
  tar --skip-old-files --no-same-owner \
  -xzf /tmp/AdditionalMaps_0.9.15.tar.gz \
  -C /home/carla

if ! docker_command exec "${BUILDER_NAME}" \
  find /home/carla/CarlaUE4/Content -iname '*Town12*' -print -quit \
  | grep -q .; then
  echo "Map extraction completed, but Town12 assets were not found." >&2
  exit 1
fi

docker_command commit \
  --change 'USER carla' \
  --change 'WORKDIR /home/carla' \
  --change 'LABEL org.av-safeplan.carla-version="0.9.15"' \
  --change 'LABEL org.av-safeplan.maps="Town12"' \
  "${BUILDER_NAME}" \
  "${TOWN12_IMAGE}" \
  >/dev/null
set_ec2_image

if [[ "${KEEP_ARCHIVE}" != "1" ]]; then
  rm -f -- "${MAPS_ARCHIVE}"
fi

echo "Town12 image is ready: ${TOWN12_IMAGE}"
echo "EC2 configuration updated: ${EC2_ENV_FILE}"
echo "Next command: ./scripts/run_week1_behavior_validation_ec2.sh"
