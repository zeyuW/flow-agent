#!/usr/bin/env bash
set -euo pipefail

# 安装本地提交前检查，避免手动提交绕过统一验证。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
git config core.hooksPath .githooks
echo "已启用 .githooks 提交检查"
