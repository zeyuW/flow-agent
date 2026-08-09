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

```bash
docker compose up --build
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
