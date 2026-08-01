#!/usr/bin/env bash
set -euo pipefail

# 保留统一入口，具体检查集中在后端验证脚本中。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "${ROOT_DIR}/scripts/verify-backend.sh"
