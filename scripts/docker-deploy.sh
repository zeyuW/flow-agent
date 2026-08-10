#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

fatal() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：./scripts/docker-deploy.sh [选项]

选项：
  --no-logs   启动后不跟踪日志，命令立即返回
  -h, --help  显示帮助

说明：
  本脚本使用项目根目录已有的 config.toml 和 .flow/。
  .flow/ 已存在时不会删除或覆盖；不存在时才会创建空目录。
  代理使用标准的 HTTP_PROXY、HTTPS_PROXY 和 NO_PROXY 变量即可。
EOF
}

normalize_proxy() {
  local value="${1:-}"
  local proxy_host="${2:-$(resolve_proxy_host)}"
  value="${value//127.0.0.1/$proxy_host}"
  value="${value//localhost/$proxy_host}"
  printf '%s' "$value"
}

is_wsl() {
  grep -qi microsoft /proc/version 2>/dev/null \
    || grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null
}

resolve_proxy_host() {
  local configured_host="${FLOW_AGENT_PROXY_HOST:-}"
  if [[ -n "$configured_host" ]]; then
    printf '%s' "$configured_host"
    return 0
  fi

  if is_wsl; then
    local windows_host
    windows_host="$(awk '$1 == "nameserver" { print $2; exit }' /etc/resolv.conf 2>/dev/null || true)"
    if [[ -n "$windows_host" ]]; then
      printf '%s' "$windows_host"
      return 0
    fi
  fi

  printf 'host.docker.internal'
}

ensure_no_proxy_host() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    printf 'host.docker.internal'
  elif [[ ",$value," == *,host.docker.internal,* ]]; then
    printf '%s' "$value"
  else
    printf '%s,host.docker.internal' "$value"
  fi
}

resolve_proxy_env() {
  local http_proxy_value="${FLOW_AGENT_HTTP_PROXY:-}"
  local https_proxy_value="${FLOW_AGENT_HTTPS_PROXY:-}"
  local no_proxy_value="${FLOW_AGENT_NO_PROXY:-}"

  if [[ -z "$http_proxy_value" ]]; then
    http_proxy_value="${HTTP_PROXY:-${http_proxy:-}}"
  fi
  if [[ -z "$https_proxy_value" ]]; then
    https_proxy_value="${HTTPS_PROXY:-${https_proxy:-}}"
  fi
  if [[ -z "$no_proxy_value" ]]; then
    no_proxy_value="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1}}"
  fi

  export FLOW_AGENT_HTTP_PROXY="$(normalize_proxy "$http_proxy_value")"
  export FLOW_AGENT_HTTPS_PROXY="$(normalize_proxy "$https_proxy_value")"
  export FLOW_AGENT_NO_PROXY="$(ensure_no_proxy_host "$no_proxy_value")"
}

select_compose() {
  if ! docker compose version >/dev/null 2>&1; then
    fatal "未找到 Docker Compose v2，请安装 docker-compose-plugin；旧版 docker-compose 1.x 不兼容当前 Docker Engine。"
  fi
  COMPOSE=(docker compose)
}

main() {
  local follow_logs=1

  while (($# > 0)); do
    case "$1" in
      --no-logs)
        follow_logs=0
        shift
        ;;
      -h|--help)
        usage
        return 0
        ;;
      *)
        usage >&2
        fatal "未知选项：$1"
        ;;
    esac
  done

  if ! command -v docker >/dev/null 2>&1; then
    fatal "未找到 docker，请先安装 Docker。"
  fi
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    fatal "未找到 Compose 文件：$COMPOSE_FILE"
  fi
  if [[ ! -f "$PROJECT_ROOT/config.toml" ]]; then
    fatal "未找到 config.toml，请先在项目根目录创建并填写配置。"
  fi

  resolve_proxy_env
  select_compose
  if ! docker info >/dev/null 2>&1; then
    fatal "Docker daemon 未运行，或当前用户没有访问 Docker socket 的权限。"
  fi

  if [[ -n "$FLOW_AGENT_HTTP_PROXY$FLOW_AGENT_HTTPS_PROXY" ]]; then
    printf '代理：已启用，容器可访问代理主机：%s\n' "$(resolve_proxy_host)"
  else
    printf '代理：未配置，使用直接网络连接\n'
  fi

  if [[ ! -d "$PROJECT_ROOT/.flow" ]]; then
    mkdir -p "$PROJECT_ROOT/.flow"
    printf '已创建运行时目录：%s\n' "$PROJECT_ROOT/.flow"
  else
    printf '使用已有运行时目录：%s\n' "$PROJECT_ROOT/.flow"
  fi

  cd "$PROJECT_ROOT"
  printf '使用 Compose：%s\n' "${COMPOSE[*]}"
  printf '校验 Compose 配置...\n'
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" config >/dev/null

  printf '构建并启动 Flow Agent...\n'
  if ! "${COMPOSE[@]}" -f "$COMPOSE_FILE" up --build --force-recreate --remove-orphans -d; then
    printf '\n部署失败。若错误包含 registry-1.docker.io、timeout 或 network，\n' >&2
    printf '请先检查 Docker Hub 网络、代理或镜像源配置。\n' >&2
    if [[ -n "$FLOW_AGENT_HTTP_PROXY$FLOW_AGENT_HTTPS_PROXY" ]]; then
      printf '当前代理主机为 %s；Windows VPN/代理需要允许来自 WSL/Docker 的局域网连接。\n' \
        "$(resolve_proxy_host)" >&2
    fi
    return 1
  fi

  printf '\n容器状态：\n'
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" ps

  if ((follow_logs)); then
    printf '\n开始跟踪日志；按 Ctrl+C 退出日志查看，不会停止容器。\n\n'
    exec "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs -f flow-agent
  fi

  printf '\n部署完成。查看日志：%s -f %s logs -f flow-agent\n' "${COMPOSE[*]}" "$COMPOSE_FILE"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
