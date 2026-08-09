# Documentation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立一套简洁、可导航、以系统设计思路为中心的中文文档体系，让读者从项目入口逐步理解 Flow Agent 的架构和主要能力。

**Architecture:** 根目录 README 负责项目定位、快速开始和完整导航；`backend/README.md` 负责后端工程结构与开发边界；`docs/ARCHITECTURE.md` 负责跨模块架构和生命周期；`docs/features/` 按能力解释运行流程、设计取舍和边界；`docs/knowledge.md` 规定后续文档维护方式。

**Tech Stack:** Markdown、ASCII 流程图、仓库当前 Python 模块和配置行为。

## Global Constraints

- 所有新增和修改的说明使用中文，代码标识符、命令、路径和第三方专有名词保持原样。
- 根 README 保持简洁，只保留项目定位、快速开始、配置、启动和继续阅读导航。
- 功能文档解释设计思路、流程、状态、边界和恢复语义，不提供源码路径映射。
- 功能文档中的关键流程和状态关系使用 ASCII 图，不使用与当前实现不一致的图示。
- 面向展示的文档以当前代码和配置为准，不把历史规格文档当作运行说明。
- 文档示例不包含密钥、个人数据、数据库内容或运行时日志。
- 不修改用户已有的代码、测试和无关文档变更。

---

### Task 1: 建立文档总入口和根 README 导航

