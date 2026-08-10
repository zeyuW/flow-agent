# Flow Agent

Flow Agent 是一个可扩展的多渠道智能体服务，提供对话、工具调用、长期记忆、后台任务和主动消息能力，并支持通过 MCP、插件和技能扩展运行时能力。

## 快速开始

### 1. 拉取仓库

先将项目拉取到本地，再执行后续配置和启动操作：

```bash
git clone https://github.com/zeyuW/flow-agent.git
cd flow-agent
```

### 2. 安装 uv

项目需要 Python 3.11 或更高版本。未安装 uv 时可执行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

确认安装成功：

```bash
uv --version
```

### 3. 创建配置

在仓库根目录执行：

```bash
cp config.example.toml config.toml
```

编辑 `config.toml`，至少填写主模型配置：

```toml
[llm.main]
model = "deepseek-v4-flash"
api_key = ""
base_url = "https://api.deepseek.com/v1"
```


### 4. 启动和停止

从仓库根目录执行：

```bash
./scripts/start.sh
```

### 5. Docker（可选）

Docker 同样读取仓库根目录的 `config.toml`，先完成配置并启用需要的渠道：

```bash
cp config.example.toml config.toml
```

当前 Docker 默认运行 Telegram 主链路；HTTP、CLI 和 dashboard 不会由 Compose 自动开启。

```bash
./scripts/docker-deploy.sh
```

Docker 需要 Compose v2（`docker compose`）。请始终使用上面的部署脚本，不要直接执行 `docker compose up`，否则脚本不会处理代理地址和容器重建。无代理时不需要配置任何环境变量；如果宿主机需要代理，可选设置标准变量：

```bash
export http_proxy=http://127.0.0.1:7892
export https_proxy=http://127.0.0.1:7892
export no_proxy=localhost,127.0.0.1,host.docker.internal
```

在 Linux/WSL2 中，脚本会自动识别 Windows 宿主机地址，把本地代理地址中的 `127.0.0.1` 转换为容器可访问的地址，并将代理同时传入镜像构建和容器运行阶段。Windows VPN/代理必须允许来自 WSL/Docker 的局域网连接；如果软件只监听 Windows 的 `127.0.0.1`，容器仍然无法连接。项目镜像包含 Node.js/npm，可运行 `.flow/mcp.json` 中使用 `npx` 声明的外部 MCP。

脚本会复用已有的 `.flow/`，不会清空本地记忆、数据库或日志；启动后按 `Ctrl+C` 只会退出日志查看，容器仍在后台运行。若不需要跟踪日志，可执行：

```bash
./scripts/docker-deploy.sh --no-logs
```

停止容器：

```bash
docker compose down
```

## 继续阅读

- [文档总索引：按阅读目的选择入口](docs/README.md)
- [系统架构：分层、消息流、生命周期和恢复语义](docs/ARCHITECTURE.md)
- [扩展 API：通过 Plugin、MCP 和 Skill 进行二次开发](docs/api.md)
- [后端开发入口：目录、依赖方向、测试和开发命令](backend/README.md)
- [Agent Loop：共享执行内核和回合生命周期](docs/features/agent-loop.md)
- [被动回复：从用户消息到回复投递](docs/features/passive.md)
- [主动回复：采集、判断、准入和主动投递](docs/features/proactive.md)
- [后台任务：定时、自动化作业和委托子 Agent](docs/features/automation.md)
- [记忆：检索、注入、提取和整理](docs/features/memory.md)
- [渠道：统一适配器、消息规范化和投递](docs/features/channels.md)
- [文档维护规则](docs/knowledge.md)
- [配置示例](config.example.toml)
