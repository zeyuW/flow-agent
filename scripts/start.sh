#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT/backend"

exec env \
  -u PYTHONPATH \
  -u AMENT_PREFIX_PATH \
  -u CMAKE_PREFIX_PATH \
  -u COLCON_PREFIX_PATH \
  -u LD_LIBRARY_PATH \
  -u ROS_DISTRO \
  -u ROS_VERSION \
  -u ROS_PYTHON_VERSION \
  -u ROS_LOCALHOST_ONLY \
  uv run python -m bootstrap.main
