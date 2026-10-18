#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec "${PROJECT_ROOT}/scripts/run_behavior_trajectory_ec2.sh" \
  --map Town01 \
  --steps 50 \
  --image-width 640 \
  --image-height 360 \
  --frame-stride 2 \
  "$@"
