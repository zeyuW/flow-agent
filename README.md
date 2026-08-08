# Flow Agent

Flow Agent 是一个可扩展的多渠道智能体服务，提供对话、工具调用、长期记忆、后台任务和主动消息能力，并支持通过 MCP、插件和技能扩展运行时能力。

## 整体认知

项目由四个顶层部分组成：

- `application`：业务模块和应用用例，描述系统要做什么。
- `interfaces`：Telegram、HTTP、QQ、CLI 等外部渠道适配器。
- `infra`：跨业务共享的配置、消息总线、持久化、日志、并发和安全设施。
- `bootstrap`：组合根，负责加载配置、创建对象、启动服务和有序关闭进程。

业务代码依赖抽象和共享设施，具体实现由 `bootstrap` 在启动时组装。

## 快速开始

### 1. 安装 uv

项目需要 Python 3.11 或更高版本。未安装 uv 时可执行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

确认安装成功：

```bash
uv --version
```

### 2. 创建配置

在仓库根目录执行：

```bash
cp config.example.toml config.toml
```

编辑 `config.toml`，至少填写主模型配置：

```toml
[llm.main]
model = "your-model"
api_key = "your-api-key"
```

OpenAI 兼容服务还需要按实际服务填写 `base_url`。Telegram、HTTP 和主动消息默认关闭，可按需在配置中启用。

### 3. 启动和停止

从仓库根目录执行：

```bash
./scripts/start.sh
```

启动脚本会自动进入 `backend`、清理 ROS 环境变量，并通过 `uv run` 使用后端环境；不需要手动 `source .venv/bin/activate`。按 `Ctrl+C` 停止服务。

### 4. Docker（可选）

```bash
docker compose up --build
```

## 继续阅读

- [后端目录结构、模块职责和依赖方向](backend/README.md)
- [配置示例](config.example.toml)
- [uv 文档](https://docs.astral.sh/uv/)