**Files:**
- Create: `docs/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 当前根 README 的快速开始、`docs/ARCHITECTURE.md` 和既有 `docs/specs/` 目录。
- Produces: 根 README 到全部主要文档的相对链接；`docs/README.md` 的按阅读目的分类索引。

- [ ] **Step 1: 编写 `docs/README.md` 文档索引**

  使用“第一次了解项目、理解系统能力、参与后端开发、追踪具体变更、维护文档”五条阅读路径，链接到架构文档、六篇功能文档、根 README、后端 README、`docs/specs/README.md` 和 `docs/knowledge.md`。每条入口只写一句用途说明。

- [ ] **Step 2: 精简并补齐根 README 的继续阅读区域**

  保留现有项目定位、配置、启动和 Docker 说明；把继续阅读改成直接可点击的完整导航，至少包含后端 README、文档总索引、架构文档、`agent-loop`、`passive`、`proactive`、`automation`、`memory`、`channels`、知识规则和配置示例。

- [ ] **Step 3: 检查入口链接**

  运行：

  ```bash
  rg -n '\]\([^)]*\)' README.md docs/README.md
  test -f docs/README.md
  ```

  预期：入口文件存在，导航中没有指向不存在目标的链接。

### Task 2: 更新 backend README 的开发入口

**Files:**
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: 当前 `backend/src` 目录、`backend/tests` 目录、`backend/pyproject.toml`、`config.example.toml` 和根 README。
- Produces: 面向开发者的后端目录、依赖方向、配置、启动、测试和文档导航说明。

- [ ] **Step 1: 校准后端目录与依赖边界**

  保留并核对 `application`、`interfaces`、顶层 `infra`、`bootstrap` 和 `tests` 的职责；明确 `application/<feature>/domain`、`app`、`infra` 的边界，并区分业务专属 `infra` 与顶层共享 `infra`。

- [ ] **Step 2: 补充真实运行和验证命令**

  说明从根目录启动、后端测试、Black、Pyright 和配置准备方式；命令必须与当前 `pyproject.toml` 和仓库脚本一致，并提醒真实渠道/模型验证依赖外部凭据和网络条件。

- [ ] **Step 3: 增加详细文档导航并删除重复废话**

  增加到 `../docs/README.md`、`../docs/ARCHITECTURE.md` 和六篇功能文档的链接；删除与根 README 重复的泛化介绍，不在后端 README 展开每条业务流程。

- [ ] **Step 4: 检查后端 README 的路径和命令**

  运行：

  ```bash
  rg -n 'flow_agent|old|旧|TODO|TBD' backend/README.md
  test -f README.md && test -f docs/README.md && test -f docs/ARCHITECTURE.md
  ```

  预期：没有旧入口或占位符，所有导航目标存在。

### Task 3: 校准系统架构文档

**Files:**
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: 当前 `ServiceApp` 生命周期、`MessageBus`/`EventBus` 语义、Agent Loop、被动/主动/后台/记忆/渠道边界。
- Produces: 一份以系统思想和数据流为中心的架构总览，并链接到对应功能文档。

- [ ] **Step 1: 保留并校准总体分层和生命周期**

  使用当前的接入层、回合编排层、智能体能力层、扩展层和基础设施层，说明 `ServiceApp` 的初始化、启动、等待、停止顺序；避免引入当前不存在的部署层或前端层。

- [ ] **Step 2: 明确跨能力数据流和不可绕过的边界**

  说明渠道如何进入统一消息总线，被动回合如何提交，主动/定时/后台/子 Agent 如何接入受控运行时，记忆如何通过事件旁路工作，以及出站投递为何不直接由业务模块调用平台 SDK。

- [ ] **Step 3: 补充功能文档导航**

  在被动、主动/定时/后台、扩展和阅读指引部分链接到 `docs/features/` 对应文档；架构文档只讲跨功能关系，不复制功能文档全部细节。

- [ ] **Step 4: 做架构一致性检查**

  运行：

  ```bash
  rg -n 'features/|ServiceApp|MessageBus|EventBus|TurnCommitted' docs/ARCHITECTURE.md
  git diff --check -- docs/ARCHITECTURE.md
  ```

  预期：架构文档包含关键组件和功能入口，且没有空白错误。

### Task 4: 编写 Agent Loop 与被动回复文档

**Files:**
- Create: `docs/features/agent-loop.md`
- Create: `docs/features/passive.md`

**Interfaces:**
- Consumes: 架构文档中的回合编排、会话隔离、消息总线和提交顺序。
- Produces: 读者无需查看源码即可理解共享 Agent 执行内核和被动 Turn 的完整心智模型。

- [ ] **Step 1: 编写 `agent-loop.md` 的设计说明**

  解释 Agent Loop 的职责、会话键、同会话 FIFO、跨会话并行、输入快照、模型/工具循环、停止取消和回合提交；使用 ASCII 图表示“入站消息 → 会话队列 → 回合执行 → 提交”的关系。

- [ ] **Step 2: 编写 `passive.md` 的完整链路**

  解释被动回复从渠道接收、统一化、排队、Prompt/记忆准备、Agent 推理、工具调用、失败回复、`TurnCommitted` 到出站投递的顺序；使用 ASCII 图表示正常路径和异常路径，并说明为什么先提交再投递。

- [ ] **Step 3: 补充边界和与其他能力的关系**

  明确被动回复不负责主动准入、不直接管理长期记忆存储、不绕过统一渠道投递；说明记忆、插件、MCP 和后台委托分别在何处参与。

- [ ] **Step 4: 检查两篇文档的概念一致性**

  运行：

  ```bash
  rg -n '```|ASCII|Agent Loop|TurnCommitted|同一|并行' docs/features/agent-loop.md docs/features/passive.md
  git diff --check -- docs/features/agent-loop.md docs/features/passive.md
  ```

  预期：两篇文档均有 ASCII 图、关键提交语义和并发边界，无格式错误。

### Task 5: 编写主动回复文档

**Files:**
- Create: `docs/features/proactive.md`

**Interfaces:**
- Consumes: 当前主动策略、数据源、生命周期图、判断循环、ACK、Drift 和投递语义。
- Produces: 主动回复的设计思想、准入链路、状态变化和恢复语义说明。

- [ ] **Step 1: 说明主动回复的目标和准入思想**

  解释主动回复不是“后台随便发消息”，而是由周期信号或数据源机会触发，并经过忙碌检查、频率、冷却、每日上限和策略判断后才允许触达。

- [ ] **Step 2: 绘制主动主链路和分支**

  使用 ASCII 图表达“tick → gate → source → candidate → judge → resolve/dedup → deliver → ACK”；另画出跳过、数据源失败、投递未知和 Drift 空闲任务分支。

- [ ] **Step 3: 解释重启、插件刷新和状态恢复**

  说明主动状态为什么持久化、来源 ACK 如何避免重复处理、运行时刷新如何保持新旧贡献代际一致，以及重启后如何从保存状态恢复而不重复发送未知结果。

- [ ] **Step 4: 校验主动文档没有越界描述**

  运行：

  ```bash
  rg -n '准入|冷却|ACK|Drift|重启|```' docs/features/proactive.md
  git diff --check -- docs/features/proactive.md
  ```

  预期：文档覆盖准入、ACK、Drift、重启和 ASCII 图，且没有把主动消息描述成普通用户入站消息。

### Task 6: 编写后台任务文档

**Files:**
- Create: `docs/features/automation.md`

**Interfaces:**
- Consumes: 当前 schedule、automation、delegation 的职责，以及队列、worker、持久化写入、重试和完成通知语义。
- Produces: 一份区分三类后台执行的设计说明。

- [ ] **Step 1: 区分三类后台执行**

  用表格或 ASCII 分支说明：用户定时任务服务处理用户创建的时间规则；系统自动化作业处理已注册的事件/间隔作业；委托子 Agent 处理需要独立执行和汇总的长任务。说明三者的触发者、结果和是否复用被动回合。

- [ ] **Step 2: 解释队列、并发和单写者**

  使用 ASCII 图表达生产者 → 有界队列 → 受限 worker → 唯一持久化写入者；说明为什么不能让多个 worker 直接竞争写运行记录，以及队列满、超时和取消如何处理。

- [ ] **Step 3: 解释失败恢复和消息投递**

  说明可重试错误与不可重试错误的区别、重启后的状态恢复、完成通知如何进入统一出站路径，以及后台任务不能抢占用户会话状态。

- [ ] **Step 4: 检查后台任务三分法**

  运行：

  ```bash
  rg -n '定时|自动化|委托|队列|worker|单写者|重试|```' docs/features/automation.md
  git diff --check -- docs/features/automation.md
  ```

  预期：三类后台执行边界清楚，文档包含队列/写入者图示和恢复语义。

### Task 7: 编写记忆与渠道文档

**Files:**
- Create: `docs/features/memory.md`
- Create: `docs/features/channels.md`

**Interfaces:**
- Consumes: 当前记忆检索/写入/整理语义、统一渠道适配器、消息规范化、权限和生命周期。
- Produces: 记忆系统和渠道系统的读者向设计说明。

- [ ] **Step 1: 编写 `memory.md` 的读写闭环**

  解释当前回合如何检索并注入记忆、回合提交后如何提取和去重、Markdown 与向量存储如何互补、如何检测替代关系以及维护压缩为什么与交互回路分离；使用 ASCII 图表示读路径和写路径。

- [ ] **Step 2: 编写 `channels.md` 的统一适配思想**

  解释平台协议如何转换为统一入站消息，统一消息如何携带会话/聊天/收发件人身份，出站如何根据公共地址投递，权限和平台专属元数据为何留在边界内；使用 ASCII 图表示入站和出站双向路径。

- [ ] **Step 3: 补充扩展与安全边界**

  说明新增渠道只需实现统一适配契约并注册配置，业务层不增加平台特判；说明白名单、凭据、附件校验和投递目标覆盖等边界。

- [ ] **Step 4: 检查两篇文档的架构边界**

  运行：

  ```bash
  rg -n '```|检索|注入|去重|Markdown|向量|适配|入站|出站|权限' docs/features/memory.md docs/features/channels.md
  git diff --check -- docs/features/memory.md docs/features/channels.md
  ```

  预期：两篇文档均有 ASCII 图，并清楚说明读写、规范化、投递和安全边界。

### Task 8: 建立文档知识沉淀规则

**Files:**
- Create: `docs/knowledge.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 已确认的文档职责、`docs/specs/` 现有目录和导航规则。
- Produces: 需求、实现、验证、发布后如何同步和归档文档的操作规则。

