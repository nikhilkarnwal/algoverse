#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Stopping any previous CARLA process before the small validation run..."
"${PROJECT_ROOT}/scripts/stop_carla_colab.sh"

exec "${PROJECT_ROOT}/scripts/run_behavior_trajectory_colab.sh" \
  --map Town01 \
  --steps 50 \
  --image-width 640 \
  --image-height 360 \
  --frame-stride 2 \
  "$@"
