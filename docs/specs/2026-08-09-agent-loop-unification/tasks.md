# Agent Loop 与 application 目录重构实施记录

## 已完成

- [x] 将 `conversation` 重命名为 `passive`；
- [x] 将 `scheduling` 重命名为 `schedule`；
- [x] 将 `tasks` 重命名为 `automation`；
- [x] 将通用 Agent 执行能力收敛到 `application/agent`；
- [x] 将生产消息循环统一为 `application/agent/app/loop.py:AgentLoop`；
- [x] 增加 `application/passive/app/passive_loop.py`，负责被动消息转换；
- [x] 删除旧的 `agent_loop.py`、`runner.py` 和 `bootstrap/workspace.py`；
- [x] 将入站总线消息模型移动到 `infra/bus/types.py`；
- [x] 将插件作业声明模型移动到 `capabilities/plugins`，消除插件与自动化模块的循环依赖；
- [x] 增加 application 导入图架构测试。

## 后续工作

- [ ] 将 Skills 正式注入被动 Agent 的 PromptRender 阶段；
- [ ] 进一步细化 `schedule` 和 `automation` 的应用服务命名；
- [ ] 补充 AgentLoop 的 `join()` 显式生命周期接口；
- [ ] 完成全量测试和运行时启动验证。