- [ ] **Step 1: 规定文档类型的适用场景**

  明确 README、架构文档、功能文档、规格文档和变更记录分别回答什么问题、面向谁、何时更新；指出 `docs/specs/` 是具体变更记录，不替代功能说明。

- [ ] **Step 2: 规定从需求到归档的流程**

  使用 ASCII 时间线表达“需求澄清 → 设计/规格 → 实现 → 验证 → 更新入口文档 → 归档”；说明哪些变更必须同时更新根 README、后端 README、架构或功能文档。

- [ ] **Step 3: 将维护规则接入 docs README**

  在 `docs/README.md` 增加到 `knowledge.md` 的明确入口，并说明文档冲突时应优先查阅当前架构规范和代码行为。

- [ ] **Step 4: 检查知识规则的可执行性**

  运行：

  ```bash
  rg -n 'README|架构|功能|规格|归档|```' docs/knowledge.md docs/README.md
  git diff --check -- docs/knowledge.md docs/README.md
  ```

  预期：规则覆盖文档类型、更新时机、流程和导航，没有模糊占位描述。

### Task 9: 全部文档校验

**Files:**
- Verify: `README.md`, `backend/README.md`, `docs/README.md`, `docs/ARCHITECTURE.md`, `docs/knowledge.md`, `docs/features/*.md`

- [ ] **Step 1: 检查文件和链接目标**

  使用 shell 脚本提取 Markdown 相对链接并确认目标存在；检查六篇功能文档和两个入口 README 都已创建或更新。

- [ ] **Step 2: 检查文档占位符和敏感内容**

  运行 `rg -n 'TODO|TBD|待定|api_key\s*=\s*[^"` ]+|bot_token\s*=\s*[^"` ]+' README.md backend/README.md docs`，只允许配置示例中的占位值，不允许真实凭据或未完成标记。

- [ ] **Step 3: 检查格式和代码回归**

  运行：

  ```bash
  git diff --check
  cd backend && uv run pytest -q
  ```

  预期：文档无空白错误，现有测试不受文档改动影响；若测试受用户已有代码修改影响，记录准确失败原因，不修改无关代码。

- [ ] **Step 4: 汇总变更和未能提交的限制**

  检查 `git diff --stat` 和 `git status --short`，只报告本次文档文件及用户原有改动；由于 `.git/index` 只读，不执行提交，向用户说明需要在可写 Git 环境中完成提交。
