# schedule 模块高内聚改造实施计划

> **For agentic workers:** 按任务逐项执行，每个任务完成后运行对应测试。

**目标：** 将 `application.schedule` 按领域规则、应用用例和 SQLite 技术实现收敛，保持现有定时任务行为不变。

**架构：** `domain/models.py` 保存定时任务模型与纯时间规则；`app/runtime.py` 负责创建、取消、到期执行和生命周期；`infra/store.py` 负责 SQLite 持久化。应用运行时可以组装本业务自己的 infra，但 infra 不反向依赖 app。

**技术栈：** Python 3.14、dataclasses、SQLite、pytest、uv。

## 全局约束

- 不保留旧目录或兼容导出，以最新模块路径为准。
- 不改变定时任务公开行为、数据表结构和消息投递语义。
- `domain` 不依赖 `app`、`infra` 或共享基础设施。
- `infra` 不依赖 `app`。
- 不为单个函数或简单模型过度拆分文件。

---

### 任务 1：锁定模块边界和时间规则

**文件：**

- 新建：`backend/src/application/schedule/domain/models.py`
- 修改：`backend/tests/schedule/test_scheduler_tasks.py`
- 新建：`backend/tests/architecture/test_schedule_boundaries.py`

- [x] 为时间规则和模块依赖编写失败测试。
- [x] 将 `ScheduledTask`、时间解析函数移动到 domain。
- [x] 验证时间规则测试和边界测试通过。

### 任务 2：提取 SQLite 持久化

**文件：**

- 新建：`backend/src/application/schedule/infra/store.py`
- 修改：`backend/src/application/schedule/app/runtime.py`
- 修改：`backend/src/application/schedule/infra/__init__.py`

- [x] 先验证新的 `ScheduledTaskStore` 导入路径失败。
- [x] 移动 SQLite 存取实现到 `infra/store.py`。
- [x] 让 runtime 只组合 domain 和 store。
- [x] 运行 schedule 测试。

### 任务 3：更新公开导出和调用方

**文件：**

- 修改：`backend/src/application/schedule/app/__init__.py`
- 修改：`backend/src/application/schedule/app/tools.py`
- 修改：所有引用旧路径的 schedule 测试和 bootstrap 调用方

- [x] 更新导入路径。
- [x] 删除 runtime 中重复的领域和持久化代码。
- [x] 运行 schedule、architecture、integration 测试。

### 任务 4：全量验证

- [x] 运行 `git diff --check`。
- [x] 运行 Python 编译检查。
- [x] 运行 schedule 相关测试。
- [x] 运行全量测试并记录结果：322 passed。
