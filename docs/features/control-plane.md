# 管理控制台与本机 API

## 一句话定位

管理面是 Flow Agent 的本机运维入口：后端提供绑定到 `127.0.0.1:8790` 的管理 API，
前端通过 Next.js 代理同源 `/api` 请求，展示会话、追踪、事件和扩展状态，并执行
定时任务、MCP 服务和用户 Skill 的受控管理操作。

它不是用户消息渠道，也不参与 Agent 回合的模型推理、工具循环或消息投递。

## 组成和数据流

```text
Flow Agent ServiceApp
        |
        +--> TraceTimeline <---- EventBus
        +--> SessionQueryService
        +--> SchedulerService
        +--> CapabilityQueryService
        +--> SkillInstaller / McpServerRegistry
        |                         |
        v                         v
  AdminServer 127.0.0.1:8790  <--  /api
        ^
        |
  Next.js server proxy
        ^
        |
  Web 控制台 http://localhost:3000
```

`ServiceApp.init()` 创建管理查询服务和 `TraceTimeline`，并订阅 `EventBus`；
`ServiceApp.start()` 启动管理服务器。停止时先停止管理服务器并等待其线程退出，
再释放其他运行时资源。管理面读取的是运行时服务的查询接口，不直接打开 SQLite
或日志文件。

## 控制台页面

前端当前提供以下页面：

- **会话**：按日期列出会话，查看消息、角色、时间和工具链摘要；
- **定时任务**：查看、新建、停止和恢复定时任务；
- **技能与连接器**：读取能力快照，扫描/安装/卸载用户 Skill，保存或启停 MCP 服务；
- **插件**：展示插件相关运行信息；
- **日志**：查看运行记录、阶段事件和单次追踪详情。

前端只保存查询结果和页面状态。模型密钥、渠道 Token、用户数据和运行时数据库
仍由后端及其工作区负责。

## API 路由

所有路由前缀都是 `/api`。请求体以 JSON 编码，成功响应遵循各路由的 Pydantic
schema；错误使用 HTTP 状态码和 `detail` 字段说明原因。

| 方法 | 路径 | 作用 | 是否改变状态 |
| --- | --- | --- | --- |
| GET | `/api/capabilities` | 查询 Skill 与连接器能力快照 | 否 |
| GET | `/api/mcp/servers` | 列出已配置 MCP 服务 | 否 |
| PUT | `/api/mcp/servers/{name}` | 新增或更新 MCP 服务配置 | 是 |
| DELETE | `/api/mcp/servers/{name}` | 删除 MCP 服务配置 | 是 |
| POST | `/api/mcp/servers/{name}/enabled` | 启用或停用 MCP 服务 | 是 |
| POST | `/api/skills/scan` | 扫描远程 Skill 仓库 | 否（不安装） |
| POST | `/api/skills/install` | 安装指定用户 Skill | 是 |
| DELETE | `/api/skills/{name}` | 卸载用户 Skill | 是 |
| GET | `/api/traces` | 查询追踪摘要，可按状态和渠道过滤 | 否 |
| GET | `/api/traces/{trace_id}` | 查询一次追踪的完整详情 | 否 |
| GET | `/api/events` | 查询阶段事件，可按追踪 ID 和类型过滤 | 否 |
| GET | `/api/sessions` | 按开始日期、结束日期查询会话摘要 | 否 |
| GET | `/api/sessions/{session_id}` | 查询会话消息详情 | 否 |
| GET | `/api/schedules` | 列出定时任务 | 否 |
| POST | `/api/schedules` | 根据已有投递目标创建定时任务 | 是 |
| POST | `/api/schedules/{task_id}/cancel` | 停止定时任务 | 是 |
| POST | `/api/schedules/{task_id}/resume` | 恢复周期性定时任务 | 是 |

查询追踪和事件时，`limit` 的范围是 1 到 100。会话列表必须同时提供
`start_date` 和 `end_date`，详情查询可以同时提供日期范围；开始日期晚于结束日期
会返回 `422`。MCP、Skill 或定时任务服务没有初始化时返回 `503`，目标不存在时
返回 `404`，配置、参数或仓库校验失败时通常返回 `422`。

## 安全边界

管理 API 强制只绑定 `127.0.0.1` 或 `localhost`，不是公网 API，也没有为跨主机
访问设计认证协议。不要通过反向代理、端口转发或 Docker 端口映射把它直接暴露到
公网；如果需要远程运维，应先增加独立的认证、授权和传输保护层。

管理 API 虽然以查询为主，但 MCP、Skill 和定时任务路由会改变本地配置或运行状态。
调用方仍必须把它当作有副作用的本机管理接口：

- 不把 API key、Token 或用户消息放入前端代码、浏览器存储和日志；
- 安装 Skill 前检查仓库来源、目录内容和 `SKILL.md` 依赖声明；
- 保存 MCP 配置时不要把秘密写入 `~/.flow/mcp.json`；
- 对删除、卸载、停用和恢复操作保留明确的用户确认和失败提示。

## 运行目录和持久化

本机 `scripts/start.sh` 读取仓库根目录的 `config.toml`；其中以 `.flow/` 开头的
默认路径会解析到用户目录 `~/.flow/`。常见数据包括：

```text
~/.flow/
├── data/                 # 会话、记忆、任务和出站状态数据库
├── logs/                 # 应用日志、追踪和主动线路追踪
├── memory/               # Markdown 记忆和整理状态
├── sessions/             # Subagent 任务记录
├── skills/               # 用户安装的 Skill
├── plugins/              # 用户插件
├── plugin-data/          # 插件配置和私有状态
├── mcp.json              # 用户 MCP 配置
└── runtime.lock         # 工作区进程锁
```

项目共享 Skill 仍在仓库根目录 `skills/`。Docker 部署脚本当前准备并挂载项目根
`.flow/`；这是容器部署的独立挂载路径，不应默认认为它等同于本机 `~/.flow/`。
备份或迁移时要分别确认宿主机路径、容器挂载目标和 `HOME` 设置。

## 本地开发和排查

从仓库根目录启动完整本地工作台：

```bash
./scripts/dev.sh
```

或分别启动后端和前端：

```bash
./scripts/start.sh
cd frontend && ADMIN_API_BASE_URL=http://127.0.0.1:8790 npm run dev
```

排查顺序建议如下：

1. 确认后端已读取正确的 `config.toml`，且 `admin_api.enabled = true`；
2. 确认 `127.0.0.1:8790` 没有被其他进程占用；
3. 直接检查 `/api/traces`、`/api/events` 或 `/api/capabilities` 的响应；
4. 确认前端的 `ADMIN_API_BASE_URL` 指向同一个后端；
5. 若只缺少某项能力，检查对应的 MCP、Skill、插件或调度服务是否初始化成功。

管理面展示的追踪是运行时事件的诊断视图，不是消息送达保证。外部渠道的投递
仍遵循出站总线和未知结果不盲目重放的语义，详见[系统架构](../ARCHITECTURE.md)。
