# Flow Agent 架构规范

状态：当前生效

版本：3.0

更新日期：2026-08-02

本文是项目当前唯一生效的架构规范，覆盖 `docs/specs/2026-08-01-ddd-refactor/` 中的阶段性设计、需求和任务文档。旧文档保留用于追溯，不再作为新增代码和迁移代码的判断依据。

## 一、总体原则

项目采用“业务模块 DDD + Agent 能力组件 + 共享基础设施”的混合结构：

- 用业务模块划分业务边界，不建立全局万能 `core`。
- 领域规则只放在对应模块的 `domain`。
- 应用用例、Agent 编排、事务边界和失败策略放在 `application`。
- 数据库、文件系统、第三方 SDK、消息、连接池等实现放在 `infra`。
- HTTP、CLI、MCP 和第三方 IM 渠道协议适配放在 `interfaces`。
- LLM、Tools、MCP、Skills 等可复用 Agent 能力放在 `modules/capabilities`。
- `bootstrap` 是唯一组合根，负责配置加载、依赖装配、启动和关闭。
- 迁移完成后删除 `flow_agent` 旧实现和转发层，不保留长期兼容入口。

## 二、目录职责

```text
backend/src/
├── modules/
│   ├── conversation/       # 被动回复
│   ├── proactive/          # 主动回复
│   ├── jobs/               # 后台任务
│   ├── delivery/           # 消息投递
│   ├── memory/             # 记忆能力
│   ├── delegation/         # 委托与子代理
│   ├── scheduling/         # 调度规则
│   └── capabilities/       # LLM、Tools、MCP、Skills 等通用能力
├── interfaces/             # 外部协议和渠道接入
├── infra/                  # 共享技术基础设施
└── bootstrap/              # 组合根和进程入口
```

复杂业务模块按需使用三层：

```text
modules/<business-module>/
├── domain/                 # 实体、值对象、领域服务、领域事件
├── application/            # 用例、Agent 编排、端口、事务边界
└── infra/                  # 仓储、网关、持久化和第三方实现
```

简单能力模块可以只保留实际需要的目录，不为目录完整而创建空层。

## 三、依赖方向

允许的方向：

```text
interfaces  → application / capabilities / infra
bootstrap   → interfaces / application / capabilities / infra
application → domain / capabilities / 端口协议
infra       → domain / capabilities 的协议实现
```

禁止的方向：

- `domain` 导入 `application`、`infra`、`interfaces` 或 `bootstrap`。
- `application` 直接依赖具体基础设施实现，应依赖端口或协议。
- 业务模块依赖其他业务模块的 `infra` 或 `domain`；跨模块交互使用应用端口、事件或明确的公共协议。
- `modules` 反向导入 `interfaces` 或 `bootstrap`。
- 共享 `infra` 反向依赖业务模块。

## 四、Agent、Tools、MCP 与 Skills

### Agent

Agent 是应用层编排器，不建立全局 `src/agent`：

```text
modules/conversation/application/agent.py
modules/proactive/application/loop.py
modules/delegation/application/agent.py
```

### Tools

工具协议和注册表属于通用能力：

```text
modules/capabilities/tools/
```

具体业务工具放回业务模块的 `application`，例如 `modules/jobs/application/tools.py`。

### MCP

MCP 客户端、服务器、连接池和传输实现属于能力或基础设施；MCP 不承载业务规则：

```text
interfaces/mcp/                 # 协议接入
modules/capabilities/mcp/       # 通用 MCP 能力
modules/<module>/infra/         # 业务模块专属 MCP 适配
```

### Skills

Skill 的说明、脚本和资源放在仓库根目录 `skills/`；加载器、注册表和解析器放在 `modules/capabilities/skills/`。

## 五、三条核心业务路线

### 被动回复

```text
interfaces/channels
  → conversation.application
  → conversation.domain
  → delivery.application
  → delivery.infra
```

### 主动回复

```text
proactive.application
  → proactive.domain
  → proactive.infra
  → delivery.application
```

### 后台任务

```text
conversation/application/tools
  → jobs.application
  → jobs.domain
  → jobs.infra
```

## 六、配置和组合根

- 配置文件使用单一 TOML 来源。
- 配置模型、加载器和热更新位于 `infra/config`。
- 业务模块不得主动读取全局配置。
- `bootstrap` 负责把配置切片显式注入 Agent、Worker、渠道和基础设施。
- 不使用全局 Settings Proxy、服务定位器或隐式模块级缓存。

## 七、迁移规则

- 新代码不得新增 `flow_agent` 导入。
- 迁移时先移动真实实现，再更新应用入口和组合根。
- 旧路径只能作为短期转发层，迁移完成后删除。
- 每批迁移必须通过架构检查、全量测试、类型检查和格式检查。
- 不为了兼容旧内部导入路径而保留重复实现。
