# Repository Guidelines

## Project Structure & Module Organization

Flow Agent 是 Python 智能体服务，采用 `backend/src` 源码布局：

- `backend/src/application/`：业务用例，按 `agent`、`passive`、`proactive`、`memory`、`schedule`、`automation`、`delegation` 和 `capabilities` 划分。
- `backend/src/interfaces/`：Telegram、QQ、HTTP、CLI 等外部渠道适配器。
- `backend/src/infra/`：跨业务通用的配置、消息总线、持久化、日志和运行时设施。
- `backend/src/bootstrap/`：配置加载、依赖装配和 `ServiceApp` 生命周期。
- `backend/tests/`：单元、集成和架构边界测试；`docs/` 保存设计与规格说明。

业务模块内部按需使用 `domain/`、`app/`、`infra/`：领域规则不依赖技术实现，应用层编排用例，业务专属基础设施放在对应模块内。顶层 `infra` 不得依赖 `application`，避免循环依赖。

## Build, Test, and Development Commands

从仓库根目录运行：

```bash
./scripts/start.sh                         # 使用 backend 的 uv 环境启动服务
cd backend && uv run pytest -q              # 运行完整测试套件
cd backend && uv run pytest tests/passive   # 运行指定模块测试
cd backend && uv run black src tests        # 按项目配置格式化
cd backend && uv run pyright                # 执行静态类型检查
```

启动前复制 `config.example.toml` 为根目录的 `config.toml` 并填写模型密钥。运行时数据统一写入根目录 `.flow/`，不要提交密钥、数据库或运行日志。

## Coding Style & Naming Conventions

使用 Python 3.11+、4 个空格缩进和 Black（行宽 88）。模块、函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`。公共包、适配器和关键职责文件应保留简短中文注释；导入方向必须保持单向且清晰。

## Testing Guidelines

测试框架为 pytest，测试文件命名为 `test_*.py`，测试函数命名为 `test_<behavior>`。修改业务行为、生命周期或依赖边界时同步补充测试；项目当前未配置覆盖率门槛，但新代码应覆盖正常路径和失败路径。架构约束测试位于 `backend/tests/architecture/`。

## Commit & Pull Request Guidelines

提交历史使用简短的 Conventional Commit 风格前缀，如 `feat:`、`refactor:`、`docs:`，也可使用清晰的中文摘要。提交应聚焦单一变更。PR 需说明目的、影响的模块和依赖方向，列出配置或数据迁移影响，并附运行过的测试命令；涉及接口或消息行为时补充日志、示例或截图。

## Security & Configuration Tips

不要把 API key、Telegram token 或个人数据写入 Git。使用本地 `config.toml` 和 `.flow/` 保存运行时配置与数据；新增外部渠道或插件时校验来源、权限和输入边界。
