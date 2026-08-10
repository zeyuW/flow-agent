# Docker 部署环境与代理传递设计

## 目标

让仓库克隆者只需执行 `./scripts/docker-deploy.sh` 即可启动 Docker 服务：没有代理时不需要配置任何环境变量；需要代理时可继续使用标准的 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY` 变量。项目内部的 `FLOW_AGENT_*` 变量只作为 Compose 的内部传递层，不作为用户文档要求。

## 当前问题

- 直接执行 `docker compose up` 会绕过部署脚本，导致容器收到空的代理变量。
- WSL/宿主机代理中的 `127.0.0.1` 在容器内指向容器自身，需要转换为 `host.docker.internal`。
- 代理环境变化后，已有容器可能继续使用旧的空环境，需要强制重建。
- Docker 构建阶段的 `pip install` 不会自动继承运行时 `environment`，首次构建在受限网络下可能无法下载依赖。
- 旧版 Python `docker-compose` 与新版 Docker Engine 存在 `ContainerConfig` 兼容性问题。
- 外部 MCP 配置可能使用 `npx`，而 Python 基础镜像默认不包含 Node.js/npm；错误需要在部署阶段明确提示。

## 方案

### 部署入口

`scripts/docker-deploy.sh` 是唯一推荐入口。脚本将：

1. 优先选择 `docker compose` v2；检测到仅有旧版 `docker-compose` 时直接报出安装提示。
2. 从大小写标准代理变量读取配置，并生成仅供当前 Compose 子进程使用的 `FLOW_AGENT_*` 变量。
3. 将代理 URL 中的 `127.0.0.1` 和 `localhost` 转换为 `host.docker.internal`。
4. 确保 `host.docker.internal` 在 `NO_PROXY` 中存在，同时保留用户已有的排除规则。
5. 使用 `--force-recreate` 使代理或其他环境变化立即进入容器。
6. 在 `.flow/mcp.json` 含有 `npx` 命令而镜像不具备 `npx` 时，在启动前输出可操作的提示；不修改用户的 MCP 配置。

### Compose 与构建

Compose 继续使用 `FLOW_AGENT_*` 作为内部变量，并将相同的解析结果传入容器运行时和 Docker 构建参数。Dockerfile 只在依赖安装命令期间使用构建代理参数，不把代理地址固化进最终镜像环境。

### 无代理与兼容性

所有代理变量默认为空。无代理用户不需要设置任何变量。配置文件、`.flow/` 数据和密钥仍由用户本地维护，不写入镜像或 Git。

## 验证

- Shell 语法检查部署脚本。
- 单元测试覆盖代理 URL 转换、标准变量读取、`NO_PROXY` 去重补全和无代理默认行为。
- Compose 配置校验通过。
- 使用代理环境运行部署脚本后，容器内 `HTTP_PROXY` / `HTTPS_PROXY` 指向 `host.docker.internal`。
- 无代理环境运行部署脚本时，容器可启动且代理变量为空。
- 含 `npx` 外部 MCP 配置时，部署输出明确指出缺少运行时依赖。
