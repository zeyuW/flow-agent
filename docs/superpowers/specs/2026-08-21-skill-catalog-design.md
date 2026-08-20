# Skill 目录与目录服务设计

## 目标

将普通 Skill 从单一的运行时目录改为有明确来源的目录模型，并提供只读目录服务，供管理前端展示真实的项目 Skill 与用户已安装 Skill。

本设计不实现技能市场、安装、卸载、启停或自然语言安装；这些能力以后基于本目录服务扩展。

## 范围与非目标

本次仅处理普通 Agent Skill，不处理 Drift Skill。`.flow/drift/skills/` 仍由 Drift 运行时管理，其状态与文件契约不变。

本次不改变 Agent 如何选择或执行 Skill；只统一发现与管理 API 的查询结果。

## 目录模型

```text
flow-agent/
├── backend/
│   └── src/application/capabilities/skills/builtin/  # 将来随程序发布的内置 Skill
├── skills/                                          # 项目 Skill，提交到 Git
│   └── weekly-report/
│       └── SKILL.md
└── .flow/
    └── skills/                                      # 本机已安装 Skill，不提交
        └── personal-notes/
            └── SKILL.md
```

| 来源 | 目录 | 是否展示 | 是否提交 |
| --- | --- | --- | --- |
| `builtin` | `backend/src/application/capabilities/skills/builtin/` | 否 | 是 |
| `project` | `<仓库根目录>/skills/` | 是 | 是 |
| `installed` | `<仓库根目录>/.flow/skills/` | 是 | 否 |

`SKILL.md` 是普通 Skill 的唯一描述来源。目录名、YAML frontmatter 的 `name` 与描述内容共同构成技能定义；不再要求或读取普通 Skill 的 `skill.json`。

普通 Skill 的最小文件格式为：

```markdown
---
name: weekly-report
description: 汇总项目进展并生成周报。适用于用户请求周报或进展整理时。
---

# 项目周报
...
```

现有 `requires_tools`、`requires_sources`、`requires_mcp`、视觉能力等声明继续由 `SKILL.md` frontmatter 提供。解析器同时兼容 YAML 列表和逗号分隔的字符串，以便技能仓库和手写文件都易于维护。

## 发现、冲突与状态

新增一个只读的 Skill catalog（目录服务），依次扫描内置、项目、本机已安装三个来源。每一项至少包含：

- `name`
- `description`
- `source`（`builtin`、`project`、`installed`）
- `path`（仅后端内部使用，不通过 HTTP 暴露）
- 依赖声明
- `status`（`available` 或 `conflict`）

同名 Skill 不做静默覆盖：目录服务保留冲突信息并使同名候选均不可用，日志记录来源和路径。这样可避免个人安装包意外替换项目约定的工作流。

管理前端默认不接收 `builtin` 项；若项目与已安装来源为空，显示空状态。冲突项可以在后续管理操作阶段提供解决入口，本次只在 API 中返回状态和简短原因。

## 后端边界与 API

新增应用层查询服务，负责组合 Skill catalog 与现有 `McpServerRegistry`；FastAPI 路由不直接访问文件系统或 MCP 注册表。

```text
GET /api/capabilities
{
  "skills": [
    {
      "name": "weekly-report",
      "description": "汇总项目进展并生成周报。",
      "source": "project",
      "status": "available"
    }
  ],
  "connectors": [
    {
      "name": "ai-news",
      "connected": true,
      "tools": ["news_search"]
    }
  ]
}
```

`connectors` 直接基于已有 MCP 注册表的运行态数据。前端不展示命令、环境变量和绝对路径，避免泄露本机信息。

依赖方向为：

```text
Skill catalog / MCP registry
          ↓
CapabilityQueryService（application）
          ↓
Admin router（interfaces）
          ↓
Frontend API client
```

## 迁移与兼容

1. `WorkspaceLayout` 新增项目级 `project_skills_dir`，并将 `.flow/skills` 命名为语义清晰的 `installed_skills_dir`。
2. 初始化工作区不再生成普通 Skill 的 `skill.json` 说明；在根目录 `skills/` 提供中文 README，说明它会被提交到 Git。
3. 现有普通 Skill 如仍含 `skill.json`，运行时忽略该文件，只读取同目录 `SKILL.md`；没有 `SKILL.md` 的目录不作为可用 Skill。
4. `SkillManager` 的安装/启停接口当前依赖 `skill.json`，本次不暴露这些操作；后续市场阶段会以独立安装状态存储替换它，避免重新把描述元数据拆回 JSON。

## 测试

- Skill 解析：标准 YAML frontmatter、依赖列表、缺失或非法 frontmatter。
- 目录服务：项目和已安装来源、无 Skill、同名冲突、内置项不进入前端结果。
- 管理 API：正常序列化与 MCP 状态组合。
- 前端：真实卡片、来源标签、空状态、API 失败状态。

## 后续阶段

技能市场使用独立 GitHub 仓库。安装前由 Agent 或控制台搜索候选项、展示来源和内容摘要、请求用户确认；确认后复制或下载到 `.flow/skills/<name>/`。自然语言“安装某个 Skill”只触发该确认流程，不能直接执行未知脚本或覆盖现有目录。
