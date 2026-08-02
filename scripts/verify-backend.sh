#!/usr/bin/env bash
set -euo pipefail

# 对后端源码、测试和架构边界执行统一验证。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

export PYTHONPATH="${ROOT_DIR}/backend/src${PYTHONPATH:+:${PYTHONPATH}}"
export TMPDIR="${TMPDIR:-/tmp}"

echo "[1/6] 编译后端源码"
"${PYTHON_BIN}" -m compileall -q backend/src

echo "[2/6] 检查空白和冲突标记"
git diff --check
git diff --check --cached

echo "[3/6] 检查项目隔离"
if rg -n -i 'akashic[-_ ]?agent|/home/roco/akashic-agent|参考项目|参考仓库' backend/src backend/tests; then
  echo "检测到不应出现在当前项目中的参考来源信息"
  exit 1
fi

echo "[4/6] 运行后端测试"
if [[ -n "${FLOW_AGENT_TEST_TARGET:-}" ]]; then
  read -r -a test_targets <<< "${FLOW_AGENT_TEST_TARGET}"
  "${PYTHON_BIN}" -m pytest -q "${test_targets[@]}"
else
  "${PYTHON_BIN}" -m pytest -q backend/tests
fi

echo "[5/6] 检查新增架构与配置类型"
python_prefix="$("${PYTHON_BIN}" -c 'import sys; print(sys.prefix)')"
python_env_root="$(dirname "${python_prefix}")"
python_env_name="$(basename "${python_prefix}")"
pyright_config="$(mktemp "${TMPDIR}/flow-agent-pyright.XXXXXX.json")"
trap 'rm -f "${pyright_config}"' EXIT
"${PYTHON_BIN}" -c '
import json
import sys

config_path, venv_path, venv_name, source_path, tests_path = sys.argv[1:]
with open(config_path, "w", encoding="utf-8") as config_file:
    json.dump(
        {
            "venvPath": venv_path,
            "venv": venv_name,
            "extraPaths": [source_path, tests_path],
            "pythonVersion": "3.10",
        },
        config_file,
    )
' "${pyright_config}" "${python_env_root}" "${python_env_name}" \
  "${ROOT_DIR}/backend/src" "${ROOT_DIR}/backend/tests"
"${PYTHON_BIN}" -m pyright --project "${pyright_config}" \
  backend/src/infra/config \
  backend/src/bootstrap \
  backend/tests/architecture \
  backend/tests/infrastructure

echo "[6/6] 检查新增架构与配置格式"
export BLACK_CACHE_DIR="${TMPDIR}/flow-agent-black-cache"
mkdir -p "${BLACK_CACHE_DIR}"
while IFS= read -r file_path; do
  "${PYTHON_BIN}" -m black -W 1 --check --target-version py310 --fast "${file_path}"
done < <(
  rg --files \
    backend/src/infra/config \
    backend/src/bootstrap \
    backend/tests/architecture \
    backend/tests/infrastructure \
  | rg '\.py$'
)

echo "后端验证通过"
