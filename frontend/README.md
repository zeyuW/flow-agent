# Flow Agent Web 控制台

`frontend/` 是 Flow Agent 的本机管理控制台，使用 Next.js 构建。它通过后端管理
API 查看会话和运行状态，并管理定时任务、MCP 服务和用户 Skill；它不承载 Agent
主回合，也不直接连接 Telegram、QQ 或模型服务。

## 本地开发

首次使用时安装依赖：

```bash
cd frontend
npm ci
```

推荐从仓库根目录同时启动后端和前端：

```bash
./scripts/dev.sh
```

脚本会启动 `scripts/start.sh` 和 `npm run dev`，默认打开
<http://localhost:3000>。如果需要分别启动：

```bash
# 终端一：仓库根目录
./scripts/start.sh

# 终端二：frontend/ 目录
cd frontend
ADMIN_API_BASE_URL=http://127.0.0.1:8790 npm run dev
```

后端管理 API 默认只绑定 `127.0.0.1:8790`。Next.js 服务端通过
`ADMIN_API_BASE_URL` 代理同源 `/api` 请求，浏览器不需要直接访问后端，也不会
因为跨域访问而暴露管理地址。不要把 API key、Token、用户内容或其他密钥写入
`.env.local`、前端代码或浏览器存储。

## 控制台页面

- **会话**：按日期查询会话列表和消息历史；
- **定时任务**：查看、新建、停止和恢复定时任务；
- **技能与连接器**：查看能力快照，扫描/安装/卸载用户 Skill，管理 MCP 服务；
- **插件**：展示插件相关运行信息；
- **日志**：查看追踪记录、阶段事件和单次运行详情。

管理 API 的完整路由、边界和失败语义见[管理控制台与本机 API](../docs/features/control-plane.md)。

## 检查与构建

在 `frontend/` 目录执行：

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

## 数据与部署边界

前端只保存页面状态，不保存 Agent 的数据库、日志、追踪或凭据。后端本机运行时
默认将用户数据放在 `~/.flow/`；仓库根目录的 `config.toml` 由后端读取。Docker
部署脚本使用项目根 `.flow/` 作为挂载目录，这是容器部署的独立路径，迁移数据时
不要默认认为它等同于本机 `~/.flow/`。
