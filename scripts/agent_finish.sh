#!/usr/bin/env bash
set -euo pipefail

# 自动完成验证、提交说明生成和提交；文件范围由 Agent 明确传入。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PUSH_AFTER_COMMIT=0
COMMIT_SUMMARY="${FLOW_AGENT_COMMIT_SUMMARY:-}"
COMMIT_DETAILS="${FLOW_AGENT_COMMIT_DETAILS:-}"

while [[ "${1:-}" == --* ]]; do
  case "${1}" in
    --push)
      PUSH_AFTER_COMMIT=1
      shift
      ;;
    --summary)
      [[ "${2:-}" ]] || { echo "--summary 需要提交标题"; exit 2; }
      COMMIT_SUMMARY="${2}"
      shift 2
      ;;
    --details)
      [[ "${2:-}" ]] || { echo "--details 需要改动说明"; exit 2; }
      COMMIT_DETAILS="${2}"
      shift 2
      ;;
    *)
      echo "不支持的参数: ${1}"
      exit 2
      ;;
  esac
done

if [[ "$#" -eq 0 ]]; then
  echo "用法: scripts/agent_finish.sh [--push] [--summary 标题] [--details 说明] <本次修改文件>..."
  echo "为避免误提交用户已有改动，必须显式传入本次修改文件。"
  exit 2
fi

for path in "$@"; do
  case "${path}" in
    backend/*|scripts/*|.github/*|.githooks/*|docs/*|README.md)
      ;;
    *)
      echo "拒绝提交范围外文件: ${path}"
      exit 2
      ;;
  esac
  if [[ ! -e "${path}" ]]; then
    echo "文件不存在: ${path}"
    exit 2
  fi
done

"${ROOT_DIR}/scripts/verify.sh"

git add -f -- "$@"

if git diff --cached --quiet; then
  echo "指定文件没有可提交的改动"
  exit 0
fi

if git diff --cached --unified=0 | rg -n '^+.*(BEGIN [A-Z ]*PRIVATE KEY|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,})'; then
  echo "检测到疑似密钥，已阻止提交"
  git reset -- "$@"
  exit 1
fi

CHANGED_FILES="$(git diff --cached --name-only)"
if [[ -z "${COMMIT_SUMMARY}" ]]; then
  if printf '%s\n' "${CHANGED_FILES}" | rg -q '^backend/src/'; then
    if printf '%s\n' "${CHANGED_FILES}" | rg -q '^backend/tests/'; then
      COMMIT_SUMMARY="feat: 更新 Agent 功能并补充测试"
    else
      COMMIT_SUMMARY="feat: 更新 Agent 功能"
    fi
  elif printf '%s\n' "${CHANGED_FILES}" | rg -q '^backend/tests/'; then
    COMMIT_SUMMARY="test: 更新自动化测试"
  else
    COMMIT_SUMMARY="chore: 更新工程自动化配置"
  fi
fi

if [[ -z "${COMMIT_DETAILS}" ]]; then
  COMMIT_DETAILS=$'自动生成说明：\n'
  while IFS= read -r file; do
    COMMIT_DETAILS+=" - ${file}"$'\n'
  done <<< "${CHANGED_FILES}"
fi
COMMIT_DETAILS+=$'\n验证命令：scripts/verify.sh'

git commit -m "${COMMIT_SUMMARY}" -m "${COMMIT_DETAILS}"

if [[ "${PUSH_AFTER_COMMIT}" -eq 1 || "${FLOW_AGENT_AUTO_PUSH:-0}" == "1" ]]; then
  CURRENT_BRANCH="$(git branch --show-current)"
  git push origin "${CURRENT_BRANCH}"
  echo "已推送到 origin/${CURRENT_BRANCH}，CI 将自动执行"
fi
